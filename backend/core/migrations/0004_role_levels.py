"""v33: rollar ierarxiyasi (Superadmin 100 · Bosh menejer 80 · Filial menejeri 60 · xodim 10).

- mavjud tizim rollariga daraja va tavsif;
- «Bosh menejer» (general_manager) roli — hamma narsani ko'radi;
- filial menejeriga: xodimlarga kirish berish (o'z filiali) va boshqaruv paneli;
- AI Kotib ruxsati rollardan olinib, o'sha odamlarga shaxsiy ruxsat sifatida o'tkaziladi (keyin Superadmin o'zi taqsimlaydi).
"""
from django.db import migrations

LEVELS = {"owner": 100, "platform_support": 1000, "general_manager": 80, "manager": 60}
DESC = {
    "owner": "Restoran egasi — hamma narsa, barcha filiallar",
    "general_manager": "Barcha filiallar va bo'limlarni ko'radi va boshqaradi",
    "manager": "O'z filialining admini: xodimlar, smena, savdo, ombor",
    "platform_support": "Platforma jamoasi (vaqtinchalik kirish)",
}
MANAGER_ADD = ["core.users.manage", "core.dashboard.view"]
DASH_ROLES = ("accountant",)


def forward(apps, schema_editor):
    Role = apps.get_model("core", "Role")
    Membership = apps.get_model("core", "Membership")
    User = apps.get_model("core", "User")
    if not Role.objects.exists():
        return                                   # public sxema yoki bo'sh restoran
    for r in Role.objects.all():
        r.level = LEVELS.get(r.code, r.level or 10)
        if not r.description and r.code in DESC:
            r.description = DESC[r.code]
        if r.code == "owner" and r.name in ("Egasi", "Owner"):
            r.name = "Superadmin (egasi)"
        if r.code == "manager":
            if r.name == "Filial menejeri":
                r.name = "Filial menejeri (admin)"
            r.permissions = [*r.permissions, *[p for p in MANAGER_ADD if p not in r.permissions]]
        if r.code in DASH_ROLES and "core.dashboard.view" not in r.permissions and "*" not in r.permissions:
            r.permissions = [*r.permissions, "core.dashboard.view"]
        if "ai.use" in (r.permissions or []) and r.code not in ("owner", "general_manager", "platform_support"):
            # AI Kotib endi shaxsan beriladi: shu roldagi odamlarga shaxsiy ruxsat
            for m in Membership.objects.filter(role=r, is_active=True):
                u = User.objects.get(pk=m.user_id)
                if "ai.use" not in (u.extra_permissions or []):
                    u.extra_permissions = [*(u.extra_permissions or []), "ai.use"]
                    u.save(update_fields=["extra_permissions"])
            r.permissions = [p for p in r.permissions if p != "ai.use"]
        r.save()
    Role.objects.get_or_create(code="general_manager", defaults={
        "name": "Bosh menejer", "permissions": ["*"], "is_system": True, "level": 80, "description": DESC["general_manager"]})


class Migration(migrations.Migration):
    dependencies = [("core", "0003_access_v33")]
    operations = [migrations.RunPython(forward, migrations.RunPython.noop)]
