from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, render, redirect
from django.db.models import Avg, Count, Q

from accounts.decorators import principal_required, school_staff_required
from accounts.models import Student, User
from .models import Assessment, AssessmentAttempt, Enrollment, GradeSubject, Question, LearningGap, Section, Subject, TeacherAssignment, LearningResource, Concept


def _school_for_staff(user):
    if getattr(user, "is_principal", False):
        from .models import School
        return School.objects.filter(principal=user, is_active=True).first()
    assignment = TeacherAssignment.objects.filter(teacher=user, is_active=True).select_related("academic_year__school").first()
    return assignment.academic_year.school if assignment else None



@login_required
@principal_required
def principal_dashboard(request):
    from django.db.models import F

    school = _school_for_staff(request.user)
    if not school:
        return render(request, "school/principal_dashboard.html", {
            "school": None,
            "error": "No school is assigned to this principal yet.",
        })

    current_year = (
        school.academic_years.filter(is_current=True).first()
        or school.academic_years.order_by("-id").first()
    )

    sections = Section.objects.filter(
        grade__school=school
    ).select_related(
        "grade", "class_teacher"
    ).order_by("grade__order", "name")

    subjects = Subject.objects.filter(school=school, is_active=True)

    if current_year:
        enrollments = Enrollment.objects.filter(
            academic_year=current_year,
            is_active=True,
            section__grade__school=school,
        ).select_related("student__student", "section__grade")

        teachers = User.objects.filter(
            school_teacher_assignments__academic_year=current_year,
            school_teacher_assignments__is_active=True,
        ).distinct().order_by("first_name", "last_name")

        attempts = AssessmentAttempt.objects.filter(
            student__school_enrollments__academic_year=current_year,
            student__school_enrollments__is_active=True,
            student__school_enrollments__section__grade_id=F(
                "assessment__grade_id"
            ),
            assessment__grade__school=school,
            is_completed=True,
        ).select_related(
            "student__student", "assessment__subject"
        ).distinct()

        gaps = LearningGap.objects.filter(
            student__school_enrollments__academic_year=current_year,
            student__school_enrollments__is_active=True,
            student__school_enrollments__section__grade_id=F(
                "concept__chapter__grade_id"
            ),
            concept__chapter__grade__school=school,
            status__in=["open", "in_progress"],
        ).select_related(
            "student__student", "concept__chapter__subject"
        ).distinct()
    else:
        enrollments = Enrollment.objects.none()
        teachers = User.objects.none()
        attempts = AssessmentAttempt.objects.none()
        gaps = LearningGap.objects.none()

    context = {
        "active_page": "principal",
        "page_title": "Principal Dashboard",
        "school": school,
        "current_year": current_year,
        "student_count": enrollments.values("student_id").distinct().count(),
        "teacher_count": teachers.count(),
        "section_count": sections.count(),
        "subject_count": subjects.count(),
        "assessment_count": Assessment.objects.filter(
            grade__school=school
        ).count(),
        "average_score": round(
            attempts.aggregate(v=Avg("percentage"))["v"] or 0, 1
        ),
        "open_gaps": gaps.count(),
        "sections": sections[:12],
        "teachers": teachers[:12],
        "recent_attempts": attempts.order_by("-completed_at")[:10],
    }
    return render(request, "school/principal_dashboard.html", context)



