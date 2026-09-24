"""Telefon raqamlarini bir xil ko'rinishga keltiradi (+998...). Ilgari demo xodimlar '+'siz yozilgan va kira olmasdi."""
from django.db import migrations


def normalize(apps, schema_editor):
    User = apps.get_model("core", "User")
    taken = set(User.objects.values_list("phone", flat=True))
    for u in User.objects.exclude(phone__startswith="+"):
        digits = "".join(ch for ch in u.phone if ch.isdigit())
        if len(digits) == 9:
            digits = "998" + digits
        new = "+" + digits
        if new in taken:
            continue
        taken.add(new)
        u.phone = new
        u.save(update_fields=["phone"])


class Migration(migrations.Migration):
    dependencies = [("core", "0001_initial")]
    operations = [migrations.RunPython(normalize, migrations.RunPython.noop)]
