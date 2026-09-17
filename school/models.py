from django.conf import settings
from django.db import models
from django.utils.text import slugify

from accounts.models import Student


class School(models.Model):
    name = models.CharField(max_length=200)
    code = models.CharField(max_length=50, unique=True)
    address = models.TextField(blank=True)
    principal = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="schools_led",
    )
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.name


class AcademicYear(models.Model):
    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name="academic_years")
    name = models.CharField(max_length=50)  # e.g. 2026-27
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    is_current = models.BooleanField(default=False)

    class Meta:
        unique_together = ("school", "name")

    def __str__(self):
        return "%s - %s" % (self.school.name, self.name)


class Grade(models.Model):
    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name="grades")
    name = models.CharField(max_length=50)  # Class 4
    order = models.PositiveIntegerField(default=1)

    class Meta:
        unique_together = ("school", "name")
        ordering = ("order", "name")

    def __str__(self):
        return self.name


class Section(models.Model):
    grade = models.ForeignKey(Grade, on_delete=models.CASCADE, related_name="sections")
    name = models.CharField(max_length=20)  # A, B, C
    class_teacher = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="class_sections",
    )

    class Meta:
        unique_together = ("grade", "name")

    def __str__(self):
        return "%s-%s" % (self.grade.name, self.name)


class Enrollment(models.Model):
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name="school_enrollments")
    academic_year = models.ForeignKey(AcademicYear, on_delete=models.CASCADE, related_name="enrollments")
    section = models.ForeignKey(Section, on_delete=models.CASCADE, related_name="enrollments")
    roll_number = models.CharField(max_length=30, blank=True)
    admission_number = models.CharField(max_length=50, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        unique_together = ("student", "academic_year")

    def __str__(self):
        return "%s - %s" % (self.student, self.section)


class Subject(models.Model):
    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name="subjects")
    name = models.CharField(max_length=150)
    code = models.CharField(max_length=50, blank=True)
    description = models.TextField(blank=True)
    icon = models.CharField(max_length=100, blank=True)
    color = models.CharField(max_length=20, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        unique_together = ("school", "name")

    def __str__(self):
        return self.name


class TeacherAssignment(models.Model):
    """Maps a teacher to a school grade/section/subject."""
    teacher = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="school_teacher_assignments")
    subject = models.ForeignKey(Subject, on_delete=models.CASCADE, related_name="teacher_assignments")
    section = models.ForeignKey(Section, on_delete=models.CASCADE, related_name="teacher_assignments", null=True, blank=True)
    academic_year = models.ForeignKey(AcademicYear, on_delete=models.CASCADE, related_name="teacher_assignments")
    is_active = models.BooleanField(default=True)

    class Meta:
        unique_together = ("teacher", "subject", "section", "academic_year")

    def __str__(self):
        section = self.section or "All sections"
        return "%s - %s - %s" % (self.teacher.get_full_name, self.subject.name, section)


class GradeSubject(models.Model):
    grade = models.ForeignKey(Grade, on_delete=models.CASCADE, related_name="grade_subjects")
    subject = models.ForeignKey(Subject, on_delete=models.CASCADE, related_name="grade_subjects")
    is_core = models.BooleanField(default=True)

    class Meta:
        unique_together = ("grade", "subject")


class Chapter(models.Model):
    subject = models.ForeignKey(Subject, on_delete=models.CASCADE, related_name="chapters")
    grade = models.ForeignKey(Grade, on_delete=models.CASCADE, related_name="chapters")
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    order = models.PositiveIntegerField(default=1)
    estimated_minutes = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ("order", "id")
        unique_together = ("grade", "subject", "title")

    def __str__(self):
        return self.title


