from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, render
from django.db.models import Avg, Count, Q

from accounts.decorators import principal_required, school_staff_required
from accounts.models import Student, User
from .models import Assessment, AssessmentAttempt, Enrollment, LearningGap, Section, Subject, TeacherAssignment


def _school_for_staff(user):
    if getattr(user, "is_principal", False):
        from .models import School
        return School.objects.filter(principal=user, is_active=True).first()
    assignment = TeacherAssignment.objects.filter(teacher=user, is_active=True).select_related("academic_year__school").first()
    return assignment.academic_year.school if assignment else None


@login_required
@principal_required
def principal_dashboard(request):
    school = _school_for_staff(request.user)
    if not school:
        return render(request, "school/principal_dashboard.html", {"school": None, "error": "No school is assigned to this principal yet."})
    current_year = school.academic_years.filter(is_current=True).first() or school.academic_years.order_by("-id").first()
    enrollments = Enrollment.objects.filter(academic_year=current_year, is_active=True).select_related("student__student", "section__grade") if current_year else Enrollment.objects.none()
    sections = Section.objects.filter(grade__school=school).select_related("grade", "class_teacher")
    teachers = User.objects.filter(school_teacher_assignments__academic_year__school=school, school_teacher_assignments__is_active=True).distinct()
    subjects = Subject.objects.filter(school=school, is_active=True)
    attempts = AssessmentAttempt.objects.filter(assessment__grade__school=school, is_completed=True)
    gaps = LearningGap.objects.filter(student__school_enrollments__academic_year=current_year, status__in=["open", "in_progress"]).distinct() if current_year else LearningGap.objects.none()
    context = {
        "active_page": "principal",
        "page_title": "Principal Dashboard",
        "school": school, "current_year": current_year,
        "student_count": enrollments.values("student_id").distinct().count(),
        "teacher_count": teachers.count(), "section_count": sections.count(), "subject_count": subjects.count(),
        "assessment_count": Assessment.objects.filter(grade__school=school).count(),
        "average_score": round(attempts.aggregate(v=Avg("percentage"))["v"] or 0, 1),
        "open_gaps": gaps.count(),
        "sections": sections[:12], "teachers": teachers[:12],
        "recent_attempts": attempts.select_related("student__student", "assessment__subject").order_by("-completed_at")[:10],
    }
    return render(request, "school/principal_dashboard.html", context)


@login_required
@school_staff_required
def teacher_dashboard(request):
    assignments = TeacherAssignment.objects.filter(teacher=request.user, is_active=True).select_related("subject", "section__grade", "academic_year")
    school = _school_for_staff(request.user)
    sections = Section.objects.filter(teacher_assignments__teacher=request.user, teacher_assignments__is_active=True).select_related("grade").distinct()
    section_ids = sections.values_list("id", flat=True)
    enrollments = Enrollment.objects.filter(section_id__in=section_ids, is_active=True).select_related("student__student", "section__grade")
    students = Student.objects.filter(school_enrollments__section_id__in=section_ids, school_enrollments__is_active=True).distinct()
    subject_ids = assignments.values_list("subject_id", flat=True)
    assessments = Assessment.objects.filter(subject_id__in=subject_ids, grade__school=school).select_related("subject", "grade") if school else Assessment.objects.none()
    gaps = LearningGap.objects.filter(student_id__in=students.values_list("id", flat=True), status__in=["open", "in_progress"]).select_related("student__student", "concept__chapter__subject")
    attempts = AssessmentAttempt.objects.filter(student_id__in=students.values_list("id", flat=True), assessment__subject_id__in=subject_ids, is_completed=True).select_related("student__student", "assessment__subject").order_by("-completed_at")
    context = {
        "active_page": "teacher", "page_title": "Teacher Dashboard", "school": school,
        "assignments": assignments, "sections": sections, "students": students,
        "student_count": students.count(), "section_count": sections.count(),
        "assessment_count": assessments.count(), "open_gaps": gaps.count(),
        "average_score": round(attempts.aggregate(v=Avg("percentage"))["v"] or 0, 1),
        "assessments": assessments[:10], "gaps": gaps[:12], "recent_attempts": attempts[:12],
    }
    return render(request, "school/teacher_dashboard.html", context)

from django.contrib import messages
from django.db import transaction
from .forms import TeacherCreateForm, GradeCreateForm, SectionCreateForm, StudentCreateForm, AssessmentCreateForm, QuestionCreateForm
from .models import ConceptPerformance, RemedialRecommendation

