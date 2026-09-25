"""Mavjud restoranlar rollariga Telegram bot ruxsatlari (yangi restoranlarda SYSTEM_ROLES orqali)."""
from django.db import migrations

GRANTS = {"manager": ["telegram.*"], "marketer": ["telegram.view", "telegram.broadcast"]}


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
    dependencies = [("tgbot", "0001_initial"), ("core", "0001_initial")]
    operations = [migrations.RunPython(grant, migrations.RunPython.noop)]
