import re
import shutil
import tempfile
from difflib import SequenceMatcher
from pathlib import Path
from urllib.parse import parse_qs, urljoin, urlparse

import cv2
import fitz
import numpy as np
import requests
from bs4 import BeautifulSoup
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from school.models import Chapter, Concept, Grade, LearningResource, NCERTQRMapping, School, Subject


NCERT_HOSTS = {"ncert.nic.in", "www.ncert.nic.in"}
EPATH_HOST = "epathshala.nic.in"
USER_AGENT = "SchoolLearningPlatform-NCERTResourceSync/1.0"


def normalize(value):
    value = (value or "").lower().strip()
    value = re.sub(r"[^\w\s]", " ", value, flags=re.UNICODE)
    return re.sub(r"\s+", " ", value).strip()


def similarity(a, b):
    return SequenceMatcher(None, normalize(a), normalize(b)).ratio()


def get_text(soup):
    return re.sub(r"\s+", " ", soup.get_text(" ", strip=True))


def request_get(session, url, **kwargs):
    response = session.get(
        url,
        timeout=30,
        headers={"User-Agent": USER_AGENT},
        **kwargs,
    )
    response.raise_for_status()
    return response


def parse_book_url(url):
    parsed = urlparse(url)
    if parsed.netloc.lower() not in NCERT_HOSTS:
        raise CommandError("--book-url must be an official ncert.nic.in textbook URL.")

    query = parse_qs(parsed.query)
    if not query:
        raise CommandError("The NCERT textbook URL does not contain a textbook code/range.")

    # NCERT textbook URLs are normally like ?fecu1=0-12.
    key, values = next(iter(query.items()))
    value = values[0]
    match = re.match(r"^(\d+)-(\d+)$", value)
    if not match:
        raise CommandError(
            "Could not read the chapter range from the NCERT textbook URL. "
            "Expected a URL such as ?fecu1=0-12."
        )

    first = int(match.group(1))
    last = int(match.group(2))
    return key, first, last


def chapter_pdf_url(code, chapter_number):
    return f"https://ncert.nic.in/textbook/pdf/{code}{chapter_number:02d}.pdf"


def decode_qr_from_pdf(pdf_path):
    detector = cv2.QRCodeDetector()
    found = []

    document = fitz.open(pdf_path)
    try:
        for page_number, page in enumerate(document, start=1):
            # QR codes in printed pages can be small, so render at 2x and 3x.
            for scale in (2.0, 3.0):
                pixmap = page.get_pixmap(
                    matrix=fitz.Matrix(scale, scale),
                    colorspace=fitz.csRGB,
                    alpha=False,
                )
                image = np.frombuffer(pixmap.samples, dtype=np.uint8)
                image = image.reshape(pixmap.height, pixmap.width, pixmap.n)
                if pixmap.n == 4:
                    image = cv2.cvtColor(image, cv2.COLOR_RGBA2RGB)

                try:
                    ok, decoded, _, _ = detector.detectAndDecodeMulti(image)
                    if ok and decoded:
                        values = decoded
                    else:
                        value, _, _ = detector.detectAndDecode(image)
                        values = [value] if value else []
                except cv2.error:
                    values = []

                for value in values:
                    value = (value or "").strip()
                    if value and value not in found:
                        found.append(value)

                if found:
                    break

            if found:
                # We normally only need the QR destination(s) from the chapter.
                continue
    finally:
        document.close()

    return found


def extract_chapter_title_from_pdf(pdf_path):
    """Extract the chapter title from the first page of an NCERT PDF."""
    document = fitz.open(pdf_path)
    try:
        if not document:
            return ""

        text = document[0].get_text("text")
    finally:
        document.close()

    lines = [
        re.sub(r"\s+", " ", line).strip()
        for line in text.splitlines()
    ]

    lines = [line for line in lines if line]

    # NCERT chapter PDFs place the chapter title at the beginning
    # of the first page. Skip purely numeric lines.
    for line in lines:
        if re.fullmatch(r"\d+", line):
            continue
        if line.lower() in {"chapter", "reprint", "reprint 2026-27"}:
            continue
        if len(line) >= 4:
            return line

    return ""