@login_required
@school_staff_required
def teacher_dashboard(request):
    if not request.user.is_lecturer:
        return redirect("school_principal_dashboard")

    school = _school_for_staff(request.user)
    assignment_qs = TeacherAssignment.objects.filter(
        teacher=request.user,
        is_active=True,
    ).select_related(
        "subject", "section__grade", "academic_year"
    ).order_by("subject__name", "section__grade__name", "section__name")

    if school:
        assignment_qs = assignment_qs.filter(academic_year__school=school)

    assignments = list(assignment_qs)

    explicit_section_ids = {
        a.section_id for a in assignments if a.section_id is not None
    }
    all_section_grade_ids = set()

    for assignment in assignments:
        if assignment.section_id is None and school:
            grade_ids = GradeSubject.objects.filter(
                subject_id=assignment.subject_id,
                grade__school=school,
            ).values_list("grade_id", flat=True)
            all_section_grade_ids.update(grade_ids)

    # Each tuple represents one authorized grade/subject/year scope.
    scopes = []
    for assignment in assignments:
        if assignment.section_id is not None:
            scopes.append((
                assignment.section.grade_id,
                assignment.subject_id,
                assignment.section_id,
                assignment.academic_year_id,
            ))
        else:
            grade_ids = GradeSubject.objects.filter(
                subject_id=assignment.subject_id,
                grade__school=school,
            ).values_list("grade_id", flat=True) if school else []
            for grade_id in grade_ids:
                scopes.append((
                    grade_id,
                    assignment.subject_id,
                    None,
                    assignment.academic_year_id,
                ))

    if school:
        sections = Section.objects.filter(
            grade__school=school
        ).filter(
            Q(pk__in=explicit_section_ids)
            | Q(grade_id__in=all_section_grade_ids)
        ).select_related("grade").distinct()
    else:
        sections = Section.objects.none()

    year_ids = {a.academic_year_id for a in assignments}
    enrollments = Enrollment.objects.filter(
        section__in=sections,
        academic_year_id__in=year_ids,
        is_active=True,
    ).select_related(
        "student__student", "section__grade", "academic_year"
    ).order_by(
        "section__grade__name", "section__name",
        "student__student__first_name", "student__student__last_name"
    ).distinct()

    students = Student.objects.filter(
        school_enrollments__in=enrollments
    ).distinct()

    assessment_scope = Q(pk__in=[])
    gap_scope = Q(pk__in=[])
    attempt_scope = Q(pk__in=[])

    for grade_id, subject_id, section_id, year_id in scopes:
        assessment_scope |= Q(
            grade_id=grade_id,
            subject_id=subject_id,
        )

        student_enrollment_scope = Q(
            student__school_enrollments__academic_year_id=year_id,
            student__school_enrollments__is_active=True,
        )

        attempt_enrollment_scope = Q(
            student__school_enrollments__academic_year_id=year_id,
            student__school_enrollments__is_active=True,
        )

        if section_id is not None:
            student_enrollment_scope &= Q(
                student__school_enrollments__section_id=section_id
            )
            attempt_enrollment_scope &= Q(
                student__school_enrollments__section_id=section_id
            )
        else:
            student_enrollment_scope &= Q(
                student__school_enrollments__section__grade_id=grade_id
            )
            attempt_enrollment_scope &= Q(
                student__school_enrollments__section__grade_id=grade_id
            )

        gap_scope |= student_enrollment_scope & Q(
            concept__chapter__grade_id=grade_id,
            concept__chapter__subject_id=subject_id,
        )

        attempt_scope |= attempt_enrollment_scope & Q(
            assessment__grade_id=grade_id,
            assessment__subject_id=subject_id,
        )

    if school and scopes:
        assessments = Assessment.objects.filter(
            assessment_scope,
            grade__school=school,
        ).select_related("subject", "grade").distinct()
    else:
        assessments = Assessment.objects.none()

    if scopes:
        gaps = LearningGap.objects.filter(
            student_id__in=students.values_list("id", flat=True),
            status__in=["open", "in_progress"],
        ).filter(gap_scope).select_related(
            "student__student", "concept__chapter__subject"
        ).distinct()

        attempts = AssessmentAttempt.objects.filter(
            student_id__in=students.values_list("id", flat=True),
            is_completed=True,
        ).filter(attempt_scope).select_related(
            "student__student", "assessment__subject"
        ).order_by("-completed_at").distinct()
    else:
        gaps = LearningGap.objects.none()
        attempts = AssessmentAttempt.objects.none()

    context = {
        "active_page": "teacher",
        "page_title": "Teacher Dashboard",
        "school": school,
        "assignments": assignments,
        "sections": sections,
        "students": students,
        "student_enrollments": enrollments[:50],
        "student_count": students.count(),
        "section_count": sections.count(),
        "assessment_count": assessments.count(),
        "open_gaps": gaps.count(),
        "average_score": round(attempts.aggregate(v=Avg("percentage"))["v"] or 0, 1),
        "assessments": assessments[:10],
        "gaps": gaps.order_by("priority", "-gap_score")[:12],
        "recent_attempts": attempts[:12],
    }
    return render(request, "school/teacher_dashboard.html", context)