class Concept(models.Model):
    chapter = models.ForeignKey(Chapter, on_delete=models.CASCADE, related_name="concepts")
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    order = models.PositiveIntegerField(default=1)
    difficulty = models.CharField(
        max_length=20,
        choices=(("easy", "Easy"), ("medium", "Medium"), ("hard", "Hard")),
        default="medium",
    )
    bloom_level = models.CharField(
        max_length=30,
        choices=(
            ("remember", "Remember"),
            ("understand", "Understand"),
            ("apply", "Apply"),
            ("analyze", "Analyze"),
            ("evaluate", "Evaluate"),
            ("create", "Create"),
        ),
        default="understand",
    )

    class Meta:
        ordering = ("order", "id")
        unique_together = ("chapter", "title")

    def __str__(self):
        return self.title


class ConceptPrerequisite(models.Model):
    concept = models.ForeignKey(Concept, on_delete=models.CASCADE, related_name="prerequisites")
    prerequisite = models.ForeignKey(Concept, on_delete=models.CASCADE, related_name="required_for")
    strength = models.FloatField(default=1.0)

    class Meta:
        unique_together = ("concept", "prerequisite")


class LearningResource(models.Model):
    RESOURCE_TYPES = (
        ("video", "Video"),
        ("pdf", "PDF"),
        ("article", "Article"),
        ("interactive", "Interactive"),
        ("practice", "Practice"),
    )
    concept = models.ForeignKey(Concept, on_delete=models.CASCADE, related_name="resources")
    title = models.CharField(max_length=200)
    resource_type = models.CharField(max_length=20, choices=RESOURCE_TYPES)
    url = models.URLField(blank=True)
    file = models.FileField(upload_to="school/resources/", blank=True, null=True)
    description = models.TextField(blank=True)
    duration_minutes = models.PositiveIntegerField(default=0)
    order = models.PositiveIntegerField(default=1)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.title


class Question(models.Model):
    QUESTION_TYPES = (
        ("mcq", "MCQ"),
        ("true_false", "True/False"),
        ("short", "Short Answer"),
        ("long", "Long Answer"),
    )
    concept = models.ForeignKey(Concept, on_delete=models.CASCADE, related_name="questions")
    text = models.TextField()
    question_type = models.CharField(max_length=20, choices=QUESTION_TYPES, default="mcq")
    difficulty = models.CharField(max_length=20, choices=Concept._meta.get_field("difficulty").choices, default="medium")
    bloom_level = models.CharField(max_length=30, choices=Concept._meta.get_field("bloom_level").choices, default="understand")
    marks = models.PositiveIntegerField(default=1)
    explanation = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.text[:80]


class QuestionOption(models.Model):
    question = models.ForeignKey(Question, on_delete=models.CASCADE, related_name="options")
    text = models.CharField(max_length=500)
    is_correct = models.BooleanField(default=False)
    order = models.PositiveIntegerField(default=1)

    class Meta:
        ordering = ("order", "id")


class Assessment(models.Model):
    TYPES = (
        ("baseline", "Baseline"),
        ("quiz", "Quiz"),
        ("exam", "Exam"),
        ("practice", "Practice"),
    )
    grade = models.ForeignKey(Grade, on_delete=models.CASCADE, related_name="assessments")
    subject = models.ForeignKey(Subject, on_delete=models.CASCADE, related_name="assessments")
    title = models.CharField(max_length=200)
    assessment_type = models.CharField(max_length=20, choices=TYPES)
    questions = models.ManyToManyField(Question, related_name="assessments", blank=True)
    time_limit_minutes = models.PositiveIntegerField(default=0)
    passing_percentage = models.FloatField(default=40)
    is_published = models.BooleanField(default=False)

    def __str__(self):
        return self.title


class AssessmentAttempt(models.Model):
    assessment = models.ForeignKey(Assessment, on_delete=models.CASCADE, related_name="attempts")
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name="assessment_attempts")
    started_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    score = models.FloatField(default=0)
    percentage = models.FloatField(default=0)
    is_completed = models.BooleanField(default=False)

    def __str__(self):
        return "%s - %s" % (self.student, self.assessment)