@login_required
@principal_required
def principal_manage(request):
    school = _school_for_staff(request.user)
    if not school:
        return render(request, 'school/principal_manage.html', {'school': None})
    forms = {
        'teacher_form': TeacherCreateForm(school=school),
        'grade_form': GradeCreateForm(),
        'section_form': SectionCreateForm(school=school),
        'student_form': StudentCreateForm(school=school),
    }
    if request.method == 'POST':
        action = request.POST.get('action')
        mapping = {'teacher': 'teacher_form', 'grade': 'grade_form', 'section': 'section_form', 'student': 'student_form'}
        key = mapping.get(action)
        if key:
            form_cls = {'teacher': TeacherCreateForm, 'grade': GradeCreateForm, 'section': SectionCreateForm, 'student': StudentCreateForm}[action]
            kwargs = {'school': school} if action in ('teacher','section','student') else {}
            form = form_cls(request.POST, **kwargs)
            if form.is_valid():
                if action == 'teacher': form.save(school)
                elif action == 'grade':
                    obj=form.save(commit=False); obj.school=school; obj.save()
                elif action == 'section': form.save()
                else: form.save(school)
                messages.success(request, f'{action.title()} created successfully.')
                return redirect('school_principal_manage')
            forms[key] = form
    sections = Section.objects.filter(grade__school=school).select_related('grade','class_teacher').order_by('grade__order','name')
    teachers = User.objects.filter(school_teacher_assignments__academic_year__school=school, school_teacher_assignments__is_active=True).distinct().order_by('first_name')
    students = Student.objects.filter(school_enrollments__section__grade__school=school, school_enrollments__is_active=True).select_related('student').distinct().order_by('student__first_name')[:50]
    return render(request, 'school/principal_manage.html', {'school':school, 'forms':forms, 'sections':sections, 'teachers':teachers, 'students':students, 'page_title':'Manage School', 'active_page':'manage'})

@login_required
@principal_required
def principal_student_detail(request, pk):
    school = _school_for_staff(request.user)
    student = get_object_or_404(Student.objects.select_related('student'), pk=pk, school_enrollments__section__grade__school=school)
    enrollment = student.school_enrollments.filter(is_active=True).select_related('section__grade','academic_year').first()
    attempts = student.assessment_attempts.filter(is_completed=True).select_related('assessment__subject').order_by('-completed_at')[:20]
    gaps = student.learning_gaps.select_related('concept__chapter__subject').order_by('status','priority','-gap_score')
    performances = student.concept_performances.select_related('concept__chapter__subject').order_by('-mastery_score')
    return render(request,'school/student_detail_staff.html',{'school':school,'student':student,'enrollment':enrollment,'attempts':attempts,'gaps':gaps,'performances':performances,'page_title':'Student Profile'})

@login_required
@school_staff_required
def teacher_create_assessment(request):
    if not request.user.is_lecturer:
        return redirect('school_principal_dashboard')
    school = _school_for_staff(request.user)
    form = AssessmentCreateForm(request.POST or None, school=school, teacher=request.user)
    assignments = TeacherAssignment.objects.filter(teacher=request.user,is_active=True).select_related('subject','section__grade')
    questions = Question.objects.filter(concept__chapter__subject_id__in=assignments.values_list('subject_id',flat=True),concept__chapter__grade_id__in=assignments.values_list('section__grade_id',flat=True)).select_related('concept__chapter__subject').prefetch_related('options').distinct()
    if request.method == 'POST' and form.is_valid():
        assessment=form.save(); selected=request.POST.getlist('questions'); assessment.questions.set(questions.filter(pk__in=selected)); messages.success(request,'Assessment created successfully.'); return redirect('school_teacher_dashboard')
    return render(request,'school/teacher_create_assessment.html',{'school':school,'form':form,'questions':questions,'page_title':'Create Assessment','active_page':'assessments'})

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
        return redirect('school_principal_dashboard')
    student=get_object_or_404(Student.objects.select_related('student'),pk=pk)
    allowed=Enrollment.objects.filter(student=student,section__teacher_assignments__teacher=request.user,section__teacher_assignments__is_active=True).exists()
    if not allowed: return redirect('school_teacher_dashboard')
    attempts=student.assessment_attempts.filter(is_completed=True).select_related('assessment__subject').order_by('-completed_at')[:20]
    gaps=student.learning_gaps.select_related('concept__chapter__subject').filter(status__in=['open','in_progress']).order_by('priority','-gap_score')
    performances=student.concept_performances.select_related('concept__chapter__subject').order_by('-mastery_score')
    resources=LearningResource.objects.filter(concept_id__in=gaps.values_list('concept_id',flat=True),is_active=True)
    return render(request,'school/student_detail_staff.html',{'school':_school_for_staff(request.user),'student':student,'enrollment':student.school_enrollments.filter(is_active=True).select_related('section__grade').first(),'attempts':attempts,'gaps':gaps,'performances':performances,'resources':resources,'teacher_view':True,'page_title':'Student Profile'})

@login_required
@school_staff_required
def teacher_assign_remedial(request, gap_id):
    if not request.user.is_lecturer: return redirect('school_principal_dashboard')
    gap=get_object_or_404(LearningGap.objects.select_related('student','concept'),pk=gap_id)
    allowed=Enrollment.objects.filter(student=gap.student,section__teacher_assignments__teacher=request.user,section__teacher_assignments__is_active=True).exists()
    if not allowed: return redirect('school_teacher_dashboard')
    resource_id=request.POST.get('resource_id')
    resource=get_object_or_404(LearningResource,pk=resource_id,concept=gap.concept,is_active=True)
    RemedialRecommendation.objects.get_or_create(student=gap.student,concept=gap.concept,resource=resource,defaults={'reason':'Assigned by teacher for an identified learning gap.','priority':gap.priority})
    gap.status='in_progress'; gap.save(update_fields=['status'])
    messages.success(request,'Remedial resource assigned to the student.')
    return redirect('school_teacher_student_detail',pk=gap.student_id)