from django.contrib import messages
from django.db import transaction
from .forms import TeacherCreateForm, GradeCreateForm, SectionCreateForm, StudentCreateForm, AssessmentCreateForm, QuestionCreateForm, LearningResourceImportForm
from .models import ConceptPerformance, RemedialRecommendation


@login_required
@principal_required
def principal_manage(request):
    school = _school_for_staff(request.user)
    if not school:
        return render(request, "school/principal_manage.html", {
            "school": None,
            "error": "No school is assigned to this principal yet.",
        })

    forms = {
        "teacher_form": TeacherCreateForm(school=school),
        "grade_form": GradeCreateForm(school=school),
        "section_form": SectionCreateForm(school=school),
        "student_form": StudentCreateForm(school=school),
    }

    form_classes = {
        "teacher": TeacherCreateForm,
        "grade": GradeCreateForm,
        "section": SectionCreateForm,
        "student": StudentCreateForm,
    }
    form_keys = {
        "teacher": "teacher_form",
        "grade": "grade_form",
        "section": "section_form",
        "student": "student_form",
    }

    if request.method == "POST":
        action = request.POST.get("action")
        form_class = form_classes.get(action)
        form_key = form_keys.get(action)

        if not form_class:
            messages.error(request, "Choose a valid management action.")
        else:
            form = form_class(request.POST, school=school)
            if form.is_valid():
                with transaction.atomic():
                    if action == "teacher":
                        form.save(school)
                    elif action == "grade":
                        grade = form.save(commit=False)
                        grade.school = school
                        grade.save()
                    elif action == "section":
                        form.save()
                    else:
                        form.save(school)

                messages.success(
                    request,
                    f"{action.title()} created successfully.",
                )
                return redirect("school_principal_manage")

            forms[form_key] = form

    current_year = (
        school.academic_years.filter(is_current=True).first()
        or school.academic_years.order_by("-id").first()
    )

    sections = Section.objects.filter(
        grade__school=school
    ).select_related(
        "grade", "class_teacher"
    ).order_by("grade__order", "name")

    if current_year:
        teachers = User.objects.filter(
            school_teacher_assignments__academic_year=current_year,
            school_teacher_assignments__is_active=True,
        ).distinct().order_by("first_name", "last_name")

        students = Student.objects.filter(
            school_enrollments__academic_year=current_year,
            school_enrollments__section__grade__school=school,
            school_enrollments__is_active=True,
        ).select_related(
            "student"
        ).distinct().order_by(
            "student__first_name", "student__last_name"
        )[:50]
    else:
        teachers = User.objects.none()
        students = Student.objects.none()

    return render(request, "school/principal_manage.html", {
        "school": school,
        "forms": forms,
        "sections": sections,
        "teachers": teachers,
        "students": students,
        "page_title": "Manage School",
        "active_page": "manage",
    })





@login_required
@principal_required
def principal_student_detail(request, pk):
    school = _school_for_staff(request.user)
    if not school:
        messages.error(request, "No school is assigned to this principal.")
        return redirect("school_principal_dashboard")

    student = get_object_or_404(
        Student.objects.filter(
            school_enrollments__section__grade__school=school,
            school_enrollments__is_active=True,
        ).distinct(),
        pk=pk,
    )

    enrollment = student.school_enrollments.filter(
        is_active=True,
        section__grade__school=school,
        academic_year__school=school,
    ).select_related(
        "section__grade", "academic_year"
    ).order_by(
        "-academic_year__is_current", "-academic_year__id"
    ).first()

    attempts = student.assessment_attempts.filter(
        is_completed=True,
        assessment__grade__school=school,
    ).select_related(
        "assessment__subject"
    ).order_by("-completed_at")[:20]

    gaps = list(
        student.learning_gaps.filter(
            status__in=["open", "in_progress"],
            concept__chapter__grade__school=school,
        ).select_related(
            "concept__chapter__subject"
        ).order_by("priority", "-gap_score").distinct()
    )

    performances = student.concept_performances.filter(
        concept__chapter__grade__school=school,
    ).select_related(
        "concept__chapter__subject"
    ).order_by("-mastery_score")

    for gap in gaps:
        resources = LearningResource.objects.filter(
            concept_id=gap.concept_id,
            is_active=True,
        ).select_related(
            "concept__chapter__subject"
        ).order_by("order", "id")

        if not resources.exists():
            resources = LearningResource.objects.filter(
                concept__chapter_id=gap.concept.chapter_id,
                concept__title="NCERT Chapter Resources",
                is_active=True,
            ).select_related(
                "concept__chapter__subject"
            ).order_by("order", "id")

        gap.remedial_resources = list(resources)

    return render(request, "school/student_detail_staff.html", {
        "school": school,
        "student": student,
        "enrollment": enrollment,
        "attempts": attempts,
        "gaps": gaps,
        "performances": performances,
        "principal_view": True,
        "page_title": "Student Profile",
    })


