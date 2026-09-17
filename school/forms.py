from django import forms
from django.contrib.auth import get_user_model

from accounts.models import Student
from .models import (
    AcademicYear, Assessment, Chapter, Concept, Enrollment, Grade, LearningResource,
    Question, QuestionOption, Section, Subject, TeacherAssignment
)

User = get_user_model()

class TeacherCreateForm(forms.Form):
    first_name = forms.CharField(max_length=150)
    last_name = forms.CharField(max_length=150, required=False)
    email = forms.EmailField(required=False)
    username = forms.CharField(max_length=150)
    password = forms.CharField(widget=forms.PasswordInput, min_length=6)
    subject = forms.ModelChoiceField(queryset=Subject.objects.none())
    section = forms.ModelChoiceField(queryset=Section.objects.none())

    def __init__(self, *args, school=None, **kwargs):
        super().__init__(*args, **kwargs)
        if school:
            self.fields['subject'].queryset = Subject.objects.filter(school=school, is_active=True)
            self.fields['section'].queryset = Section.objects.filter(grade__school=school).select_related('grade')

    def save(self, school):
        user = User.objects.create_user(
            username=self.cleaned_data['username'], password=self.cleaned_data['password'],
            first_name=self.cleaned_data['first_name'], last_name=self.cleaned_data['last_name'],
            email=self.cleaned_data['email'], is_lecturer=False,
        )
        user.is_lecturer = True
        user.save(update_fields=['is_lecturer'])
        section = self.cleaned_data['section']
        year = AcademicYear.objects.filter(school=school, is_current=True).first() or AcademicYear.objects.filter(school=school).order_by('-id').first()
        TeacherAssignment.objects.create(teacher=user, subject=self.cleaned_data['subject'], section=section, academic_year=year)
        if not school.principal:
            school.principal = None
        return user

class GradeCreateForm(forms.ModelForm):
    class Meta:
        model = Grade
        fields = ('name', 'order')

class SectionCreateForm(forms.ModelForm):
    class Meta:
        model = Section
        fields = ('grade', 'name', 'class_teacher')

    def __init__(self, *args, school=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['grade'].queryset = Grade.objects.filter(school=school) if school else Grade.objects.none()
        self.fields['class_teacher'].queryset = User.objects.filter(is_lecturer=True) if school else User.objects.none()

class StudentCreateForm(forms.Form):
    first_name = forms.CharField(max_length=150)
    last_name = forms.CharField(max_length=150, required=False)
    username = forms.CharField(max_length=150)
    password = forms.CharField(widget=forms.PasswordInput, min_length=6)
    section = forms.ModelChoiceField(queryset=Section.objects.none())
    roll_number = forms.CharField(max_length=30, required=False)
    admission_number = forms.CharField(max_length=50, required=False)

    def __init__(self, *args, school=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['section'].queryset = Section.objects.filter(grade__school=school).select_related('grade') if school else Section.objects.none()

    def save(self, school):
        section = self.cleaned_data['section']
        user = User.objects.create_user(username=self.cleaned_data['username'], password=self.cleaned_data['password'], first_name=self.cleaned_data['first_name'], last_name=self.cleaned_data['last_name'], is_student=False)
        user.is_student = True
        user.save(update_fields=['is_student'])
        program = __import__('course.models', fromlist=['Program']).Program.objects.first()
        student = Student.objects.create(student=user, program=program)
        year = AcademicYear.objects.filter(school=school, is_current=True).first() or AcademicYear.objects.filter(school=school).order_by('-id').first()
        Enrollment.objects.create(student=student, academic_year=year, section=section, roll_number=self.cleaned_data['roll_number'], admission_number=self.cleaned_data['admission_number'])
        return student

class AssessmentCreateForm(forms.ModelForm):
    class Meta:
        model = Assessment
        fields = ('grade', 'subject', 'title', 'assessment_type', 'time_limit_minutes', 'passing_percentage', 'is_published')

    def __init__(self, *args, school=None, teacher=None, **kwargs):
        super().__init__(*args, **kwargs)
        assignments = TeacherAssignment.objects.filter(teacher=teacher, is_active=True) if teacher else TeacherAssignment.objects.none()
        self.fields['subject'].queryset = Subject.objects.filter(id__in=assignments.values_list('subject_id', flat=True))
        self.fields['grade'].queryset = Grade.objects.filter(id__in=assignments.values_list('section__grade_id', flat=True))

class QuestionCreateForm(forms.Form):
    concept = forms.ModelChoiceField(queryset=Concept.objects.none())
    text = forms.CharField(widget=forms.Textarea(attrs={'rows': 3}))
    difficulty = forms.ChoiceField(choices=Concept._meta.get_field('difficulty').choices)
    bloom_level = forms.ChoiceField(choices=Concept._meta.get_field('bloom_level').choices)
    marks = forms.IntegerField(min_value=1, initial=1)
    option_a = forms.CharField(max_length=500)
    option_b = forms.CharField(max_length=500)
    option_c = forms.CharField(max_length=500, required=False)
    option_d = forms.CharField(max_length=500, required=False)
    correct = forms.ChoiceField(choices=(('a','A'),('b','B'),('c','C'),('d','D')))
    explanation = forms.CharField(widget=forms.Textarea(attrs={'rows':2}), required=False)

    def __init__(self, *args, teacher=None, **kwargs):
        super().__init__(*args, **kwargs)
        assignments = TeacherAssignment.objects.filter(teacher=teacher, is_active=True)
        self.fields['concept'].queryset = Concept.objects.filter(chapter__subject_id__in=assignments.values_list('subject_id', flat=True), chapter__grade_id__in=assignments.values_list('section__grade_id', flat=True)).select_related('chapter__subject')

    def save(self):
        q = Question.objects.create(concept=self.cleaned_data['concept'], text=self.cleaned_data['text'], difficulty=self.cleaned_data['difficulty'], bloom_level=self.cleaned_data['bloom_level'], marks=self.cleaned_data['marks'], explanation=self.cleaned_data['explanation'])
        for key, order in [('a',1),('b',2),('c',3),('d',4)]:
            text = self.cleaned_data.get(f'option_{key}')
            if text:
                QuestionOption.objects.create(question=q, text=text, order=order, is_correct=self.cleaned_data['correct'] == key)
        return q
