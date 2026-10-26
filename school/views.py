from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from accounts.models import Student
from .models import (
    Assessment, AssessmentAttempt, BloomPerformance, Chapter, Concept, ConceptPerformance,
    LearningGap, LearningPath, LearningResource, RemedialRecommendation,
    StudentPrediction, StudentResourceProgress, Subject, StudentAnswer,
)


def _student(request):
    return Student.objects.filter(student=request.user).first()


def _school_context(request):
    student = _student(request)
    enrollment = None
    grade = None
    if student:
        enrollment = (student.school_enrollments.filter(is_active=True)
                      .select_related("section__grade", "academic_year")
                      .order_by("-academic_year__is_current", "-academic_year__id").first())
        grade = enrollment.section.grade if enrollment else None

    subject_qs = Subject.objects.filter(is_active=True)
    if grade:
        subject_qs = subject_qs.filter(grade_subjects__grade=grade).distinct()
    subjects = list(subject_qs.prefetch_related("chapters")[:6])

    gaps_qs = LearningGap.objects.none()
    paths_qs = LearningPath.objects.none()
    predictions_qs = StudentPrediction.objects.none()
    performances_qs = ConceptPerformance.objects.none()
    attempts_qs = AssessmentAttempt.objects.none()
    if student:
        gaps_qs = student.learning_gaps.filter(status__in=["open", "in_progress"]).select_related("concept__chapter__subject")
        paths_qs = student.learning_paths.filter(is_active=True).select_related("subject").prefetch_related("items__concept")
        predictions_qs = student.predictions.select_related("subject").order_by("-calculated_at")
        performances_qs = student.concept_performances.select_related("concept__chapter__subject")
        attempts_qs = student.assessment_attempts.select_related("assessment__subject").order_by("-started_at")

    total_answers = sum(p.total_answers for p in performances_qs)
    correct_answers = sum(p.correct_answers for p in performances_qs)
    readiness = round((correct_answers / total_answers) * 100) if total_answers else 0
    mastered_count = sum(1 for p in performances_qs if p.is_mastered)
    open_gaps = gaps_qs.filter(status="open")

    # Build subject-level assessment readiness and actual learning progress.
    subject_cards = []
    completed_resource_ids = set()

    if student:
        completed_resource_ids = set(
            StudentResourceProgress.objects.filter(
                student=student,
                completed_at__isnull=False,
            ).values_list("resource_id", flat=True)
        )

    for subject in subjects:
        subject_perfs = [
            p for p in performances_qs
            if p.concept.chapter.subject_id == subject.id
        ]

        stotal = sum(p.total_answers for p in subject_perfs)
        scorrect = sum(p.correct_answers for p in subject_perfs)
        sreadiness = round((scorrect / stotal) * 100) if stotal else 0

        subject_resources = LearningResource.objects.filter(
            concept__chapter__subject=subject,
            concept__chapter__grade=grade,
            is_active=True,
        )

        resource_total = subject_resources.count()
        completed_total = subject_resources.filter(
            id__in=completed_resource_ids
        ).count()

        learning_progress = (
            round((completed_total / resource_total) * 100)
            if resource_total else 0
        )

        subject_cards.append({
            "subject": subject,
            "chapter_count": subject.chapters.filter(grade=grade).count(),
            "readiness": sreadiness,
            "learning_progress": learning_progress,
            "resource_total": resource_total,
            "completed_total": completed_total,
        })

    latest_predictions = list(predictions_qs[:6])
    latest_prediction = latest_predictions[0] if latest_predictions else None
    if latest_prediction:
        readiness = round(latest_prediction.readiness_score or readiness)

    context = {
        "student": student,
        "enrollment": enrollment,
        "grade": grade,
        "subjects": subjects,
        "subject_cards": subject_cards,
        "gaps": list(gaps_qs.order_by("priority", "-gap_score")[:8]),
        "paths": list(paths_qs[:5]),
        "predictions": latest_predictions,
        "performances": performances_qs,
        "attempts": attempts_qs,
        "subject_count": subject_qs.count(),
        "gap_count": open_gaps.count(),
        "mastered_count": mastered_count,
        "readiness": readiness,
        "learning_loss": max(0, 100 - readiness),
        "latest_prediction": latest_prediction,
    }
    return context


