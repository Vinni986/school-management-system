from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from django.db import transaction
from accounts.models import Student
from course.models import Program
from school.models import *

User = get_user_model()

class Command(BaseCommand):
    help = 'Create/update a complete demo school environment.'

    @transaction.atomic
    def handle(self, *args, **kwargs):
        program = Program.objects.first()
        school, _ = School.objects.get_or_create(code='DEMO-SCHOOL', defaults={'name':'SkyLearn Demo School','address':'Demo campus'})
        principal, _ = User.objects.get_or_create(username='principal1', defaults={'first_name':'Aarav','last_name':'Sharma','is_principal':True})
        principal.set_password('Principal@123'); principal.is_principal=True; principal.is_active=True; principal.save()
        school.principal = principal; school.save(update_fields=['principal'])
        year, _ = AcademicYear.objects.get_or_create(school=school, name='2026-27', defaults={'is_current':True})
        AcademicYear.objects.filter(school=school).exclude(pk=year.pk).update(is_current=False)
        year.is_current=True; year.save(update_fields=['is_current'])
        grade, _ = Grade.objects.get_or_create(school=school, name='Class 4', defaults={'order':4})
        section, _ = Section.objects.get_or_create(grade=grade, name='B')
        subjects = []
        for name in ['Mathematics','Science','English']:
            s,_=Subject.objects.get_or_create(school=school,name=name,defaults={'code':name[:3].upper()}); subjects.append(s)
        teacher, _ = User.objects.get_or_create(username='teacher1', defaults={'first_name':'Priya','last_name':'Verma','is_lecturer':False})
        teacher.set_password('Teacher@123'); teacher.is_lecturer=True; teacher.save()
        for s in subjects:
            TeacherAssignment.objects.get_or_create(teacher=teacher,subject=s,section=section,academic_year=year,is_active=True)
            GradeSubject.objects.get_or_create(grade=grade,subject=s)
            ch,_=Chapter.objects.get_or_create(grade=grade,subject=s,title=f'{s.name} Foundations',defaults={'order':1})
            concept,_=Concept.objects.get_or_create(chapter=ch,title=f'{s.name} Basics',defaults={'difficulty':'easy','bloom_level':'understand'})
            LearningResource.objects.get_or_create(concept=concept,title=f'{concept.title} Study Guide',resource_type='article',description='Teacher-curated introductory resource.')
        student_user, _ = User.objects.get_or_create(username='student4', defaults={'first_name':'Demo','last_name':'Student','is_student':False})
        student_user.set_password('Student@123'); student_user.is_student=True; student_user.save()
        if program:
            student,_=Student.objects.get_or_create(student=student_user,defaults={'program':program})
            if student.program_id != program.id: student.program=program; student.save(update_fields=['program'])
            Enrollment.objects.get_or_create(student=student,academic_year=year,defaults={'section':section,'roll_number':'4','admission_number':'DEMO-004'})
            for s in subjects:
                ch=Chapter.objects.filter(grade=grade,subject=s).first(); concept=ch.concepts.first()
                if concept:
                    q=Question.objects.filter(concept=concept).first()
                    if not q:
                        q=Question.objects.create(concept=concept,text=f'Which statement best describes {concept.title}?',difficulty='easy',bloom_level='remember',marks=1)
                        QuestionOption.objects.create(question=q,text='It is a core learning concept.',is_correct=True,order=1)
                        QuestionOption.objects.create(question=q,text='It is unrelated to the subject.',is_correct=False,order=2)
                        QuestionOption.objects.create(question=q,text='It is only for teachers.',is_correct=False,order=3)
                    assessment,_=Assessment.objects.get_or_create(grade=grade,subject=s,title=f'{s.name} Baseline Assessment',defaults={'assessment_type':'baseline','is_published':True,'passing_percentage':40})
                    assessment.questions.add(q); assessment.is_published=True; assessment.save(update_fields=['is_published'])
        self.stdout.write(self.style.SUCCESS('Demo school data is ready.'))
        self.stdout.write('Student: student4 / Student@123')
        self.stdout.write('Teacher: teacher1 / Teacher@123')
        self.stdout.write('Principal: principal1 / Principal@123')
