from django.urls import path
from .staff_views import (principal_dashboard, teacher_dashboard, principal_manage, principal_student_detail, teacher_create_assessment, teacher_create_question, teacher_student_detail, teacher_assign_remedial)
from .views import (
    assessment_result, assessment_view, gaps_view, learning_view, reports_view,
    resource_open, resources_view, start_assessment, student_dashboard, take_assessment,
)

urlpatterns = [
    path("principal/", principal_dashboard, name="school_principal_dashboard"),
    path("principal/manage/", principal_manage, name="school_principal_manage"),
    path("principal/students/<int:pk>/", principal_student_detail, name="school_principal_student_detail"),
    path("teacher/", teacher_dashboard, name="school_teacher_dashboard"),
    path("teacher/assessments/new/", teacher_create_assessment, name="school_teacher_create_assessment"),
    path("teacher/questions/new/", teacher_create_question, name="school_teacher_create_question"),
    path("teacher/students/<int:pk>/", teacher_student_detail, name="school_teacher_student_detail"),
    path("teacher/gaps/<int:gap_id>/remedial/", teacher_assign_remedial, name="school_teacher_assign_remedial"),
    path("", student_dashboard, name="school_dashboard"),
    path("learning/", learning_view, name="school_learning"),
    path("assessment/", assessment_view, name="school_assessment"),
    path("assessment/<int:pk>/start/", start_assessment, name="school_start_assessment"),
    path("assessment/attempt/<int:pk>/", take_assessment, name="school_take_assessment"),
    path("assessment/attempt/<int:pk>/result/", assessment_result, name="school_assessment_result"),
    path("gaps/", gaps_view, name="school_gaps"),
    path("reports/", reports_view, name="school_reports"),
    path("resources/", resources_view, name="school_resources"),
    path("resources/<int:pk>/open/", resource_open, name="school_resource_open"),
]