@login_required
def student_dashboard(request):
    if getattr(request.user, "is_principal", False):
        return redirect("school_principal_dashboard")
    if getattr(request.user, "is_lecturer", False):
        return redirect("school_teacher_dashboard")

    context = _school_context(request)
    context["active_page"] = "dashboard"
    context["page_title"] = "Dashboard"
    return render(request, "school/dashboard.html", context)


@login_required
def learning_view(request):
    context = _school_context(request)
    context["active_page"] = "learning"
    context["page_title"] = "My Learning"

    paths = context["paths"]
    context["active_path"] = paths[0] if paths else None

    grade = context.get("grade")
    student = context.get("student")

    completed_resource_ids = set()

    if student:
        completed_resource_ids = set(
            StudentResourceProgress.objects.filter(
                student=student,
                completed_at__isnull=False,
            ).values_list("resource_id", flat=True)
        )

    learning_subjects = []

    if grade:
        subject_qs = (
            Subject.objects
            .filter(
                is_active=True,
                grade_subjects__grade=grade,
            )
            .distinct()
            .order_by("name")
        )

        for subject in subject_qs:
            chapters = []

            chapter_qs = (
                Chapter.objects
                .filter(
                    grade=grade,
                    subject=subject,
                )
                .order_by("order", "id")
            )

            for chapter in chapter_qs:
                resources = list(
                    LearningResource.objects
                    .filter(
                        concept__chapter=chapter,
                        is_active=True,
                    )
                    .select_related("concept")
                    .order_by(
                        "resource_type",
                        "concept__order",
                        "order",
                        "id",
                    )
                )

                for resource in resources:
                    resource.is_completed = resource.pk in completed_resource_ids

                videos = [r for r in resources if r.resource_type == "video"]
                pdfs = [r for r in resources if r.resource_type == "pdf"]
                interactive = [r for r in resources if r.resource_type == "interactive"]
                other = [
                    r for r in resources
                    if r.resource_type not in {"video", "pdf", "interactive"}
                ]

                completed_total = sum(
                    1 for resource in resources if resource.is_completed
                )
                resource_total = len(resources)
                progress_percentage = (
                    round((completed_total / resource_total) * 100)
                    if resource_total else 0
                )

                chapters.append(
                    {
                        "chapter": chapter,
                        "videos": videos,
                        "pdfs": pdfs,
                        "interactive": interactive,
                        "other": other,
                        "resource_total": resource_total,
                        "completed_total": completed_total,
                        "progress_percentage": progress_percentage,
                    }
                )

            if chapters:
                learning_subjects.append(
                    {
                        "subject": subject,
                        "chapters": chapters,
                        "chapter_count": len(chapters),
                        "resource_count": sum(
                            chapter["resource_total"] for chapter in chapters
                        ),
                        "completed_count": sum(
                            chapter["completed_total"] for chapter in chapters
                        ),
                    }
                )

    context["learning_subjects"] = learning_subjects

    selected_subject_id = request.GET.get("subject")
    try:
        selected_subject_id = int(selected_subject_id) if selected_subject_id else None
    except (TypeError, ValueError):
        selected_subject_id = None

    valid_subject_ids = {
        item["subject"].id
        for item in learning_subjects
    }

    if selected_subject_id not in valid_subject_ids:
        selected_subject_id = None

    context["selected_subject_id"] = selected_subject_id

    return render(request, "school/learning.html", context)


@login_required
def assessment_view(request):
    context = _school_context(request)
    context["active_page"] = "assessment"
    context["page_title"] = "Assessments"

    student = context.get("student")
    grade = context.get("grade")

    assessments_qs = (
        Assessment.objects
        .filter(is_published=True)
        .select_related("subject", "grade")
        .prefetch_related("questions")
    )

    # Do not expose a class-wide list when the account has no student profile.
    if not student or not grade:
        assessments_qs = Assessment.objects.none()
    else:
        assessments_qs = assessments_qs.filter(grade=grade)

        # Completed baseline tests, quizzes and exams are no longer available.
        # Practice assessments are deliberately excluded from this filter,
        # so students can retake them.
        completed_one_time_ids = AssessmentAttempt.objects.filter(
            student=student,
            is_completed=True,
            assessment__assessment_type__in=["baseline", "quiz", "exam"],
        ).values_list("assessment_id", flat=True)

        assessments_qs = assessments_qs.exclude(
            pk__in=completed_one_time_ids
        )

    available = list(
        assessments_qs.order_by("assessment_type", "title", "id").distinct()
    )

    # Feature one assessment at the top; list the remaining assessments below.
    context["recommended_assessment"] = available[0] if available else None
    context["available_assessments"] = available[1:] if available else []
    context["assessments"] = available

    return render(request, "school/assessment.html", context)