class StudentAnswer(models.Model):
    attempt = models.ForeignKey(AssessmentAttempt, on_delete=models.CASCADE, related_name="answers")
    question = models.ForeignKey(Question, on_delete=models.CASCADE, related_name="student_answers")
    selected_option = models.ForeignKey(QuestionOption, on_delete=models.SET_NULL, null=True, blank=True)
    answer_text = models.TextField(blank=True)
    is_correct = models.BooleanField(default=False)
    marks_awarded = models.FloatField(default=0)
    answered_at = models.DateTimeField(auto_now_add=True)


class ConceptPerformance(models.Model):
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name="concept_performances")
    concept = models.ForeignKey(Concept, on_delete=models.CASCADE, related_name="student_performances")
    attempts = models.PositiveIntegerField(default=0)
    correct_answers = models.PositiveIntegerField(default=0)
    total_answers = models.PositiveIntegerField(default=0)
    mastery_score = models.FloatField(default=0)
    confidence_score = models.FloatField(default=0)
    last_assessed_at = models.DateTimeField(null=True, blank=True)
    is_mastered = models.BooleanField(default=False)

    class Meta:
        unique_together = ("student", "concept")


class LearningGap(models.Model):
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name="learning_gaps")
    concept = models.ForeignKey(Concept, on_delete=models.CASCADE, related_name="learning_gaps")
    gap_score = models.FloatField(default=0)
    reason = models.TextField(blank=True)
    priority = models.PositiveIntegerField(default=1)
    status = models.CharField(
        max_length=20,
        choices=(("open", "Open"), ("in_progress", "In Progress"), ("cleared", "Cleared")),
        default="open",
    )
    detected_at = models.DateTimeField(auto_now_add=True)
    cleared_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = ("student", "concept")
        ordering = ("priority", "-gap_score")


class LearningPath(models.Model):
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name="learning_paths")
    subject = models.ForeignKey(Subject, on_delete=models.CASCADE, related_name="learning_paths")
    title = models.CharField(max_length=200)
    generated_at = models.DateTimeField(auto_now_add=True)
    is_active = models.BooleanField(default=True)
    progress_percentage = models.FloatField(default=0)

    def __str__(self):
        return self.title


class LearningPathItem(models.Model):
    learning_path = models.ForeignKey(LearningPath, on_delete=models.CASCADE, related_name="items")
    concept = models.ForeignKey(Concept, on_delete=models.CASCADE, related_name="learning_path_items")
    resource = models.ForeignKey(LearningResource, on_delete=models.SET_NULL, null=True, blank=True)
    order = models.PositiveIntegerField(default=1)
    reason = models.TextField(blank=True)
    status = models.CharField(
        max_length=20,
        choices=(("locked", "Locked"), ("pending", "Pending"), ("in_progress", "In Progress"), ("completed", "Completed")),
        default="pending",
    )
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("order", "id")


class RemedialRecommendation(models.Model):
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name="remedial_recommendations")
    concept = models.ForeignKey(Concept, on_delete=models.CASCADE, related_name="remedial_recommendations")
    resource = models.ForeignKey(LearningResource, on_delete=models.CASCADE)
    reason = models.TextField(blank=True)
    priority = models.PositiveIntegerField(default=1)
    is_completed = models.BooleanField(default=False)


class StudentPrediction(models.Model):
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name="predictions")
    subject = models.ForeignKey(Subject, on_delete=models.CASCADE, related_name="predictions")
    predicted_score = models.FloatField(default=0)
    readiness_score = models.FloatField(default=0)
    learning_loss_percentage = models.FloatField(default=0)
    calculated_at = models.DateTimeField(auto_now_add=True)


class BloomPerformance(models.Model):
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name="bloom_performances")
    subject = models.ForeignKey(Subject, on_delete=models.CASCADE, related_name="bloom_performances")
    bloom_level = models.CharField(max_length=30)
    accuracy = models.FloatField(default=0)
    total_questions = models.PositiveIntegerField(default=0)
    correct_questions = models.PositiveIntegerField(default=0)

    class Meta:
        unique_together = ("student", "subject", "bloom_level")
