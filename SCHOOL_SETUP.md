# SkyLearn School setup

From the project root:

```bash
python manage.py makemigrations school
python manage.py migrate
python manage.py seed_school_demo
python manage.py runserver
```

Then open `/school/` after logging in.

The demo command creates a small Class 4-B curriculum, subjects, chapters, concepts, resources, questions and published baseline assessments. If a student account does not exist, it creates `student4` with password `Student@123`.

For production, replace the demo data with your school's real classes, subjects, curriculum, questions and resources through Django Admin or dedicated school-admin screens.