@login_required
def start_assessment(request, pk):
    if request.method != "POST":
        return redirect("school_assessment")

    context = _school_context(request)
    student = context.get("student")
    grade = context.get("grade")

    if not student or not grade:
        messages.error(
            request,
            "An active student enrollment is required to start an assessment."
        )
        return redirect("school_assessment")

    assessment = get_object_or_404(
        Assessment.objects.filter(
            is_published=True,
            grade=grade,
        ),
        pk=pk,
    )

    if not assessment.questions.filter(is_active=True).exists():
        messages.error(request, "This assessment has no active questions.")
        return redirect("school_assessment")

    if assessment.assessment_type in {"baseline", "quiz", "exam"}:
        already_completed = AssessmentAttempt.objects.filter(
            student=student,
            assessment=assessment,
            is_completed=True,
        ).exists()

        if already_completed:
            messages.info(
                request,
                "This assessment has already been completed."
            )
            return redirect("school_assessment")

    # Resume an unfinished attempt instead of creating duplicates.
    attempt = AssessmentAttempt.objects.filter(
        student=student,
        assessment=assessment,
        is_completed=False,
    ).order_by("-id").first()

    if attempt is None:
        attempt = AssessmentAttempt.objects.create(
            student=student,
            assessment=assessment,
        )

    return redirect("school_take_assessment", pk=attempt.pk)



@login_required
def take_assessment(request, pk):
    student = _student(request)
    attempt = get_object_or_404(AssessmentAttempt.objects.select_related("assessment"), pk=pk, student=student)
    if attempt.is_completed:
        return redirect("school_assessment_result", pk=attempt.pk)
    questions = list(attempt.assessment.questions.filter(is_active=True).prefetch_related("options"))
    if request.method == "POST":
        with transaction.atomic():
            StudentAnswer.objects.filter(attempt=attempt).delete()
            total = 0
            score = 0
            for question in questions:
                total += question.marks
                selected_id = request.POST.get(f"question_{question.pk}")
                selected = question.options.filter(pk=selected_id).first() if selected_id else None
                correct = bool(selected and selected.is_correct)
                awarded = question.marks if correct else 0
                score += awarded
                StudentAnswer.objects.create(
                    attempt=attempt, question=question, selected_option=selected,
                    is_correct=correct, marks_awarded=awarded,
                )
            attempt.score = score
            attempt.percentage = round((score / total) * 100, 2) if total else 0
            attempt.completed_at = timezone.now()
            attempt.is_completed = True
            attempt.save(update_fields=["score", "percentage", "completed_at", "is_completed"])
            _recalculate_student(student)
        return redirect("school_assessment_result", pk=attempt.pk)
    return render(request, "school/take_assessment.html", {"attempt": attempt, "questions": questions, "page_title": attempt.assessment.title})


@login_required
def assessment_result(request, pk):
    student = _student(request)
    attempt = get_object_or_404(AssessmentAttempt.objects.select_related("assessment__subject"), pk=pk, student=student)
    return render(request, "school/assessment_result.html", {"attempt": attempt, "answers": attempt.answers.select_related("question", "selected_option"), "page_title": "Assessment Result"})


