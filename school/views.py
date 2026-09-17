from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from accounts.models import Student
from .models import (
    Assessment, AssessmentAttempt, BloomPerformance, Chapter, Concept, ConceptPerformance,
    LearningGap, LearningPath, LearningResource, RemedialRecommendation, StudentPrediction,
    Subject, StudentAnswer,
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

    # Build subject-level progress so the dashboard does not show the same
    # global readiness number for every subject.
    subject_cards = []
    for subject in subjects:
        subject_perfs = [p for p in performances_qs if p.concept.chapter.subject_id == subject.id]
        stotal = sum(p.total_answers for p in subject_perfs)
        scorrect = sum(p.correct_answers for p in subject_perfs)
        sreadiness = round((scorrect / stotal) * 100) if stotal else 0
        subject_cards.append({
            "subject": subject,
            "chapter_count": subject.chapters.count(),
            "readiness": sreadiness,
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
    return render(request, "school/learning.html", context)


@login_required
def assessment_view(request):
    context = _school_context(request)
    context["active_page"] = "assessment"
    context["page_title"] = "Assessments"
    grade = context["grade"]
    qs = Assessment.objects.filter(is_published=True).select_related("subject", "grade").prefetch_related("questions")
    if grade:
        qs = qs.filter(grade=grade)
    context["assessments"] = qs.order_by("assessment_type", "title")
    return render(request, "school/assessment.html", context)


@login_required
def start_assessment(request, pk):
    if request.method != "POST":
        return redirect("school_assessment")
    student = _student(request)
    assessment = get_object_or_404(Assessment, pk=pk, is_published=True)
    if not student:
        messages.error(request, "A student profile is required to start an assessment.")
        return redirect("school_assessment")
    attempt = AssessmentAttempt.objects.create(student=student, assessment=assessment)
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
    context["active_page"] = "resources"
    context["page_title"] = "Resources"
    resources = LearningResource.objects.filter(is_active=True).select_related("concept__chapter__subject")
    if context["student"]:
        gap_concepts = context["student"].learning_gaps.filter(status__in=["open", "in_progress"]).values_list("concept_id", flat=True)
        recommended = resources.filter(concept_id__in=gap_concepts)
        context["recommended_resources"] = recommended[:12]
    context["resources"] = resources[:24]
    return render(request, "school/resources.html", context)


@login_required
def resource_open(request, pk):
    resource = get_object_or_404(LearningResource, pk=pk, is_active=True)
    if resource.url:
        return redirect(resource.url)
    if resource.file:
        return redirect(resource.file.url)
    messages.info(request, "This resource does not have a file or URL yet.")
    return redirect("school_resources")