@login_required
@principal_required
def principal_assign_remedial(request, gap_id):
    if request.method != "POST":
        return redirect("school_principal_dashboard")

    school = _school_for_staff(request.user)
    if not school:
        messages.error(request, "No school is assigned to this principal.")
        return redirect("school_principal_dashboard")

    gap = get_object_or_404(
        LearningGap.objects.select_related(
            "student", "concept__chapter__grade"
        ),
        pk=gap_id,
        status__in=["open", "in_progress"],
        concept__chapter__grade__school=school,
        student__school_enrollments__section__grade__school=school,
        student__school_enrollments__is_active=True,
    )

    resources = LearningResource.objects.filter(
        concept_id=gap.concept_id,
        is_active=True,
    )
    if not resources.exists():
        resources = LearningResource.objects.filter(
            concept__chapter_id=gap.concept.chapter_id,
            concept__title="NCERT Chapter Resources",
            is_active=True,
        )

    resource = get_object_or_404(
        resources,
        pk=request.POST.get("resource_id"),
    )

    RemedialRecommendation.objects.get_or_create(
        student=gap.student,
        concept=gap.concept,
        resource=resource,
        defaults={
            "reason": "Assigned by principal for an identified learning gap.",
            "priority": gap.priority,
        },
    )

    if gap.status != "in_progress":
        gap.status = "in_progress"
        gap.save(update_fields=["status"])

    messages.success(request, "Remedial resource assigned to the student.")
    return redirect("school_principal_student_detail", pk=gap.student_id)



@login_required
@school_staff_required
def teacher_create_assessment(request):
    from .models import GradeSubject, Question

    if not request.user.is_lecturer:
        return redirect("school_principal_dashboard")

    school = _school_for_staff(request.user)
    form = AssessmentCreateForm(
        request.POST or None,
        school=school,
        teacher=request.user,
    )

    assignments = TeacherAssignment.objects.filter(
        teacher=request.user,
        is_active=True,
    ).select_related("subject", "section__grade", "academic_year")

    if school:
        assignments = assignments.filter(academic_year__school=school)

    # Construct valid assignment pairs, not a cross-product of grades and subjects.
    allowed = Q(pk__in=[])

    for assignment in assignments:
        if assignment.section_id:
            allowed |= Q(
                concept__chapter__grade_id=assignment.section.grade_id,
                concept__chapter__subject_id=assignment.subject_id,
            )
        else:
            grade_ids = GradeSubject.objects.filter(
                subject_id=assignment.subject_id,
                grade__school_id=assignment.academic_year.school_id,
            ).values_list("grade_id", flat=True)

            allowed |= Q(
                concept__chapter__grade_id__in=grade_ids,
                concept__chapter__subject_id=assignment.subject_id,
            )

    available_questions = Question.objects.filter(
        allowed
    ).select_related(
        "concept__chapter__grade",
        "concept__chapter__subject",
    ).prefetch_related("options").distinct().order_by(
        "concept__chapter__grade__name",
        "concept__chapter__subject__name",
        "id",
    )

    if request.method == "POST" and form.is_valid():
        selected_ids = request.POST.getlist("questions")

        matching_questions = available_questions.filter(
            pk__in=selected_ids,
            concept__chapter__grade=form.cleaned_data["grade"],
            concept__chapter__subject=form.cleaned_data["subject"],
        ).distinct()

        if not matching_questions.exists():
            messages.error(
                request,
                "Select at least one question matching the chosen grade and subject.",
            )
        else:
            with transaction.atomic():
                assessment = form.save()
                assessment.questions.set(matching_questions)

            messages.success(request, "Assessment created successfully.")
            return redirect("school_teacher_dashboard")

    questions = available_questions
    selected_grade = request.POST.get("grade") or request.GET.get("grade")
    selected_subject = request.POST.get("subject") or request.GET.get("subject")

    if selected_grade:
        questions = questions.filter(
            concept__chapter__grade_id=selected_grade
        )
    if selected_subject:
        questions = questions.filter(
            concept__chapter__subject_id=selected_subject
        )

    return render(request, "school/teacher_create_assessment.html", {
        "school": school,
        "form": form,
        "questions": questions,
        "page_title": "Create Assessment",
        "active_page": "assessments",
    })