def _recalculate_student(student):
    answers = StudentAnswer.objects.filter(attempt__student=student).select_related("question__concept", "question__concept__chapter__subject")
    concept_ids = answers.values_list("question__concept_id", flat=True).distinct()
    for concept_id in concept_ids:
        concept_answers = answers.filter(question__concept_id=concept_id)
        total = concept_answers.count()
        correct = concept_answers.filter(is_correct=True).count()
        mastery = (correct / total) * 100 if total else 0
        ConceptPerformance.objects.update_or_create(
            student=student, concept_id=concept_id,
            defaults={"attempts": concept_answers.values("attempt_id").distinct().count(), "correct_answers": correct,
                      "total_answers": total, "mastery_score": mastery, "confidence_score": mastery,
                      "last_assessed_at": timezone.now(), "is_mastered": mastery >= 80},
        )
        concept = Concept.objects.get(pk=concept_id)
        gap = LearningGap.objects.filter(student=student, concept=concept).first()
        if mastery < 80:
            LearningGap.objects.update_or_create(
                student=student, concept=concept,
                defaults={"gap_score": round(100 - mastery, 2), "reason": "Assessment performance is below the mastery threshold.",
                          "priority": 1 if mastery < 50 else 2, "status": "open"},
            )
        elif gap:
            gap.status = "cleared"
            gap.cleared_at = timezone.now()
            gap.save(update_fields=["status", "cleared_at"])

    subject_ids = answers.values_list("question__concept__chapter__subject_id", flat=True).distinct()
    for subject_id in subject_ids:
        subject_answers = answers.filter(question__concept__chapter__subject_id=subject_id)
        total = subject_answers.count()
        correct = subject_answers.filter(is_correct=True).count()
        accuracy = (correct / total) * 100 if total else 0
        BloomPerformance.objects.update_or_create(
            student=student, subject_id=subject_id, bloom_level="overall",
            defaults={"accuracy": accuracy, "total_questions": total, "correct_questions": correct},
        )
        StudentPrediction.objects.create(
            student=student, subject_id=subject_id, predicted_score=round(accuracy, 2),
            readiness_score=round(accuracy, 2), learning_loss_percentage=round(100 - accuracy, 2),
        )


@login_required
def gaps_view(request):
    context = _school_context(request)
    context["active_page"] = "gaps"
    context["page_title"] = "Learning Gaps"
    if context["student"]:
        context["all_gaps"] = context["student"].learning_gaps.select_related("concept__chapter__subject").order_by("status", "priority", "-gap_score")
    else:
        context["all_gaps"] = []
    context["gap_count"] = context["all_gaps"].filter(status="open").count() if context["student"] else 0
    context["high_priority_count"] = context["all_gaps"].filter(status__in=["open", "in_progress"], priority=1).count() if context["student"] else 0
    context["in_progress_count"] = context["all_gaps"].filter(status="in_progress").count() if context["student"] else 0
    return render(request, "school/gaps.html", context)


@login_required
def reports_view(request):
    context = _school_context(request)
    context["active_page"] = "reports"
    context["page_title"] = "My Reports"
    context["bloom"] = (context["student"].bloom_performances.filter(bloom_level__in=["remember", "understand", "apply", "analyze", "evaluate", "create"])
                         if context["student"] else [])
    return render(request, "school/reports.html", context)