def normalize_qr_destination(value):
    value = (value or "").strip()

    if not value:
        return None

    # QR codes in NCERT PDFs may contain the legacy ePathshala URL:
    # http://epathshala.nic.in/QR/?id=0677CH02
    # Convert that QR identifier to the public DIKSHA resolver.
    match = re.search(r"[?&]id=([A-Za-z0-9_-]{3,64})", value, re.I)
    if match:
        code = match.group(1)
        return f"https://diksha.gov.in/ncert/get?code={code}"

    # Plain NCERT QR/DIAL code.
    if re.fullmatch(r"[A-Za-z0-9_-]{3,64}", value):
        return f"https://diksha.gov.in/ncert/get?code={value}"

    return value


def find_topic_url(session, qr_value):
    destination = normalize_qr_destination(qr_value)

    if not destination:
        return None

    response = request_get(
        session,
        destination,
        allow_redirects=True,
    )

    return response.url or destination


def parse_topic_page(session, topic_url):
    response = request_get(session, topic_url, allow_redirects=True)
    soup = BeautifulSoup(response.text, "html.parser")
    text = get_text(soup)

    metadata = {
        "class_name": "",
        "book_name": "",
        "subject": "",
        "chapter_number": None,
        "chapter_name": "",
    }

    match = re.search(r"Class:\s*([^|]+?)\s*\|\s*Book Name:\s*([^|]+?)\s*\|", text, re.I)
    if match:
        metadata["class_name"] = match.group(1).strip()
        metadata["book_name"] = match.group(2).strip()

    match = re.search(
        r"Subject-\s*(.*?)\s*\|\s*Chapter No-\s*(\d+)\s*\|\s*Chapter Name-\s*(.*?)\s*\|",
        text,
        re.I,
    )
    if match:
        metadata["subject"] = match.group(1).strip()
        metadata["chapter_number"] = int(match.group(2))
        metadata["chapter_name"] = match.group(3).strip()

    resources = []
    for anchor in soup.find_all("a", href=True):
        label = re.sub(r"\s+", " ", anchor.get_text(" ", strip=True))
        href = urljoin(response.url, anchor["href"])
        if not href.startswith(("http://", "https://")):
            continue

        label_lower = label.lower()
        href_lower = href.lower()
        if "video" in label_lower or "video" in href_lower:
            resources.append({"title": label or "NCERT Video", "url": href})

    # Remove duplicate URLs while retaining order.
    unique = []
    seen = set()
    for item in resources:
        if item["url"] not in seen:
            seen.add(item["url"])
            unique.append(item)

    metadata["resources"] = unique
    metadata["source_url"] = response.url
    return metadata


def best_match(query, objects):
    query_normalized = normalize(query)
    exact = [obj for obj in objects if normalize(obj.title if hasattr(obj, "title") else obj.name) == query_normalized]
    if exact:
        return exact[0]

    scored = []
    for obj in objects:
        value = obj.title if hasattr(obj, "title") else obj.name
        scored.append((similarity(query, value), obj))
    scored.sort(key=lambda x: x[0], reverse=True)
    if scored and scored[0][0] >= 0.72:
        return scored[0][1]
    return None




def download_pdf_with_retry(pdf_url, pdf_path, max_attempts=5):
    """
    Download NCERT PDF with retry logic and detailed error reporting.

    Returns:
        True if successful, False otherwise
    """
    import subprocess
    import shutil
    import time

    for attempt in range(1, max_attempts + 1):
        try:
            curl_result = subprocess.run(
                [
                    "curl",
                    "-4",
                    "-L",
                    "--fail",
                    "--silent",
                    "--show-error",
                    "--max-time", "120",
                    "--retry", "2",
                    "--retry-delay", "2",
                    "--tlsv1.2",
                    "--ssl-no-revoke",
                    "-A", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                    "-o", str(pdf_path),
                    pdf_url,
                ],
                capture_output=True,
                text=True,
            )

            if curl_result.returncode == 0:
                if pdf_path.exists() and pdf_path.stat().st_size > 10000:
                    return True
                else:
                    raise RuntimeError("Downloaded file is missing or too small")

            error = curl_result.stderr.strip() or f"curl exit code {curl_result.returncode}"

            if attempt < max_attempts:
                wait_time = 2 ** attempt
                print(f"    Attempt {attempt}/{max_attempts} failed: {error}")
                print(f"    Retrying in {wait_time} seconds...")
                time.sleep(wait_time)
            else:
                raise RuntimeError(f"All {max_attempts} attempts failed. Last error: {error}")

        except Exception as exc:
            if attempt < max_attempts:
                wait_time = 2 ** attempt
                print(f"    Attempt {attempt}/{max_attempts} exception: {exc}")
                print(f"    Retrying in {wait_time} seconds...")
                time.sleep(wait_time)
            else:
                raise

    return False


