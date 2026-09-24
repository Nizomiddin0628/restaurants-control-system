"""Mavjud restoranlar rollariga o'qitish ruxsatlarini qo'shadi (yangi restoranlarda SYSTEM_ROLES orqali)."""
from django.db import migrations

GRANTS = {"manager": ["training.*"], "cashier": ["training.view"], "waiter": ["training.view"], "cook": ["training.view"],
          "courier": ["training.view"], "accountant": ["training.view"], "marketer": ["training.view"]}


def grant(apps, schema_editor):
    Role = apps.get_model("core", "Role")
    for code, perms in GRANTS.items():
        for r in Role.objects.filter(code=code):
            cur = list(r.permissions or [])
            add = [p for p in perms if p not in cur]
            if add:
                r.permissions = cur + add
                r.save(update_fields=["permissions"])


class Migration(migrations.Migration):
    dependencies = [("training", "0001_initial"), ("core", "0001_initial")]
    operations = [migrations.RunPython(grant, migrations.RunPython.noop)]