@login_required
def resources_view(request):
    context = _school_context(request)
    context["layout_template"] = (
        "school/staff_layout.html"
        if (
            getattr(request.user, "is_lecturer", False)
            or getattr(request.user, "is_principal", False)
        )
        else "school/layout.html"
    )
    context["active_page"] = "resources"
    context["page_title"] = "Resources"
    resources = (
        LearningResource.objects
        .filter(is_active=True)
        .select_related("concept__chapter__subject")
        .order_by(
            "concept__chapter__order",
            "concept__chapter__id",
            "resource_type",
            "order",
            "id",
        )
    )

    # STUDENT_ENROLLMENT_RESOURCE_SCOPE
    # Students see resources for their currently active enrolled class only.
    if context.get("student"):
        enrollment = (
            context["student"].school_enrollments
            .filter(is_active=True)
            .select_related("section__grade", "academic_year")
            .order_by(
                "-academic_year__is_current",
                "-academic_year__id",
            )
            .first()
        )

        if enrollment:
            resources = resources.filter(
                concept__chapter__grade_id=enrollment.section.grade_id
            )
        else:
            # Do not expose other classes' resources without an enrollment.
            resources = resources.none()

    # TEACHER_ASSIGNMENT_RESOURCE_SCOPE
    # Teachers can see resources only for their assigned class/subject pairs.
    if (
        getattr(request.user, "is_lecturer", False)
        and not getattr(request.user, "is_principal", False)
    ):
        from django.db.models import Q
        from .models import TeacherAssignment, GradeSubject

        assignments = TeacherAssignment.objects.filter(
            teacher=request.user,
            is_active=True,
        ).select_related(
            "subject", "section__grade", "academic_year"
        )

        assigned_scope = Q(pk__in=[])

        for assignment in assignments:
            assignment_school_id = assignment.academic_year.school_id

            if assignment.section_id:
                assigned_scope |= Q(
                    concept__chapter__grade_id=assignment.section.grade_id,
                    concept__chapter__subject_id=assignment.subject_id,
                    concept__chapter__grade__school_id=assignment_school_id,
                )
            else:
                grade_ids = GradeSubject.objects.filter(
                    grade__school_id=assignment_school_id,
                    subject_id=assignment.subject_id,
                ).values_list("grade_id", flat=True)

                assigned_scope |= Q(
                    concept__chapter__grade_id__in=grade_ids,
                    concept__chapter__subject_id=assignment.subject_id,
                    concept__chapter__grade__school_id=assignment_school_id,
                )

        resources = resources.filter(assigned_scope).distinct()

    if context["student"]:
        gaps = context["student"].learning_gaps.filter(
            status__in=["open", "in_progress"]
        ).select_related("concept__chapter").order_by(
            "priority", "-gap_score", "id"
        )

        recommended_resources = []
        seen_resource_ids = set()

        for gap in gaps:
            if gap.concept.title == "NCERT Chapter Resources":
                # A chapter-level gap can benefit from resources throughout
                # that chapter, including topic-mapped material.
                candidates = resources.filter(
                    concept__chapter_id=gap.concept.chapter_id
                )
            else:
                candidates = resources.filter(
                    concept_id=gap.concept_id
                )

                if not candidates.exists():
                    candidates = resources.filter(
                        concept__chapter_id=gap.concept.chapter_id,
                        concept__title="NCERT Chapter Resources",
                    )

            for resource in candidates:
                if resource.pk in seen_resource_ids:
                    continue

                seen_resource_ids.add(resource.pk)
                recommended_resources.append(resource)

                if len(recommended_resources) >= 12:
                    break

            if len(recommended_resources) >= 12:
                break

        context["recommended_resources"] = recommended_resources

    subject_map = {}

    for resource in resources:
        chapter = resource.concept.chapter
        subject = chapter.subject

        if subject.id not in subject_map:
            subject_map[subject.id] = {
                "subject": subject,
                "total": 0,
                "chapters": {},
            }

        subject_group = subject_map[subject.id]
        subject_group["total"] += 1

        if chapter.id not in subject_group["chapters"]:
            subject_group["chapters"][chapter.id] = {
                "chapter": chapter,
                "videos": [],
                "pdfs": [],
                "interactive": [],
                "other": [],
                "total": 0,
            }

        chapter_group = subject_group["chapters"][chapter.id]
        chapter_group["total"] += 1

        if resource.resource_type == "video":
            chapter_group["videos"].append(resource)
        elif resource.resource_type == "pdf":
            chapter_group["pdfs"].append(resource)
        elif resource.resource_type == "interactive":
            chapter_group["interactive"].append(resource)
        else:
            chapter_group["other"].append(resource)

    subject_groups = []

    for subject_group in subject_map.values():
        subject_group["chapters"] = list(
            sorted(
                subject_group["chapters"].values(),
                key=lambda item: (item["chapter"].order, item["chapter"].id),
            )
        )
        subject_groups.append(subject_group)

    context["subject_groups"] = subject_groups
    context["resource_total"] = resources.count()

    return render(request, "school/resources.html", context)


@login_required
def resource_open(request, pk):
    resource = get_object_or_404(
        LearningResource.objects.select_related("concept__chapter"),
        pk=pk,
        is_active=True,
    )

    student = _student(request)

    if student:
        StudentResourceProgress.objects.get_or_create(
            student=student,
            resource=resource,
        )

    if resource.url:
        return redirect(resource.url)

    if resource.file:
        return redirect(resource.file.url)

    messages.info(request, "This resource does not have a file or URL yet.")
    return redirect("school_resources")


@login_required
def resource_complete(request, pk):
    if request.method != "POST":
        return redirect("school_learning")

    resource = get_object_or_404(
        LearningResource,
        pk=pk,
        is_active=True,
    )

    student = _student(request)

    if not student:
        messages.error(request, "A student profile is required.")
        return redirect("school_learning")

    progress, _ = StudentResourceProgress.objects.get_or_create(
        student=student,
        resource=resource,
    )

    if not progress.completed_at:
        progress.completed_at = timezone.now()
        progress.save(update_fields=["completed_at", "updated_at"])
        messages.success(request, "Resource marked as completed.")

    return redirect(
        f"/en/school/learning/?subject={resource.concept.chapter.subject_id}"
        f"#subject-{resource.concept.chapter.subject_id}"
    )