@login_required
@school_staff_required
def teacher_create_question(request):
    if not request.user.is_lecturer:
        return redirect('school_principal_dashboard')
    form=QuestionCreateForm(request.POST or None, teacher=request.user)
    if request.method=='POST' and form.is_valid():
        form.save(); messages.success(request,'Question created successfully.'); return redirect('school_teacher_create_assessment')
    school=_school_for_staff(request.user)
    return render(request,'school/teacher_create_question.html',{'school':school,'form':form,'page_title':'Create Question','active_page':'assessments'})

@login_required
@school_staff_required
def teacher_student_detail(request, pk):
    if not request.user.is_lecturer:
        return redirect("school_principal_dashboard")

    student = get_object_or_404(
        Student.objects.select_related("student"),
        pk=pk,
    )
    school = _school_for_staff(request.user)

    enrollments = Enrollment.objects.filter(
        student=student,
        is_active=True,
    ).select_related(
        "section__grade", "academic_year"
    ).order_by("-academic_year__is_current", "-academic_year__id")

    allowed_pairs = set()
    matching_enrollment = None

    for enrollment in enrollments:
        if school and enrollment.section.grade.school_id != school.id:
            continue

        matching_assignments = TeacherAssignment.objects.filter(
            teacher=request.user,
            is_active=True,
            academic_year=enrollment.academic_year,
        ).filter(
            Q(section=enrollment.section) | Q(section__isnull=True)
        ).select_related("subject")

        for assignment in matching_assignments:
            if assignment.section_id is None:
                subject_is_taught_in_grade = GradeSubject.objects.filter(
                    grade=enrollment.section.grade,
                    subject_id=assignment.subject_id,
                ).exists()
                if not subject_is_taught_in_grade:
                    continue

            allowed_pairs.add((
                enrollment.section.grade_id,
                assignment.subject_id,
            ))
            if matching_enrollment is None:
                matching_enrollment = enrollment

    if not allowed_pairs:
        messages.info(request, "This student is not in your assigned teaching scope.")
        return redirect("school_teacher_dashboard")

    attempt_scope = Q(pk__in=[])
    concept_scope = Q(pk__in=[])

    for grade_id, subject_id in allowed_pairs:
        attempt_scope |= Q(
            assessment__grade_id=grade_id,
            assessment__subject_id=subject_id,
        )
        concept_scope |= Q(
            concept__chapter__grade_id=grade_id,
            concept__chapter__subject_id=subject_id,
        )

    attempts = student.assessment_attempts.filter(
        is_completed=True
    ).filter(
        attempt_scope
    ).select_related(
        "assessment__subject"
    ).order_by("-completed_at")[:20]

    gaps = student.learning_gaps.filter(
        status__in=["open", "in_progress"]
    ).filter(
        concept_scope
    ).select_related(
        "concept__chapter__subject"
    ).order_by("priority", "-gap_score")

    performances = student.concept_performances.filter(
        concept_scope
    ).select_related(
        "concept__chapter__subject"
    ).order_by("-mastery_score")

    # Prefer resources linked to the exact gap concept.
    # Fall back to generic chapter resources when no exact match exists.
    for gap in gaps:
        topic_resources = list(
            LearningResource.objects.filter(
                concept_id=gap.concept_id,
                is_active=True,
            ).select_related(
                "concept__chapter__subject"
            ).order_by("order", "id")
        )

        if topic_resources:
            gap.remedial_resources = topic_resources
        else:
            gap.remedial_resources = list(
                LearningResource.objects.filter(
                    concept__chapter_id=gap.concept.chapter_id,
                    concept__title="NCERT Chapter Resources",
                    is_active=True,
                ).select_related(
                    "concept__chapter__subject"
                ).order_by("order", "id")
            )

    return render(request, "school/student_detail_staff.html", {
        "school": school,
        "student": student,
        "enrollment": matching_enrollment,
        "attempts": attempts,
        "gaps": gaps,
        "performances": performances,
        "teacher_view": True,
        "page_title": "Student Profile",
    })