class Command(BaseCommand):
    help = (
        "Download NCERT chapter PDFs temporarily, decode their QR codes, "
        "follow ePathshala resources, and import official video URLs."
    )

    def add_arguments(self, parser):
        parser.add_argument("--school", required=True, help="School code or exact school name.")
        parser.add_argument("--book-url", required=True, help="Official NCERT textbook URL, e.g. https://ncert.nic.in/textbook.php?fecu1=0-12")
        parser.add_argument("--grade", required=False, help="Existing Grade name, e.g. Class 6. If omitted, use the NCERT class metadata.")
        parser.add_argument("--subject", required=False, help="Existing Subject name. If omitted, use the NCERT subject metadata.")
        parser.add_argument("--from-chapter", type=int, default=None)
        parser.add_argument("--to-chapter", type=int, default=None)
        parser.add_argument("--dry-run", action="store_true", help="Discover and report resources without writing to the database.")
        parser.add_argument("--max-pages", type=int, default=0, help="Reserved for future QR scanning optimization.")

    def resolve_school(self, value):
        school = School.objects.filter(code=value, is_active=True).first()
        if school:
            return school
        school = School.objects.filter(name__iexact=value, is_active=True).first()
        if school:
            return school
        raise CommandError(f"No active school found for '{value}'.")

    def resolve_grade(self, school, value):
        if value:
            grade = Grade.objects.filter(school=school, name__iexact=value).first()
            if grade:
                return grade
            raise CommandError(f"Grade '{value}' does not exist in {school.name}.")
        return None

    def resolve_subject(self, school, value):
        if value:
            subject = Subject.objects.filter(school=school, name__iexact=value, is_active=True).first()
            if subject:
                return subject
            raise CommandError(f"Subject '{value}' does not exist in {school.name}.")
        return None

    def handle(self, *args, **options):
        school = self.resolve_school(options["school"])
        code, first_chapter, last_chapter = parse_book_url(options["book_url"])

        start = options["from_chapter"] if options["from_chapter"] is not None else first_chapter + 1
        end = options["to_chapter"] if options["to_chapter"] is not None else last_chapter
        if start < 1 or end < start:
            raise CommandError("Invalid chapter range.")

        forced_grade = self.resolve_grade(school, options.get("grade"))
        forced_subject = self.resolve_subject(school, options.get("subject"))

        session = requests.Session()
        session.headers.update({"User-Agent": USER_AGENT})

        imported = 0
        skipped = 0
        discovered = 0

        self.stdout.write(self.style.MIGRATE_HEADING(
            f"NCERT resource sync: {school.name} | {options['book_url']}"
        ))

        Path("data/ncert_cache").mkdir(parents=True, exist_ok=True)

        with tempfile.TemporaryDirectory(prefix="ncert_qr_") as temp_dir:
            for chapter_number in range(start, end + 1):
                pdf_url = chapter_pdf_url(code, chapter_number)
                pdf_path = Path(temp_dir) / f"{code}{chapter_number:02d}.pdf"

                self.stdout.write(f"\nChapter {chapter_number}: {pdf_url}")
                try:

                    success = download_pdf_with_retry(pdf_url, pdf_path, max_attempts=5)

                    if not success:
                        raise RuntimeError("Download failed after all retry attempts")

                except Exception as exc:

                    # Use a previously downloaded valid PDF if NCERT is unreachable.
                    cached_pdf = Path("data/ncert_cache") / pdf_path.name

                    if cached_pdf.exists():
                        try:
                            cached_doc = fitz.open(cached_pdf)
                            cached_pages = len(cached_doc)
                            cached_size = cached_pdf.stat().st_size
                            cached_doc.close()

                            if cached_pages > 0 and cached_size > 10000:
                                shutil.copy2(cached_pdf, pdf_path)
                                self.stdout.write(
                                    self.style.WARNING(
                                        f"  Download failed; using cached PDF: {cached_pdf} "
                                        f"({cached_pages} pages, {cached_size} bytes)"
                                    )
                                )
                            else:
                                raise RuntimeError("Cached PDF is invalid")

                        except Exception as cache_exc:
                            self.stdout.write(
                                self.style.WARNING(
                                    f"  Could not use cached PDF: {cache_exc}"
                                )
                            )
                            skipped += 1
                            continue
                    else:
                        self.stdout.write(
                            self.style.WARNING(
                                f"  Could not download chapter PDF after retries: {exc}"
                            )
                        )
                        skipped += 1
                        continue

                try:
                    qr_values = decode_qr_from_pdf(pdf_path)
                except Exception as exc:
                    self.stdout.write(self.style.WARNING(f"  QR decoding failed: {exc}"))
                    skipped += 1
                    continue

                self.stdout.write(f"  QR destinations found: {len(qr_values)}")

                pdf_chapter_title = extract_chapter_title_from_pdf(pdf_path)

                if pdf_chapter_title:
                    self.stdout.write(
                        f"  Chapter title from PDF: {pdf_chapter_title}"
                    )
                if not qr_values:
                    skipped += 1
                    continue

                for qr_value in qr_values:
                    try:
                        topic_url = find_topic_url(session, qr_value)
                        if not topic_url:
                            self.stdout.write(self.style.WARNING(f"  Could not resolve QR: {qr_value}"))
                            skipped += 1
                            continue

                        metadata = parse_topic_page(session, topic_url)
                        videos = metadata["resources"]

                        grade = forced_grade
                        if not grade and metadata["class_name"]:
                            grade = best_match(
                                metadata["class_name"],
                                Grade.objects.filter(school=school),
                            )

                        if not grade:
                            self.stdout.write(self.style.WARNING(
                                f"  Could not map class '{metadata['class_name']}' to an existing Grade."
                            ))
                            skipped += 1
                            continue

                        subject = forced_subject
                        if not subject and metadata["subject"]:
                            subject = best_match(
                                metadata["subject"],
                                Subject.objects.filter(
                                    school=school,
                                    is_active=True,
                                ),
                            )

                        if not subject:
                            self.stdout.write(self.style.WARNING(
                                f"  Could not map subject '{metadata['subject']}' to an existing Subject."
                            ))
                            skipped += 1
                            continue

                        chapter = None

                        chapter_query = (
                            pdf_chapter_title
                            or metadata["chapter_name"]
                        )

                        if chapter_query:
                            chapter = best_match(
                                chapter_query,
                                Chapter.objects.filter(
                                    subject=subject,
                                    grade=grade,
                                ),
                            )

                        # DIKSHA QR pages often do not expose chapter metadata.
                        # In that case, map the current PDF chapter number.
                        if not chapter:
                            chapter_fields = {
                                field.name for field in Chapter._meta.get_fields()
                            }

                            if "chapter_number" in chapter_fields:
                                chapter = Chapter.objects.filter(
                                    subject=subject,
                                    grade=grade,
                                    chapter_number=chapter_number,
                                ).first()
                            elif "order" in chapter_fields:
                                chapter = Chapter.objects.filter(
                                    subject=subject,
                                    grade=grade,
                                    order=chapter_number,
                                ).first()

                            if not chapter:
                                chapter_candidates = list(
                                    Chapter.objects.filter(
                                        subject=subject,
                                        grade=grade,
                                    ).order_by("id")
                                )

                                index = chapter_number - 1
                                if 0 <= index < len(chapter_candidates):
                                    chapter = chapter_candidates[index]

                        if not chapter and pdf_chapter_title:
                            chapter = Chapter.objects.filter(
                                subject=subject,
                                grade=grade,
                                order=chapter_number,
                            ).first()

                        if chapter and pdf_chapter_title and not options["dry_run"]:
                            if (chapter.title or "").strip().lower().endswith(" foundations"):
                                chapter.title = pdf_chapter_title[:255]
                                chapter.description = (
                                    f"NCERT {grade.name} {subject.name} "
                                    f"Chapter {chapter_number}"
                                )
                                chapter.save(update_fields=["title", "description"])
                                self.stdout.write(
                                    f"  Updated placeholder chapter title: {chapter.title}"
                                )

                        if not chapter and pdf_chapter_title and not options["dry_run"]:
                            chapter, _ = Chapter.objects.get_or_create(
                                subject=subject,
                                grade=grade,
                                order=chapter_number,
                                defaults={
                                    "title": pdf_chapter_title,
                                    "description": (
                                        f"NCERT {grade.name} {subject.name} "
                                        f"Chapter {chapter_number}"
                                    ),
                                    "estimated_minutes": 60,
                                },
                            )

                        if not chapter:
                            self.stdout.write(self.style.WARNING(
                                f"  Could not map chapter number {chapter_number} "
                                f"to an existing Chapter."
                            ))
                            skipped += 1
                            continue

                        if not videos:

                            code_match = re.search(

                                r"[?&]code=([A-Za-z0-9_-]+)",

                                topic_url,

                                re.I,

                            )

                            qr_code = code_match.group(1) if code_match else qr_value

                            resolver_url = f"https://epathshala.nic.in/QR/?id={qr_code}"



                            self.stdout.write(

                                f"  No direct resources found; saving pending QR mapping: {resolver_url}"

                            )



                            if not options["dry_run"]:

                                NCERTQRMapping.objects.update_or_create(

                                    school=school,

                                    chapter=chapter,

                                    qr_code=qr_code,

                                    defaults={

                                        "grade": grade,

                                        "subject": subject,

                                        "resolver_url": resolver_url,

                                        "status": "pending",

                                        "last_error": "",

                                    },

                                )



                            discovered += 1

                            continue



                        discovered += len(videos)

                        concepts = list(Concept.objects.filter(chapter=chapter))
                        if not concepts:
                            self.stdout.write(self.style.WARNING(
                                f"  Chapter '{chapter.title}' has no concepts; creating an NCERT resource bucket concept."
                            ))
                            if options["dry_run"]:
                                concepts = []
                            else:
                                bucket, _ = Concept.objects.get_or_create(
                                    chapter=chapter,
                                    title="NCERT Chapter Resources",
                                    defaults={
                                        "description": "Official NCERT/ePathshala resources linked to this chapter.",
                                        "order": 999,
                                        "difficulty": "easy",
                                        "bloom_level": "understand",
                                    },
                                )
                                concepts = [bucket]

                        for video in videos:
                            title = video["title"] or "NCERT Video"
                            concept = best_match(title, concepts)
                            # Chapter-level NCERT videos don't always name a concept.
                            # Use the first concept only when there is exactly one concept;
                            # otherwise skip rather than silently misclassifying content.
                            if not concept and len(concepts) == 1:
                                concept = concepts[0]
                            if not concept:
                                self.stdout.write(self.style.WARNING(
                                    f"  Video '{title}' could not be mapped to a concept; skipped."
                                ))
                                skipped += 1
                                continue

                            existing = LearningResource.objects.filter(
                                concept=concept,
                                url=video["url"],
                            ).first()
                            if existing:
                                self.stdout.write(f"  Already imported: {title}")
                                continue

                            self.stdout.write(
                                f"  NEW: {grade.name} / {subject.name} / {chapter.title} / {concept.title} / {title}"
                            )

                            if not options["dry_run"]:
                                with transaction.atomic():
                                    LearningResource.objects.create(
                                        concept=concept,
                                        title=title[:200],
                                        resource_type=video.get("resource_type", "video"),
                                        url=video["url"],
                                        description=f"NCERT/ePathshala resource for {chapter.title}.",
                                        source_name="NCERT / ePathshala",
                                        duration_minutes=0,
                                        is_active=True,
                                    )
                            imported += 1

                    except Exception as exc:
                        self.stdout.write(self.style.WARNING(f"  Resource processing failed: {exc}"))
                        skipped += 1

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(
            f"Sync complete. Discovered resources: {discovered} | New/imported: {imported} | Skipped: {skipped}"
        ))
        if options["dry_run"]:
            self.stdout.write(self.style.WARNING("Dry-run mode: no database records were created."))
