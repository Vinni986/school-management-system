from django.contrib import admin

from .models import (
    School, AcademicYear, Grade, Section, Enrollment, Subject, GradeSubject,
    Chapter, Concept, ConceptPrerequisite, LearningResource, Question,
    QuestionOption, Assessment, AssessmentAttempt, StudentAnswer,
    ConceptPerformance, LearningGap, LearningPath, LearningPathItem,
    RemedialRecommendation, StudentPrediction, BloomPerformance,
)


admin.site.register([
    School, AcademicYear, Grade, Section, Enrollment, Subject, GradeSubject,
    Chapter, Concept, ConceptPrerequisite, LearningResource, Question,
    QuestionOption, Assessment, AssessmentAttempt, StudentAnswer,
    ConceptPerformance, LearningGap, LearningPath, LearningPathItem,
    RemedialRecommendation, StudentPrediction, BloomPerformance,
])