def _decode_qr_image(uploaded_file):
    """Decode the first QR code from an uploaded image."""
    try:
        import cv2
        import numpy as np
        data = uploaded_file.read()
        image = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
        if image is None:
            return ""
        detector = cv2.QRCodeDetector()
        value, points, _ = detector.detectAndDecode(image)
        return (value or "").strip()
    except Exception:
        return ""


def _resource_import_school(user):
    return _school_for_staff(user)


@login_required
@school_staff_required
def resource_import(request):
    school = _resource_import_school(request.user)
    if not school:
        return render(request, "school/resource_import.html", {
            "school": None, "page_title": "Import Learning Resource",
            "error": "No school is assigned to this account yet.",
        })

    form = LearningResourceImportForm(request.POST or None, request.FILES or None, school=school, teacher=request.user)
    decoded_url = ""
    if request.method == "POST" and request.POST.get("action") == "decode_qr":
        qr_image = request.FILES.get("qr_image")
        if not qr_image:
            messages.error(request, "Please upload a QR code image.")
        else:
            decoded_url = _decode_qr_image(qr_image)
            if decoded_url:
                form = LearningResourceImportForm(initial={"url": decoded_url, "source_name": "NCERT"}, school=school, teacher=request.user)
                messages.success(request, "QR code decoded successfully. Review the URL and save the resource.")
            else:
                messages.error(request, "No readable QR code was found in that image.")
    elif request.method == "POST" and request.POST.get("action") == "save_resource":
        if form.is_valid():
            url = form.cleaned_data.get("url") or _decode_qr_image(form.cleaned_data["qr_image"])
            if not url:
                form.add_error("url", "The QR image could not be decoded. Try a clearer image or paste the URL.")
            else:
                concept = form.cleaned_data["concept"]
                if request.user.is_lecturer:
                    from .models import GradeSubject

                    grade = concept.chapter.grade
                    resource_subject = concept.chapter.subject

                    if (
                        grade.school_id != school.id
                        or resource_subject.school_id != school.id
                    ):
                        allowed = False
                    else:
                        assignment_base = TeacherAssignment.objects.filter(
                            teacher=request.user,
                            subject=resource_subject,
                            is_active=True,
                            academic_year__school=school,
                        )

                        section_allowed = assignment_base.filter(
                            section__grade=grade
                        ).exists()

                        grade_wide_allowed = (
                            assignment_base.filter(
                                section__isnull=True
                            ).exists()
                            and GradeSubject.objects.filter(
                                grade=grade,
                                subject=resource_subject,
                            ).exists()
                        )

                        allowed = section_allowed or grade_wide_allowed
                    if not allowed:
                        form.add_error("concept", "You can only add resources for your assigned subjects/classes.")
                    else:
                        title = form.cleaned_data["title"] or "Official learning video"
                        LearningResource.objects.create(
                            concept=concept, title=title, resource_type=form.cleaned_data["resource_type"],
                            url=url, description=form.cleaned_data["description"],
                            source_name=form.cleaned_data["source_name"] or "Official source",
                            duration_minutes=form.cleaned_data["duration_minutes"] or 0,
                        )
                        messages.success(request, "Learning resource added and linked to the concept.")
                        return redirect("school_resource_import")
                else:
                    title = form.cleaned_data["title"] or "Official learning video"
                    LearningResource.objects.create(
                        concept=concept, title=title, resource_type=form.cleaned_data["resource_type"],
                        url=url, description=form.cleaned_data["description"],
                        source_name=form.cleaned_data["source_name"] or "Official source",
                        duration_minutes=form.cleaned_data["duration_minutes"] or 0,
                    )
                    messages.success(request, "Learning resource added and linked to the concept.")
                    return redirect("school_resource_import")

    # TEACHER_ASSIGNMENT_IMPORT_SCOPE
    resources_query = LearningResource.objects.filter(
        concept__chapter__subject__school=school
    ).select_related(
        "concept__chapter__subject", "concept__chapter__grade"
    )

    if (
        getattr(request.user, "is_lecturer", False)
        and not getattr(request.user, "is_principal", False)
    ):
        from django.db.models import Q
        from .models import GradeSubject

        assignments = TeacherAssignment.objects.filter(
            teacher=request.user,
            is_active=True,
            academic_year__school=school,
        ).select_related(
            "subject", "section__grade", "academic_year"
        )

        assigned_scope = Q(pk__in=[])

        for assignment in assignments:
            if assignment.section_id:
                assigned_scope |= Q(
                    concept__chapter__grade_id=assignment.section.grade_id,
                    concept__chapter__subject_id=assignment.subject_id,
                    concept__chapter__grade__school_id=school.id,
                )
            else:
                grade_ids = GradeSubject.objects.filter(
                    grade__school=school,
                    subject_id=assignment.subject_id,
                ).values_list("grade_id", flat=True)

                assigned_scope |= Q(
                    concept__chapter__grade_id__in=grade_ids,
                    concept__chapter__subject_id=assignment.subject_id,
                    concept__chapter__grade__school_id=school.id,
                )

        resources_query = resources_query.filter(assigned_scope).distinct()

    resources = resources_query.order_by("-id")[:30]
    return render(request, "school/resource_import.html", {
        "school": school, "form": form, "resources": resources,
        "page_title": "Import Learning Resource", "active_page": "resources",
        "decoded_url": decoded_url,
    })


