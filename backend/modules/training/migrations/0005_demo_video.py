"""Demo kursdagi «Qo'lni to'g'ri yuvish» darsiga haqiqiy video (JSST, YouTube) — video nazoratini sinab ko'rish uchun.
Faqat demo nomi bilan va videosi bo'sh bo'lsa o'zgartiradi; o'zingiz yaratgan darslarga tegmaydi."""
from django.db import migrations

URL = "https://www.youtube.com/watch?v=3PmVJQUCm4E"


def add(apps, schema_editor):
    Lesson = apps.get_model("training", "Lesson")
    Lesson.objects.filter(title="Qo'lni to'g'ri yuvish", video_url="", video="").update(video_url=URL)


class Migration(migrations.Migration):
    dependencies = [("training", "0004_reminders")]
    operations = [migrations.RunPython(add, migrations.RunPython.noop)]
