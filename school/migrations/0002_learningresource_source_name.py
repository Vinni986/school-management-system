from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("school", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="learningresource",
            name="source_name",
            field=models.CharField(blank=True, default="", max_length=120),
        ),
    ]