@login_required
@school_staff_required
def teacher_assign_remedial(request, gap_id):
    from .models import GradeSubject

    if request.method != "POST":
        return redirect("school_teacher_dashboard")

    if not request.user.is_lecturer:
        return redirect("school_principal_dashboard")

    gap = get_object_or_404(
        LearningGap.objects.select_related(
            "student",
            "concept__chapter__grade",
            "concept__chapter__subject",
        ),
        pk=gap_id,
        status__in=["open", "in_progress"],
    )

    school = _school_for_staff(request.user)
    grade = gap.concept.chapter.grade
    subject = gap.concept.chapter.subject

    if (
        not school
        or grade.school_id != school.id
        or subject.school_id != school.id
    ):
        messages.error(request, "This learning gap is outside your school.")
        return redirect("school_teacher_dashboard")

    allowed = False

    enrollments = Enrollment.objects.filter(
        student=gap.student,
        is_active=True,
        section__grade=grade,
        academic_year__school=school,
    ).select_related("section", "academic_year")

    for enrollment in enrollments:
        assignment_base = TeacherAssignment.objects.filter(
            teacher=request.user,
            subject=subject,
            academic_year=enrollment.academic_year,
            is_active=True,
        )

        if assignment_base.filter(section=enrollment.section).exists():
            allowed = True
            break

        grade_wide_allowed = (
            assignment_base.filter(section__isnull=True).exists()
            and GradeSubject.objects.filter(
                grade=grade,
                subject=subject,
            ).exists()
        )

        if grade_wide_allowed:
            allowed = True
            break

    if not allowed:
        messages.error(
            request,
            "You are not assigned to this student's class and subject."
        )
        return redirect("school_teacher_dashboard")

    # Match the resource options shown on the student's profile:
    # exact concept resources first, generic chapter resources as fallback.
    candidates = LearningResource.objects.filter(
        concept_id=gap.concept_id,
        is_active=True,
    )

    if not candidates.exists():
        candidates = LearningResource.objects.filter(
            concept__chapter_id=gap.concept.chapter_id,
            concept__title="NCERT Chapter Resources",
            is_active=True,
        )

    resource = get_object_or_404(
        candidates,
        pk=request.POST.get("resource_id"),
    )

    RemedialRecommendation.objects.get_or_create(
        student=gap.student,
        concept=gap.concept,
        resource=resource,
        defaults={
            "reason": "Assigned by teacher for an identified learning gap.",
            "priority": gap.priority,
        },
    )

    if gap.status != "in_progress":
        gap.status = "in_progress"
        gap.save(update_fields=["status"])

    messages.success(request, "Remedial resource assigned to the student.")
    return redirect("school_teacher_student_detail", pk=gap.student_id)


