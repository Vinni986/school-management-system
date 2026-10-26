
import json
import re
import tempfile
import zipfile
from pathlib import Path
from urllib.parse import urlparse

import requests
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from school.models import (
    Concept,
    LearningResource,
    NCERTQRMapping,
    School,
)


DIKSHA_SEARCH_URL = "https://diksha.gov.in/api/content/v1/search"
USER_AGENT = "SchoolLearningPlatform-NCERTDIKSHAResolver/1.0"


def resource_type_for(item):
    mime = (item.get("mimeType") or "").lower()
    url = (
        item.get("streamingUrl")
        or item.get("artifactUrl")
        or item.get("previewUrl")
        or ""
    ).lower()

    if mime.startswith("video/") or ".mp4" in url or ".m3u8" in url:
        return "video"

    if mime == "application/pdf" or url.endswith(".pdf"):
        return "pdf"

    if (
        "html" in mime
        or "h5p" in mime
        or ".html" in url
        or "/h5p/" in url
    ):
        return "interactive"

    return None


def walk(obj):
    if isinstance(obj, dict):
        yield obj
        for value in obj.values():
            yield from walk(value)

    elif isinstance(obj, list):
        for item in obj:
            yield from walk(item)


class Command(BaseCommand):
    help = "Resolve pending NCERT QR mappings using the public DIKSHA content package."

    def add_arguments(self, parser):
        parser.add_argument(
            "--school",
            required=True,
            help="School code or exact school name.",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=50,
        )

    def resolve_school(self, value):
        school = School.objects.filter(
            code=value,
            is_active=True,
        ).first()

        if school:
            return school

        school = School.objects.filter(
            name__iexact=value,
            is_active=True,
        ).first()

        if school:
            return school

        raise CommandError(
            f"No active school found for '{value}'."
        )

    def find_diksha_package(self, session, qr_code):
        payload = {
            "request": {
                "filters": {
                    "visibility": ["Default", "Parent"],
                    "dialcodes": [qr_code],
                },
                "mode": "Collection",
                "fields": [
                    "identifier",
                    "name",
                    "primaryCategory",
                    "contentType",
                    "mimeType",
                    "resourceType",
                    "children",
                    "childNodes",
                    "downloadUrl",
                    "streamingUrl",
                    "artifactUrl",
                    "dialcodes",
                ],
                "limit": 50,
            }
        }

        response = session.post(
            DIKSHA_SEARCH_URL,
            json=payload,
            timeout=60,
        )
        response.raise_for_status()

        data = response.json()
        result = data.get("result") or {}

        content = result.get("content") or []
        collections = result.get("collections") or []

        target = next(
            (
                item for item in content
                if qr_code in (item.get("dialcodes") or [])
            ),
            None,
        )

        if not target:
            return None, None

        package_url = None

        for collection in collections:
            package_url = collection.get("downloadUrl")
            if package_url:
                break

        if not package_url:
            package_url = target.get("downloadUrl")

        return target, package_url

    def download_package(self, session, url):
        response = session.get(
            url,
            timeout=120,
        )
        response.raise_for_status()

        fd, filename = tempfile.mkstemp(
            suffix=".ecar",
            prefix="diksha_",
        )
        Path(filename).write_bytes(response.content)

        import os
        os.close(fd)

        return Path(filename)

    def extract_resources(self, package_path, target_id):
        with zipfile.ZipFile(package_path) as archive:
            hierarchy = json.loads(
                archive.read("hierarchy.json")
            )

        target = None

        for item in walk(hierarchy):
            if item.get("identifier") == target_id:
                target = item
                break

        if not target:
            return []

        resources = []
        seen = set()

        for item in walk(target):
            if item.get("contentType") != "Resource":
                continue

            identifier = item.get("identifier")
            if not identifier or identifier in seen:
                continue

            url = (
                item.get("streamingUrl")
                or item.get("artifactUrl")
                or item.get("previewUrl")
            )

            resource_type = resource_type_for(item)

            if not url or not resource_type:
                continue

            seen.add(identifier)

            resources.append(
                {
                    "identifier": identifier,
                    "title": (
                        item.get("name")
                        or "NCERT Resource"
                    ),
                    "url": url,
                    "resource_type": resource_type,
                    "mimeType": item.get("mimeType") or "",
                    "description": (
                        item.get("description")
                        or ""
                    ),
                }
            )

        return resources

    def handle(self, *args, **options):
        school = self.resolve_school(options["school"])

        mappings = list(
            NCERTQRMapping.objects.filter(
                school=school,
                status="pending",
            ).select_related(
                "grade",
                "subject",
                "chapter",
            )[:options["limit"]]
        )

        if not mappings:
            self.stdout.write(
                self.style.WARNING(
                    "No pending NCERT QR mappings found."
                )
            )
            return

        session = requests.Session()
        session.headers.update(
            {
                "User-Agent": USER_AGENT,
                "Content-Type": "application/json",
            }
        )

        resolved = 0
        no_resources = 0
        still_pending = 0

        for mapping in mappings:
            self.stdout.write(
                f"\nQR {mapping.qr_code}"
            )

            package_path = None

            try:
                target, package_url = self.find_diksha_package(
                    session,
                    mapping.qr_code,
                )

                if not target:
                    raise RuntimeError(
                        "DIKSHA content search returned no matching content."
                    )

                self.stdout.write(
                    f"  DIKSHA content: {target.get('identifier')}"
                )
                self.stdout.write(
                    f"  Name: {target.get('name')}"
                )

                if not package_url:
                    raise RuntimeError(
                        "DIKSHA search returned no package download URL."
                    )

                self.stdout.write(
                    f"  Package: {package_url}"
                )

                package_path = self.download_package(
                    session,
                    package_url,
                )

                resources = self.extract_resources(
                    package_path,
                    target.get("identifier"),
                )

                self.stdout.write(
                    f"  Resources found: {len(resources)}"
                )

                if not resources:
                    mapping.status = "no_resources"
                    mapping.resource_count = 0
                    mapping.last_error = (
                        "No supported Resource objects found "
                        "under the DIKSHA chapter node."
                    )
                    mapping.save(
                        update_fields=[
                            "status",
                            "resource_count",
                            "last_error",
                            "updated_at",
                        ]
                    )
                    no_resources += 1
                    continue

                concept, _ = Concept.objects.get_or_create(
                    chapter=mapping.chapter,
                    title="NCERT Chapter Resources",
                    defaults={
                        "description": (
                            "Official NCERT/DIKSHA resources "
                            "linked to this chapter."
                        ),
                        "order": 999,
                        "difficulty": "easy",
                        "bloom_level": "understand",
                    },
                )

                imported = 0

                with transaction.atomic():
                    for resource in resources:
                        existing = LearningResource.objects.filter(
                            concept=concept,
                            url=resource["url"],
                        ).first()

                        if existing:
                            continue

                        LearningResource.objects.create(
                            concept=concept,
                            title=resource["title"][:200],
                            resource_type=resource["resource_type"],
                            url=resource["url"],
                            description=resource["description"][:5000],
                            source_name="NCERT / DIKSHA",
                            duration_minutes=0,
                            is_active=True,
                        )

                        imported += 1

                        self.stdout.write(
                            f"    NEW [{resource['resource_type']}]: "
                            f"{resource['title']}"
                        )
                        self.stdout.write(
                            f"      {resource['url']}"
                        )

                mapping.status = "resolved"
                mapping.resource_count = len(resources)
                mapping.last_error = ""
                mapping.save(
                    update_fields=[
                        "status",
                        "resource_count",
                        "last_error",
                        "updated_at",
                    ]
                )

                resolved += 1

                self.stdout.write(
                    self.style.SUCCESS(
                        f"  Imported {imported} new resource(s)."
                    )
                )

            except Exception as exc:
                mapping.status = "pending"
                mapping.last_error = str(exc)[:2000]
                mapping.save(
                    update_fields=[
                        "status",
                        "last_error",
                        "updated_at",
                    ]
                )

                still_pending += 1

                self.stdout.write(
                    self.style.WARNING(
                        f"  Still pending: {exc}"
                    )
                )

            finally:
                if package_path and package_path.exists():
                    package_path.unlink()

        self.stdout.write("")
        self.stdout.write(
            self.style.SUCCESS(
                f"DIKSHA resolver complete. "
                f"Resolved: {resolved} | "
                f"No resources: {no_resources} | "
                f"Still pending: {still_pending}"
            )
        )
