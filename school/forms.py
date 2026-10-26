from django import forms
from django.contrib.auth import get_user_model

from accounts.models import Student
from .models import (
    AcademicYear, Assessment, Chapter, Concept, Enrollment, Grade, LearningResource,
    Question, QuestionOption, Section, Subject, TeacherAssignment
)

User = get_user_model()



class SectionByGradeSelect(forms.Select):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.grade_map = {}

    def create_option(
        self, name, value, label, selected, index,
        subindex=None, attrs=None
    ):
        option = super().create_option(
            name, value, label, selected, index,
            subindex=subindex, attrs=attrs
        )
        raw_value = getattr(value, "value", value)
        grade_id = self.grade_map.get(str(raw_value))
        if grade_id is not None:
            option["attrs"]["data-grade-id"] = str(grade_id)
        return option



class TeacherCreateForm(forms.Form):
    first_name = forms.CharField(max_length=150)
    last_name = forms.CharField(max_length=150, required=False)
    email = forms.EmailField(required=False)
    username = forms.CharField(max_length=150)
    password = forms.CharField(widget=forms.PasswordInput, min_length=6)
    subject = forms.ModelChoiceField(queryset=Subject.objects.none())
    grade = forms.ModelChoiceField(
        queryset=Grade.objects.none(),
        label="Class",
        empty_label="Select class",
    )
    section = forms.ModelChoiceField(
        queryset=Section.objects.none(),
        label="Section",
        empty_label="Select section",
        widget=SectionByGradeSelect(),
    )

    def __init__(self, *args, school=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.school = school

        if school:
            self.fields["subject"].queryset = Subject.objects.filter(
                school=school,
                is_active=True,
            ).order_by("name")

            self.fields["grade"].queryset = Grade.objects.filter(
                school=school,
            ).order_by("order", "name")

            sections = Section.objects.filter(
                grade__school=school,
            ).select_related("grade").order_by(
                "grade__order", "grade__name", "name"
            )

            self.fields["section"].queryset = sections
            self.fields["section"].widget.grade_map = {
                str(section.pk): str(section.grade_id)
                for section in sections
            }
            self.fields["section"].label_from_instance = (
                lambda section: f"Section {section.name}"
            )

    def clean_username(self):
        username = self.cleaned_data["username"].strip()
        if User.objects.filter(username__iexact=username).exists():
            raise forms.ValidationError(
                "This username already exists. Choose another."
            )
        return username

    def clean(self):
        cleaned = super().clean()
        school = self.school
        subject = cleaned.get("subject")
        grade = cleaned.get("grade")
        section = cleaned.get("section")

        if not school:
            raise forms.ValidationError(
                "No school is assigned to this principal."
            )

        if subject and subject.school_id != school.id:
            self.add_error("subject", "Choose a subject in this school.")

        if grade and grade.school_id != school.id:
            self.add_error("grade", "Choose a class in this school.")

        if section and section.grade.school_id != school.id:
            self.add_error("section", "Choose a section in this school.")

        if grade and section and section.grade_id != grade.pk:
            self.add_error(
                "section",
                "Choose a section that belongs to the selected class.",
            )

        if not AcademicYear.objects.filter(school=school).exists():
            raise forms.ValidationError(
                "Create an academic year before adding teachers."
            )

        return cleaned



    def save(self, school):
        from django.db import transaction

        if not self.is_valid():
            raise ValueError("Cannot save an invalid teacher form.")

        year = (
            AcademicYear.objects.filter(
                school=school, is_current=True
            ).first()
            or AcademicYear.objects.filter(
                school=school
            ).order_by("-id").first()
        )

        if not year:
            raise ValueError("A school academic year is required.")

        username = self.cleaned_data["username"].strip()
        password = self.cleaned_data["password"]
        subject = self.cleaned_data["subject"]
        grade = self.cleaned_data["grade"]
        section = self.cleaned_data["section"]

        if (
            subject.school_id != school.id
            or grade.school_id != school.id
            or section.grade_id != grade.pk
        ):
            raise ValueError(
                "The selected subject, class and section must match this school."
            )

        with transaction.atomic():
            teacher = User(
                username=username,
                first_name=self.cleaned_data["first_name"],
                last_name=self.cleaned_data["last_name"],
                email=self.cleaned_data.get("email", ""),
                is_lecturer=True,
            )

            # Tell the post_save signal not to replace these credentials.
            teacher._preserve_supplied_credentials = True
            teacher._supplied_password = password
            teacher.set_password(password)
            teacher.save()

            TeacherAssignment.objects.create(
                teacher=teacher,
                subject=subject,
                section=section,
                academic_year=year,
                is_active=True,
            )

        return teacher




class GradeCreateForm(forms.ModelForm):
    class Meta:
        model = Grade
        fields = ("name", "order")

    def __init__(self, *args, school=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.school = school

    def clean_name(self):
        name = self.cleaned_data["name"].strip()
        if not self.school:
            raise forms.ValidationError("A school must be assigned first.")
        duplicates = Grade.objects.filter(
            school=self.school,
            name__iexact=name,
        ).exclude(pk=self.instance.pk)
        if duplicates.exists():
            raise forms.ValidationError(
                "A class with this name already exists in this school."
            )
        return name



class SectionCreateForm(forms.ModelForm):
    class Meta:
        model = Section
        fields = ("grade", "name", "class_teacher")

    def __init__(self, *args, school=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["grade"].label = "Class"
        self.fields["grade"].empty_label = "Select class"
        self.fields["name"].label = "Section"
        self.fields["name"].help_text = "Enter a section name, e.g. A or B."
        self.school = school
        self.fields["grade"].queryset = (
            Grade.objects.filter(school=school).order_by("order", "name")
            if school else Grade.objects.none()
        )
        self.fields["class_teacher"].queryset = (
            User.objects.filter(
                is_lecturer=True,
                school_teacher_assignments__is_active=True,
                school_teacher_assignments__academic_year__school=school,
            ).distinct()
            if school else User.objects.none()
        )

    def clean(self):
        cleaned = super().clean()
        grade = cleaned.get("grade")
        name = cleaned.get("name")
        teacher = cleaned.get("class_teacher")

        if not self.school:
            raise forms.ValidationError("A school must be assigned first.")

        if grade and grade.school_id != self.school.id:
            self.add_error("grade", "Select a class in this school.")

        if grade and name and grade.school_id == self.school.id:
            duplicates = Section.objects.filter(
                grade=grade,
                name__iexact=name.strip(),
            ).exclude(pk=self.instance.pk)
            if duplicates.exists():
                self.add_error(
                    "name",
                    "This section already exists in the selected class.",
                )

        if teacher and not TeacherAssignment.objects.filter(
            teacher=teacher,
            is_active=True,
            academic_year__school=self.school,
        ).exists():
            self.add_error(
                "class_teacher",
                "Select a teacher assigned to this school.",
            )

        return cleaned



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
        self.school = school
        self.fields["section"].queryset = (
            Section.objects.filter(grade__school=school).select_related("grade")
            if school else Section.objects.none()
        )

    def clean_username(self):
        username = self.cleaned_data["username"].strip()
        if User.objects.filter(username__iexact=username).exists():
            raise forms.ValidationError(
                "This username already exists. Choose another username."
            )
        return username

    def clean(self):
        cleaned = super().clean()
        school = self.school
        section = cleaned.get("section")

        if not school:
            raise forms.ValidationError("A school must be assigned first.")

        if section and section.grade.school_id != school.id:
            self.add_error("section", "Select a section in this school.")

        if not AcademicYear.objects.filter(school=school).exists():
            raise forms.ValidationError(
                "Create an academic year before enrolling students."
            )

        from course.models import Program
        if not Program.objects.exists():
            raise forms.ValidationError(
                "Create a program before creating student accounts."
            )

        return cleaned



    def save(self, school):
        from django.db import transaction
        from course.models import Program

        if not self.is_valid():
            raise ValueError("Cannot save an invalid student form.")

        section = self.cleaned_data["section"]
        year = (
            AcademicYear.objects.filter(
                school=school, is_current=True
            ).first()
            or AcademicYear.objects.filter(
                school=school
            ).order_by("-id").first()
        )
        program = Program.objects.first()

        if (
            not year
            or not program
            or section.grade.school_id != school.id
        ):
            raise ValueError(
                "A valid school, academic year, program and section are required."
            )

        username = self.cleaned_data["username"].strip()
        password = self.cleaned_data["password"]

        with transaction.atomic():
            user = User(
                username=username,
                first_name=self.cleaned_data["first_name"],
                last_name=self.cleaned_data["last_name"],
                is_student=True,
            )

            user._preserve_supplied_credentials = True
            user._supplied_password = password
            user.set_password(password)
            user.save()

            student = Student.objects.create(
                student=user,
                program=program,
            )

            Enrollment.objects.create(
                student=student,
                academic_year=year,
                section=section,
                roll_number=self.cleaned_data["roll_number"],
                admission_number=self.cleaned_data["admission_number"],
                is_active=True,
            )

        return student


class AssessmentCreateForm(forms.ModelForm):
    class Meta:
        model = Assessment
        fields = (
            "grade", "subject", "title", "assessment_type",
            "time_limit_minutes", "passing_percentage", "is_published",
        )

    def __init__(self, *args, school=None, teacher=None, **kwargs):
        super().__init__(*args, **kwargs)
        from .models import GradeSubject

        self.teacher = teacher
        self.school = school

        assignments = TeacherAssignment.objects.filter(
            teacher=teacher, is_active=True
        ) if teacher else TeacherAssignment.objects.none()

        if school:
            assignments = assignments.filter(academic_year__school=school)

        self.fields["subject"].queryset = Subject.objects.filter(
            id__in=assignments.values_list("subject_id", flat=True)
        ).distinct().order_by("name")

        grade_ids = set(
            assignments.exclude(section__isnull=True).values_list(
                "section__grade_id", flat=True
            )
        )

        for assignment in assignments.filter(section__isnull=True):
            ids = GradeSubject.objects.filter(
                subject_id=assignment.subject_id,
                grade__school_id=assignment.academic_year.school_id,
            ).values_list("grade_id", flat=True)
            grade_ids.update(ids)

        grade_queryset = Grade.objects.filter(id__in=grade_ids)
        if school:
            grade_queryset = grade_queryset.filter(school=school)

        self.fields["grade"].queryset = grade_queryset.distinct().order_by("name")

    def clean(self):
        from django.db.models import Q

        cleaned = super().clean()
        grade = cleaned.get("grade")
        subject = cleaned.get("subject")

        if not grade or not subject or not self.teacher:
            return cleaned

        if self.school and (
            grade.school_id != self.school.id
            or subject.school_id != self.school.id
        ):
            self.add_error("subject", "Choose a grade and subject from your school.")
            return cleaned

        assignments = TeacherAssignment.objects.filter(
            teacher=self.teacher,
            subject=subject,
            is_active=True,
        )

        if self.school:
            assignments = assignments.filter(academic_year__school=self.school)

        valid_pair = assignments.filter(
            Q(section__grade=grade)
            | Q(
                section__isnull=True,
                subject__grade_subjects__grade=grade,
            )
        ).exists()

        if not valid_pair:
            self.add_error(
                "subject",
                "You are not assigned to teach this subject in the selected grade.",
            )

        return cleaned


class QuestionCreateForm(forms.Form):
    concept = forms.ModelChoiceField(queryset=Concept.objects.none())
    text = forms.CharField(widget=forms.Textarea(attrs={"rows": 3}))
    difficulty = forms.ChoiceField(choices=Concept._meta.get_field("difficulty").choices)
    bloom_level = forms.ChoiceField(choices=Concept._meta.get_field("bloom_level").choices)
    marks = forms.IntegerField(min_value=1, initial=1)
    option_a = forms.CharField(max_length=500)
    option_b = forms.CharField(max_length=500)
    option_c = forms.CharField(max_length=500, required=False)
    option_d = forms.CharField(max_length=500, required=False)
    correct = forms.ChoiceField(
        choices=(("a", "A"), ("b", "B"), ("c", "C"), ("d", "D"))
    )
    explanation = forms.CharField(
        widget=forms.Textarea(attrs={"rows": 2}), required=False
    )

    def __init__(self, *args, teacher=None, **kwargs):
        super().__init__(*args, **kwargs)
        from django.db.models import Q
        from .models import GradeSubject

        allowed = Q(pk__in=[])

        assignments = TeacherAssignment.objects.filter(
            teacher=teacher, is_active=True
        ).select_related("subject", "section__grade", "academic_year")

        for assignment in assignments:
            if assignment.section_id:
                allowed |= Q(
                    chapter__grade_id=assignment.section.grade_id,
                    chapter__subject_id=assignment.subject_id,
                )
            else:
                grade_ids = GradeSubject.objects.filter(
                    subject_id=assignment.subject_id,
                    grade__school_id=assignment.academic_year.school_id,
                ).values_list("grade_id", flat=True)

                allowed |= Q(
                    chapter__grade_id__in=grade_ids,
                    chapter__subject_id=assignment.subject_id,
                )

        self.fields["concept"].queryset = Concept.objects.filter(
            allowed
        ).select_related(
            "chapter__subject", "chapter__grade"
        ).distinct().order_by(
            "chapter__grade__name", "chapter__order", "order"
        )
        self.fields["concept"].label = "Concept (Class • Subject • Chapter)"
        self.fields["concept"].label_from_instance = lambda concept: (
            f"{concept.chapter.grade.name} • "
            f"{concept.chapter.subject.name} • "
            f"{concept.chapter.title} — {concept.title}"
        )
        self.fields["concept"].label = "Concept (Class • Subject • Chapter)"
        self.fields["concept"].label_from_instance = lambda concept: (
            f"{concept.chapter.grade.name} • "
            f"{concept.chapter.subject.name} • "
            f"{concept.chapter.title} — {concept.title}"
        )

        self.fields["concept"].queryset = self.fields["concept"].queryset.exclude(title="NCERT Chapter Resources")

    def save(self):
        q = Question.objects.create(
            concept=self.cleaned_data["concept"],
            text=self.cleaned_data["text"],
            difficulty=self.cleaned_data["difficulty"],
            bloom_level=self.cleaned_data["bloom_level"],
            marks=self.cleaned_data["marks"],
            explanation=self.cleaned_data["explanation"],
        )

        for key, order in [("a", 1), ("b", 2), ("c", 3), ("d", 4)]:
            option_text = self.cleaned_data.get(f"option_{key}")
            if option_text:
                QuestionOption.objects.create(
                    question=q,
                    text=option_text,
                    order=order,
                    is_correct=self.cleaned_data["correct"] == key,
                )

        return q


class LearningResourceImportForm(forms.Form):
    concept = forms.ModelChoiceField(queryset=Concept.objects.none(), label="Concept")
    title = forms.CharField(max_length=200, required=False, help_text="Leave blank to generate a title from the URL.")
    resource_type = forms.ChoiceField(choices=LearningResource.RESOURCE_TYPES, initial="video")
    url = forms.URLField(required=False, label="Official resource URL")
    qr_image = forms.ImageField(required=False, label="QR code image")
    source_name = forms.CharField(max_length=120, required=False, initial="NCERT")
    description = forms.CharField(widget=forms.Textarea(attrs={"rows": 3}), required=False)
    duration_minutes = forms.IntegerField(min_value=0, required=False, initial=0)

    def __init__(self, *args, school=None, teacher=None, **kwargs):
        super().__init__(*args, **kwargs)
        if school and teacher and getattr(teacher, "is_lecturer", False):
            assignments = TeacherAssignment.objects.filter(
                teacher=teacher, is_active=True
            )
            self.fields["concept"].queryset = Concept.objects.filter(
                chapter__subject_id__in=assignments.values_list("subject_id", flat=True),
                chapter__grade_id__in=assignments.values_list("section__grade_id", flat=True),
            ).select_related("chapter__subject", "chapter__grade").distinct().order_by(
                "chapter__grade__order", "chapter__order", "order"
            )
        elif school:
            self.fields["concept"].queryset = Concept.objects.filter(
                chapter__subject__school=school
            ).select_related("chapter__subject", "chapter__grade").order_by(
                "chapter__grade__order", "chapter__order", "order"
            )

    def clean(self):
        cleaned = super().clean()
        if not cleaned.get("url") and not cleaned.get("qr_image"):
            raise forms.ValidationError("Provide an official URL or upload a QR code image.")
        return cleaned