@login_required
@principal_required
def principal_teacher_detail(request, pk):
    from django.contrib.auth import get_user_model
    from django.db.models import Avg, Q
    from django.shortcuts import get_object_or_404, redirect, render
    from accounts.models import Student
    from .models import (
        TeacherAssignment, Enrollment, GradeSubject,
        AssessmentAttempt, LearningGap,
    )

    school = _school_for_staff(request.user)
    if not school:
        messages.error(request, "No school is assigned to this principal.")
        return redirect("school_principal_dashboard")

    UserModel = get_user_model()
    teacher = get_object_or_404(
        UserModel.objects.filter(
            is_lecturer=True,
            school_teacher_assignments__academic_year__school=school,
            school_teacher_assignments__is_active=True,
        ).distinct(),
        pk=pk,
    )

    assignments = list(
        TeacherAssignment.objects.filter(
            teacher=teacher,
            is_active=True,
            academic_year__school=school,
        ).select_related(
            "subject", "section__grade", "academic_year"
        ).order_by(
            "-academic_year__id", "subject__name", "section__name"
        )
    )

    student_enrollments = {}
    attempt_scope = Q(assessment__pk__in=[])
    gap_scope = Q(pk__in=[])

    for assignment in assignments:
        if assignment.section_id:
            grade_ids = [assignment.section.grade_id]
            enrollments = Enrollment.objects.filter(
                academic_year=assignment.academic_year,
                section=assignment.section,
                is_active=True,
            )
        else:
            grade_ids = list(
                GradeSubject.objects.filter(
                    grade__school=school,
                    subject_id=assignment.subject_id,
                ).values_list("grade_id", flat=True)
            )
            enrollments = Enrollment.objects.filter(
                academic_year=assignment.academic_year,
                section__grade__school=school,
                section__grade_id__in=grade_ids,
                is_active=True,
            )

        for grade_id in grade_ids:
            attempt_scope |= Q(
                assessment__grade_id=grade_id,
                assessment__subject_id=assignment.subject_id,
            )
            gap_scope |= Q(
                concept__chapter__grade_id=grade_id,
                concept__chapter__subject_id=assignment.subject_id,
            )

        for enrollment in enrollments.select_related(
            "student__student", "section__grade", "academic_year"
        ).order_by("-academic_year__id"):
            student_enrollments.setdefault(enrollment.student_id, enrollment)

    student_ids = list(student_enrollments)

    if student_ids and assignments:
        attempts = AssessmentAttempt.objects.filter(
            student_id__in=student_ids,
            is_completed=True,
        ).filter(
            attempt_scope
        ).select_related(
            "student__student", "assessment__subject"
        ).order_by("-completed_at")

        average_score = round(
            attempts.aggregate(value=Avg("percentage"))["value"] or 0,
            1,
        )
        recent_attempts = attempts[:10]

        gaps = LearningGap.objects.filter(
            student_id__in=student_ids,
            status__in=["open", "in_progress"],
        ).filter(
            gap_scope
        ).select_related(
            "student__student", "concept__chapter__subject"
        ).distinct().order_by("priority", "-gap_score")
    else:
        attempts = AssessmentAttempt.objects.none()
        recent_attempts = attempts
        average_score = 0
        gaps = LearningGap.objects.none()

    students = sorted(
        student_enrollments.values(),
        key=lambda enrollment: (
            enrollment.section.grade.order,
            enrollment.section.name,
            enrollment.student.student.first_name.casefold(),
            enrollment.student.student.last_name.casefold(),
        ),
    )

    return render(request, "school/principal_teacher_detail.html", {
        "school": school,
        "teacher": teacher,
        "assignments": assignments,
        "students": students[:100],
        "student_count": len(student_enrollments),
        "assessment_count": attempts.count(),
        "average_score": average_score,
        "open_gaps": gaps.count(),
        "gaps": gaps[:20],
        "recent_attempts": recent_attempts,
        "page_title": "Teacher Profile",
        "active_page": "manage",
    })
