# School Management & AI Learning Platform

A Django-based School Management and AI-Powered Learning Platform designed for **Students, Teachers, and Principals**.

The platform combines school administration, assessments, student performance analysis, personalized learning, remedial learning, teacher management, and principal-level analytics in one system.

---

## 🚀 Key Features

### 👨‍🎓 Student Dashboard

Students can:

- View their learning dashboard
- View enrolled subjects
- View chapters and concepts
- Take assessments
- Submit answers
- View assessment results
- Track scores and accuracy
- Identify learning gaps
- View personalized learning recommendations
- Access remedial resources
- View learning progress
- View performance reports
- Access learning resources

### 🤖 AI-Based Learning Analysis

The platform supports:

- Baseline assessment
- Concept-level performance analysis
- Learning gap identification
- Learning loss analysis
- Personalized learning paths
- Remedial recommendations
- Student readiness analysis
- Predicted performance
- Bloom's Taxonomy performance tracking
- Concept mastery tracking
- Difficulty analysis
- Accuracy analysis

### 👨‍🏫 Teacher Dashboard

Teachers can:

- View assigned classes
- View assigned subjects
- View students
- Create questions
- Create assessments
- Assign assessments
- View student performance
- View student learning gaps
- Assign remedial resources
- Monitor student progress

### 👨‍💼 Principal Dashboard

Principals can:

- View school overview
- View teachers
- View students
- Create teachers
- Create students
- Create grades/classes
- Create sections
- Manage school structure
- View individual student performance
- Monitor academic performance
- View learning analytics

---

# 🔄 Learning Workflow

The core learning workflow is:

```text
Student
   ↓
Baseline Assessment
   ↓
Student Answers
   ↓
Concept Performance Analysis
   ↓
Learning Gap Detection
   ↓
Learning Loss Analysis
   ↓
Readiness / Prediction
   ↓
Personalized Learning Path
   ↓
Remedial Learning
   ↓
Practice / Quiz
   ↓
Mastery Update
   ↓
Student Dashboard
👥 User Roles

The system currently supports three main school roles:

Role	Main Access
Student	Learning, assessments, results, gaps, resources
Teacher	Classes, students, questions, assessments, remedial learning
Principal	School management, teachers, students, classes, analytics
🔐 Demo Login Credentials

Use these accounts to test the different dashboards.

Principal
Username: principal1
Password: Principal@123

Access:

/en/school/principal/
Teacher
Username: teacher1
Password: Teacher@123

Access:

/en/school/teacher/
Student
Username: student4
Password: Student@123

Access:

/en/school/
🌐 Important URLs

After starting the Django server:

http://127.0.0.1:8000/en/
Student
/en/school/
/en/school/learning/
/en/school/assessments/
/en/school/gaps/
/en/school/reports/
/en/school/resources/
Principal
/en/school/principal/
Teacher
/en/school/teacher/
Django Admin
/admin/
🛠️ Technology Stack
Backend
Python
Django
Django ORM
SQLite (development)
Frontend
HTML
CSS
JavaScript
Django Templates
Responsive UI
Existing Project Components

The project is based on a Django LMS structure and includes:

Accounts
Courses
Quiz
Results
Search
Payments
School Management
AI Learning Analytics
📁 Project Structure
school-management-system/
│
├── accounts/
│   ├── models.py
│   ├── views.py
│   ├── forms.py
│   └── urls.py
│
├── school/
│   ├── models.py
│   ├── views.py
│   ├── staff_views.py
│   ├── forms.py
│   ├── urls.py
│   └── management/
│       └── commands/
│           └── seed_school_demo.py
│
├── core/
│   ├── views.py
│   └── urls.py
│
├── course/
├── quiz/
├── result/
├── search/
├── payments/
│
├── templates/
│   └── school/
│       ├── dashboard.html
│       ├── learning.html
│       ├── assessment.html
│       ├── take_assessment.html
│       ├── assessment_result.html
│       ├── gaps.html
│       ├── reports.html
│       ├── resources.html
│       ├── principal_dashboard.html
│       ├── principal_manage.html
│       ├── teacher_dashboard.html
│       ├── teacher_create_assessment.html
│       ├── teacher_create_question.html
│       └── student_detail_staff.html
│
├── static/
│   ├── css/
│   │   └── school.css
│   └── js/
│       └── school.js
│
├── config/
│   ├── settings.py
│   ├── urls.py
│   └── wsgi.py
│
├── manage.py
├── requirements.txt
└── README.md
🗄️ Main School Data Models

The School module contains models for:

School
AcademicYear
Grade
Section
Enrollment

Subject
TeacherAssignment
GradeSubject

Chapter
Concept
ConceptPrerequisite

LearningResource

Question
QuestionOption
Assessment
AssessmentAttempt
StudentAnswer

ConceptPerformance
LearningGap

LearningPath
LearningPathItem
RemedialRecommendation

StudentPrediction
BloomPerformance

These models provide the foundation for school management, assessments, concept-level analytics, and personalized learning.

📊 Student Performance System

Student performance is analyzed at the concept level.

The system records:

Assessment attempts
Student answers
Correct/incorrect responses
Scores
Accuracy
Concept performance
Learning gaps
Learning recommendations
Bloom's Taxonomy performance
Predicted performance

A concept can be considered mastered when the student's performance reaches the configured mastery threshold.

The current implementation uses:

80% mastery threshold
🧠 Learning Gap Detection

After an assessment is submitted:

Assessment
    ↓
Student Answers
    ↓
Concept Performance
    ↓
Performance Calculation
    ↓
Learning Gap

Concepts where the student performs below the configured mastery threshold can be added to the student's learning gaps.

These gaps can then be used for:

Remedial learning
Personalized recommendations
Learning paths
Teacher intervention
Student progress tracking
📚 Personalized Learning

The platform supports personalized learning through:

Student performance
Concept mastery
Learning gaps
Remedial recommendations
Learning resources
Learning paths

The intended flow is:

Identify Weak Concept
        ↓
Recommend Resource
        ↓
Student Learns
        ↓
Practice
        ↓
Assessment
        ↓
Recalculate Mastery
📝 Assessments

Teachers can create assessments containing questions.

Students can:

Open an assessment
Answer questions
Submit the assessment
Receive a score
View performance
Identify weak concepts

Assessment results are stored for future performance analysis.

👨‍🏫 Teacher Management

Teachers can be assigned to:

Academic Year
     ↓
Grade
     ↓
Section
     ↓
Subject

This allows the platform to associate teachers with specific classes and subjects.

Teachers can then manage assessments and monitor students assigned to their classes.

🏫 Principal Management

The Principal dashboard provides school-level management.

The Principal can create/manage:

Teachers
Students
Grades
Sections
School structure

The Principal can also open individual student profiles to inspect academic performance and learning information.

🌱 Demo Data

The project includes a Django management command that creates demo school data.

Run:

python manage.py seed_school_demo

The seed command creates demo data including:

School
Academic year
Grade
Section
Subjects
Chapters
Concepts
Learning resources
Questions
Assessments
Teacher assignment
Principal account
Teacher account
Student account
💻 Installation
1. Clone the Repository
git clone <YOUR_GITHUB_REPOSITORY_URL>
cd school-management-system
2. Create Virtual Environment
Linux / macOS
python3 -m venv venv
source venv/bin/activate
Windows
python -m venv venv
venv\Scripts\activate
3. Install Dependencies
pip install -r requirements.txt
4. Run Migrations
python manage.py makemigrations
python manage.py migrate
5. Create Demo School Data
python manage.py seed_school_demo
6. Create Admin User
python manage.py createsuperuser

Follow the terminal instructions.

7. Start Development Server
python manage.py runserver

Open:

http://127.0.0.1:8000/en/
🔑 Login Flow

The root URL is role-aware.

After login:

Student
   → Student Dashboard

Teacher
   → Teacher Dashboard

Principal
   → Principal Dashboard

The system checks the authenticated user's role and redirects them to the appropriate dashboard.

⚙️ Environment Configuration

For local development, Django can use the default configuration.

If environment variables are required, create a .env file.

Example:

DEBUG=True
SECRET_KEY=your-secret-key

EMAIL_BACKEND=django.core.mail.backends.console.EmailBackend
EMAIL_HOST_USER=
EMAIL_HOST_PASSWORD=
EMAIL_FROM_ADDRESS=

Do not commit sensitive credentials or production secrets to GitHub.

🧪 Development Checks

Run Django system checks with:

python manage.py check

Run migrations with:

python manage.py makemigrations
python manage.py migrate

Run the development server:

python manage.py runserver
🐛 Troubleshooting
Error: No such table

Example:

OperationalError: no such table: school_school

Run:

python manage.py makemigrations
python manage.py migrate

Then seed the demo data again:

python manage.py seed_school_demo
Error: no such column

Example:

OperationalError: no such column: accounts_user.is_principal

Run:

python manage.py makemigrations accounts
python manage.py migrate accounts
python manage.py migrate
Demo Login Not Working

Reset the demo user's password from Django shell:

python manage.py shell

Then:

from accounts.models import User

u = User.objects.get(username="student4")
u.set_password("Student@123")
u.is_student = True
u.save()

For the teacher:

u = User.objects.get(username="teacher1")
u.set_password("Teacher@123")
u.is_lecturer = True
u.save()

For the principal:

u = User.objects.get(username="principal1")
u.set_password("Principal@123")
u.is_principal = True
u.save()
🔒 Production Considerations

This project is currently structured primarily for development and demonstration.

Before production deployment:

Change all demo passwords
Configure a production SECRET_KEY
Set DEBUG=False
Configure ALLOWED_HOSTS
Use PostgreSQL or another production database
Configure production email
Configure HTTPS
Configure secure cookies
Review authentication and authorization
Add CSRF/security headers
Remove or replace demo data
Configure static/media storage
Add proper backups
Add logging and monitoring
🎯 Project Objective

The objective of this platform is to provide a unified digital learning and school-management environment where:

School Administration
        +
Teacher Management
        +
Student Management
        +
Assessments
        +
Concept-Level Analytics
        +
Learning Gap Detection
        +
Personalized Learning
        +
Remedial Learning
        +
Performance Reporting

are connected into a single platform.

🔮 Future Enhancements

Potential future improvements include:

Parent dashboard
Attendance management
Timetable management
Fee management
School notifications
Advanced AI tutoring
AI-generated questions
AI-generated assessments
Automatic lesson recommendations
Advanced predictive analytics
Student risk detection
Advanced Bloom's Taxonomy analytics
PDF report generation
Excel/CSV exports
Interactive charts
Mobile application
REST API
PostgreSQL production deployment
Cloud deployment
Multi-school SaaS architecture
📌 Demo Summary

Use the following accounts to explore the three major dashboards:

Dashboard	Username	Password
Principal	principal1	Principal@123
Teacher	teacher1	Teacher@123
Student	student4	Student@123

Start the project with:

python manage.py runserver

Then visit:

http://127.0.0.1:8000/en/
