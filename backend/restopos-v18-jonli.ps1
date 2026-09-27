# RestoPOS v18 — Jonli demo va bo'lim panellari
# Ishga tushirish (ildiz papkada!): PS C:\Users\xalil\Desktop\restaurants\restopos>
#   powershell -ExecutionPolicy Bypass -File .\restopos-v18-jonli.ps1
$ErrorActionPreference = 'Stop'
if (-not (Test-Path "$PWD\backend\manage.py") -or -not (Test-Path "$PWD\frontend\apps\admin")) {
  Write-Host "XATO: skriptni restopos ildiz papkasida ishga tushiring (PS C:\Users\xalil\Desktop\restaurants\restopos>)." -ForegroundColor Red
  exit 1
}
if (-not (Test-Path "$PWD\frontend\apps\admin\src\nav\sections.ts")) {
  Write-Host "XATO: avval v17 (Menyu tartibi) skriptini ishga tushiring." -ForegroundColor Red
  exit 1
}
$enc = New-Object Text.UTF8Encoding $false
function Put([string]$rel, [string]$text) {
  $path = Join-Path $PWD $rel
  $dir = Split-Path $path -Parent
  if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }
  [IO.File]::WriteAllText($path, $text.Replace("`r`n", "`n") + "`n", $enc)
  Write-Host ("  + " + $rel)
}

Put 'backend\api\api.py' @'
"""
Tenant API — /api/v1/ (restoran domenida). Yadro: auth, men, modullar, filiallar, rollar, foydalanuvchilar,
audit, dashboard. Modullar o'z routerlarini qo'shadi (catalog, cms, ...).
"""
from __future__ import annotations

from typing import Optional

from django.conf import settings
from django.shortcuts import get_object_or_404
from django.utils import timezone
from ninja import File, NinjaAPI, Schema
from ninja.errors import HttpError
from ninja.files import UploadedFile

from core import avatars
from core import modules as modreg
from core.audit import record
from core.auth import auth, issue_token, require_perm
from core.models import AuditLog, Branch, Membership, OtpCode, Role, User
from integrations.sms import send_otp
from public.services import set_modules

api = NinjaAPI(title="RestoPOS API", version="1.0", urls_namespace="tenant_api")


# ------------------------------------------------------------------ auth (telefon + OTP)
class OtpRequest(Schema):
    phone: str


class OtpVerify(Schema):
    phone: str
    code: str


class TokenOut(Schema):
    token: str
    user: dict


@api.post("/auth/otp", tags=["auth"])
def request_otp(request, data: OtpRequest):
    phone = User.objects.normalize_phone(data.phone)
    if not User.objects.filter(phone=phone, is_active=True).exists():
        raise HttpError(404, "Bu raqam ushbu restoranda ro'yxatdan o'tmagan")
    otp = OtpCode.issue(phone)
    send_otp(phone, otp.code)
    out = {"ok": True, "ttl": settings.OTP_TTL_SECONDS}
    if settings.OTP_DEV_ECHO:
        out["dev_code"] = otp.code   # faqat dev: SMS shart emas
    return out


@api.post("/auth/verify", response=TokenOut, tags=["auth"])
def verify_otp(request, data: OtpVerify):
    phone = User.objects.normalize_phone(data.phone)
    otp = OtpCode.objects.filter(phone=phone, used_at__isnull=True).order_by("-created_at").first()
    if not otp or not otp.is_valid(settings.OTP_TTL_SECONDS):
        raise HttpError(400, "Kod muddati tugagan, qaytadan so'rang")
    if otp.code != data.code:
        otp.attempts += 1
        otp.save(update_fields=["attempts"])
        raise HttpError(400, "Kod noto'g'ri")
    otp.used_at = timezone.now()
    otp.save(update_fields=["used_at"])
    user = User.objects.get(phone=phone)
    user.last_seen_at = timezone.now()
    user.save(update_fields=["last_seen_at"])
    return {"token": issue_token(user, request.tenant.schema_name), "user": _me(request, user)}


def _me(request, user: User) -> dict:
    tenant = request.tenant
    perms = sorted(user.tenant_permissions()) if not user.is_superuser else ["*"]
    return {
        "id": str(user.pk), "phone": user.phone, "full_name": user.full_name, "language": user.language,
        "avatar": user.avatar.url if user.avatar else None,
        "roles": [m.role.code for m in user.memberships.filter(is_active=True).select_related("role")],
        "role_names": [m.role.name for m in user.memberships.filter(is_active=True).select_related("role")],
        "permissions": perms,
        "tenant": {"name": tenant.name, "slug": tenant.slug, "preset": tenant.preset, "schema": tenant.schema_name,
                   "enabled_modules": tenant.enabled_modules, "settings": tenant.settings,
                   "trial_ends_at": tenant.trial_ends_at.isoformat() if tenant.trial_ends_at else None},
        "nav": [n for n in modreg.nav_for(tenant.enabled_modules) if user.has_perm_code(n.get("perm", "core.*"))],
    }


def _live(request):
    """Jonli demo (faqat namuna restoranlar): vaqt o'tgani sari savdo, ombor, zakup… o'zi davom etadi."""
    from public.live import tick
    tick(getattr(request, "tenant", None))


@api.get("/me", auth=auth, tags=["auth"])
def me(request):
    _live(request)
    return _me(request, request.auth)


class MeIn(Schema):
    full_name: Optional[str] = None
    language: Optional[str] = None
    pin: Optional[str] = None


@api.patch("/me", auth=auth, tags=["auth"])
def update_me(request, data: MeIn):
    u = request.auth
    if data.full_name is not None:
        u.full_name = data.full_name
    if data.language:
        u.language = data.language
    if data.pin:
        u.set_pin(data.pin)
    u.save()
    return _me(request, u)


@api.post("/me/avatar", auth=auth, tags=["auth"])
def upload_my_avatar(request, file: UploadedFile = File(...)):
    """Har bir xodim o'z profil rasmini qo'yadi (telefondan kamera ham bo'ladi)."""
    avatars.set_avatar(request.auth, file)
    return _me(request, request.auth)


@api.delete("/me/avatar", auth=auth, tags=["auth"])
def delete_my_avatar(request):
    avatars.clear_avatar(request.auth)
    return _me(request, request.auth)


# ------------------------------------------------------------------ modullar
@api.get("/modules", auth=auth, tags=["modules"])
def list_modules(request):
    enabled = set(request.tenant.enabled_modules)
    plan = request.tenant.plan
    return [{**m.to_dict(), "enabled": m.code in enabled, "allowed_by_plan": plan is None or plan.allows(m.code)} for m in modreg.all_modules()]


class ModulesIn(Schema):
    enabled: list[str]


@api.put("/modules", auth=auth, tags=["modules"])
def update_modules(request, data: ModulesIn):
    require_perm(request, "core.modules.manage")
    before = list(request.tenant.enabled_modules)
    known = [c for c in data.enabled if modreg.get(c)]
    # hali yozilmagan (rejadagi) modullar yoqilmaydi — aks holda bazada "yoqilgan" turadi, menyuda esa hech narsa yo'q
    skipped = [c for c in known if not modreg.get(c).implemented]
    try:
        resolved = set_modules(request.tenant, [c for c in known if modreg.get(c).implemented])
    except PermissionError as e:
        raise HttpError(403, str(e)) from e
    record(request, "modules", model="Tenant", before={"enabled": before}, after={"enabled": resolved})
    return {"enabled": resolved, "nav": modreg.nav_for(resolved), "skipped": skipped}


@api.get("/permissions", auth=auth, tags=["modules"])
def list_permissions(request):
    return modreg.all_permissions(request.tenant.enabled_modules)


# ------------------------------------------------------------------ tenant sozlamalari
class TenantSettingsIn(Schema):
    name: Optional[str] = None
    settings: Optional[dict] = None


@api.put("/tenant", auth=auth, tags=["tenant"])
def update_tenant(request, data: TenantSettingsIn):
    require_perm(request, "core.settings.edit")
    t = request.tenant
    before = {"name": t.name, "settings": t.settings}
    if data.name:
        t.name = data.name
    if data.settings is not None:
        t.settings = {**t.settings, **data.settings}
    t.save(update_fields=["name", "settings"])
    record(request, "update", model="Tenant", before=before, after={"name": t.name, "settings": t.settings})
    return {"name": t.name, "settings": t.settings}


# ------------------------------------------------------------------ filiallar
class BranchIn(Schema):
    name: str
    address: str = ""
    phone: str = ""
    lat: Optional[float] = None
    lng: Optional[float] = None
    working_hours: dict = {}
    is_active: bool = True
    settings: dict = {}
    disabled_modules: list[str] = []


class BranchOut(BranchIn):
    id: int
    sort_order: int


@api.get("/branches", response=list[BranchOut], auth=auth, tags=["branches"])
def list_branches(request):
    return Branch.objects.filter(deleted_at__isnull=True)


@api.post("/branches", response=BranchOut, auth=auth, tags=["branches"])
def create_branch(request, data: BranchIn):
    require_perm(request, "core.branches.manage")
    plan = request.tenant.plan
    if plan and Branch.objects.filter(deleted_at__isnull=True).count() >= plan.max_branches:
        raise HttpError(403, f"Tarif bo'yicha filiallar limiti: {plan.max_branches}")
    b = Branch.objects.create(**data.dict(), sort_order=Branch.objects.count())
    record(request, "create", b)
    return b


@api.put("/branches/{bid}", response=BranchOut, auth=auth, tags=["branches"])
def update_branch(request, bid: int, data: BranchIn):
    require_perm(request, "core.branches.manage")
    b = get_object_or_404(Branch, pk=bid, deleted_at__isnull=True)
    for k, v in data.dict().items():
        setattr(b, k, v)
    b.save()
    record(request, "update", b)
    return b


@api.delete("/branches/{bid}", auth=auth, tags=["branches"])
def delete_branch(request, bid: int):
    require_perm(request, "core.branches.manage")
    b = get_object_or_404(Branch, pk=bid, deleted_at__isnull=True)
    b.soft_delete()
    record(request, "delete", b)
    return {"ok": True}


# ------------------------------------------------------------------ rollar va foydalanuvchilar
class RoleIn(Schema):
    code: str
    name: str
    permissions: list[str] = []
    requires_pin_for: list[str] = []


class RoleOut(RoleIn):
    id: int
    is_system: bool


@api.get("/roles", response=list[RoleOut], auth=auth, tags=["users"])
def list_roles(request):
    return Role.objects.all()


@api.post("/roles", response=RoleOut, auth=auth, tags=["users"])
def create_role(request, data: RoleIn):
    require_perm(request, "core.users.manage")
    r = Role.objects.create(**data.dict())
    record(request, "create", r)
    return r


@api.put("/roles/{rid}", response=RoleOut, auth=auth, tags=["users"])
def update_role(request, rid: int, data: RoleIn):
    require_perm(request, "core.users.manage")
    r = get_object_or_404(Role, pk=rid)
    if r.is_system and r.code == "owner":
        raise HttpError(400, "Egasi rolini o'zgartirib bo'lmaydi")
    for k, v in data.dict().items():
        setattr(r, k, v)
    r.save()
    record(request, "update", r)
    return r


class UserIn(Schema):
    phone: str
    full_name: str = ""
    role_code: str
    branch_ids: list[int] = []
    language: str = "uz"


class UserOut(Schema):
    id: str
    phone: str
    full_name: str
    avatar: Optional[str] = None
    language: str
    is_active: bool
    roles: list[str]
    branch_ids: list[int]
    last_seen_at: Optional[str] = None

    @staticmethod
    def resolve_id(obj):
        return str(obj.pk)

    @staticmethod
    def resolve_avatar(obj):
        return obj.avatar.url if obj.avatar else None

    @staticmethod
    def resolve_roles(obj):
        return [m.role.code for m in obj.memberships.all()]

    @staticmethod
    def resolve_branch_ids(obj):
        ids: set[int] = set()
        for m in obj.memberships.all():
            ids.update(m.branches.values_list("id", flat=True))
        return sorted(ids)

    @staticmethod
    def resolve_last_seen_at(obj):
        return obj.last_seen_at.isoformat() if obj.last_seen_at else None


@api.get("/users", response=list[UserOut], auth=auth, tags=["users"])
def list_users(request):
    require_perm(request, "core.users.manage")
    return User.objects.prefetch_related("memberships__role", "memberships__branches").filter(is_active=True)


@api.post("/users", response=UserOut, auth=auth, tags=["users"])
def create_user(request, data: UserIn):
    require_perm(request, "core.users.manage")
    role = get_object_or_404(Role, code=data.role_code)
    phone = User.objects.normalize_phone(data.phone)
    u, created = User.objects.get_or_create(phone=phone, defaults={"full_name": data.full_name, "language": data.language})
    m, _ = Membership.objects.get_or_create(user=u, role=role)
    m.branches.set(data.branch_ids)
    record(request, "create" if created else "update", u)
    return u


@api.post("/users/{uid}/avatar", response=UserOut, auth=auth, tags=["users"])
def upload_user_avatar(request, uid: str, file: UploadedFile = File(...)):
    """Egasi / administrator istalgan xodimning rasmini qo'yadi."""
    require_perm(request, "core.users.manage")
    u = get_object_or_404(User, pk=uid)
    avatars.set_avatar(u, file)
    record(request, "update", u, after={"avatar": u.avatar.name})
    return u


@api.delete("/users/{uid}/avatar", response=UserOut, auth=auth, tags=["users"])
def delete_user_avatar(request, uid: str):
    require_perm(request, "core.users.manage")
    u = get_object_or_404(User, pk=uid)
    avatars.clear_avatar(u)
    return u


@api.delete("/users/{uid}", auth=auth, tags=["users"])
def deactivate_user(request, uid: str):
    require_perm(request, "core.users.manage")
    u = get_object_or_404(User, pk=uid)
    if u == request.auth:
        raise HttpError(400, "O'zingizni o'chira olmaysiz")
    u.is_active = False
    u.save(update_fields=["is_active"])
    record(request, "deactivate", u)
    return {"ok": True}


# ------------------------------------------------------------------ audit / dashboard
@api.get("/audit", auth=auth, tags=["audit"])
def list_audit(request, model: Optional[str] = None, limit: int = 50):
    require_perm(request, "core.settings.view")
    qs = AuditLog.objects.select_related("actor")
    if model:
        qs = qs.filter(model=model)
    return [{"id": a.id, "at": a.at.isoformat(), "actor": str(a.actor) if a.actor else None, "action": a.action,
             "model": a.model, "object_id": a.object_id, "before": a.before, "after": a.after} for a in qs[: min(limit, 200)]]


def _delta(cur, prev):
    return round(100 * (cur - prev) / prev, 1) if prev else None


def _has_recipes():
    try:
        from modules.inventory.models import Recipe
        return Recipe.objects.exists()
    except Exception:
        return False


def _has_shift():
    try:
        from modules.pos.models import CashShift
        return CashShift.objects.exists()
    except Exception:
        return False


@api.get("/dashboard/summary", auth=auth, tags=["dashboard"])
def dashboard_summary(request):
    """Bosqich 1: sozlash holati. Kassa (4-bosqich) kelganda savdo KPI'lari shu yerga qo'shiladi."""
    from modules.catalog.models import Category, MenuVersion, Product
    from modules.cms.models import SiteSection, SiteSettings

    t = request.tenant
    published = MenuVersion.objects.order_by("-version").first()
    site = SiteSettings.get()
    kpis = []
    if t.module_enabled("pos"):
        from datetime import timedelta as _td

        from django.db.models import Count as _C
        from django.db.models import Sum as _S

        from modules.finance.reports import pnl as _pnl
        from modules.pos.models import Order as _O
        from modules.pos.models import OrderStatus as _OS
        today = timezone.localdate()
        d = _pnl(today, today)
        m = _pnl(today.replace(day=1), today)
        # adolatli taqqoslash: bugun hozirgacha ↔ kecha xuddi shu soatgacha (ertalab doim "qizil" chiqmasin)
        now = timezone.now()
        ya = _O.objects.filter(status=_OS.PAID, paid_at__date=today - _td(days=1), paid_at__lte=now - _td(days=1)).aggregate(r=_S("total"), n=_C("id"))
        y_rev, y_n = int(ya["r"] or 0), ya["n"] or 0
        y_avg = int(y_rev / y_n) if y_n else 0
        kpis += [
            {"key": "revenue", "label": "Bugungi savdo", "value": d["revenue"], "money": True, "delta": _delta(d["revenue"], y_rev), "hint": f"kecha shu vaqtgacha {y_rev:,}".replace(",", " ")},
            {"key": "orders", "label": "Buyurtmalar", "value": d["orders"], "delta": _delta(d["orders"], y_n), "hint": f"kecha shu vaqtgacha {y_n}"},
            {"key": "avg_check", "label": "O'rtacha chek", "value": d["avg_check"], "money": True, "delta": _delta(d["avg_check"], y_avg)},
            {"key": "food_cost", "label": "Food cost (oy)", "value": f"{m['food_cost_percent']}%", "hint": "Me'yor: 28–35%", "warn": m["food_cost_percent"] > 35},
            {"key": "labor", "label": "Mehnat xarajati (oy)", "value": f"{m['labor_percent']}%", "hint": "Me'yor: ≤ 25%", "warn": m["labor_percent"] > 25},
            {"key": "net", "label": "Sof foyda (oy)", "value": m["net_profit"], "money": True, "hint": f"Marja: {m['net_margin_percent']}%"},
        ]
    if t.module_enabled("tasks"):
        from modules.tasks.models import Task
        kpis.append({"key": "tasks_overdue", "label": "Kechikkan vazifalar", "value": Task.objects.overdue().count(),
                     "warn": Task.objects.overdue().exists(), "route": "/tasks"})
    if t.module_enabled("inventory"):
        from modules.inventory.models import Ingredient
        low = sum(1 for i in Ingredient.objects.filter(deleted_at__isnull=True, is_active=True) if i.is_low)
        kpis.append({"key": "low_stock", "label": "Tugayotgan xomashyo", "value": low, "warn": low > 0, "route": "/inventory"})
    if not kpis:
        kpis = [
            {"key": "branches", "label": "Filiallar", "value": Branch.objects.filter(deleted_at__isnull=True).count()},
            {"key": "products", "label": "Taomlar", "value": Product.objects.filter(deleted_at__isnull=True).count()},
            {"key": "categories", "label": "Kategoriyalar", "value": Category.objects.filter(deleted_at__isnull=True).count()},
            {"key": "menu_version", "label": "E'lon qilingan menyu", "value": f"v{published.version}" if published else "yo'q"},
            {"key": "sections", "label": "Sayt bo'limlari", "value": SiteSection.objects.filter(is_enabled=True).count()},
            {"key": "users", "label": "Foydalanuvchilar", "value": User.objects.filter(is_active=True).count()},
        ]
    return {
        "tenant": {"name": t.name, "preset": t.preset, "trial_ends_at": t.trial_ends_at.isoformat() if t.trial_ends_at else None},
        "kpis": kpis,
        "checklist": [
            {"key": "menu", "label": "Taomnoma kiritilgan", "done": Product.objects.exists(), "route": "/catalog"},
            {"key": "publish", "label": "Taomnoma e'lon qilingan", "done": published is not None, "route": "/catalog"},
            {"key": "site", "label": "Sayt sozlangan (nom, telefon)", "done": bool(site.title and site.phone), "route": "/site"},
            {"key": "branch", "label": "Filial manzili kiritilgan", "done": Branch.objects.exclude(address="").exists(), "route": "/branches"},
            {"key": "users", "label": "Xodimlar qo'shilgan", "done": User.objects.count() > 1, "route": "/users"},
            {"key": "recipes", "label": "Tex-kartalar kiritilgan (tannarx)", "done": _has_recipes(), "route": "/inventory"},
            {"key": "shift", "label": "Kassa smenasi ochilgan", "done": _has_shift(), "route": "/pos"},
        ],
        "enabled_modules": t.enabled_modules,
    }


@api.get("/dashboard/overview", auth=auth, tags=["dashboard"])
def dashboard_overview(request, period: str = "today", branch_id: Optional[int] = None):
    """Menejer paneli: KPI, dinamika, holat, top, filiallar, so'nggi buyurtmalar, ombor, vazifalar, faoliyat."""
    from .dashboard import overview
    _live(request)
    return overview(request, period, branch_id)


@api.get("/dashboard/sections", auth=auth, tags=["dashboard"])
def dashboard_sections(request):
    """Har bo'lim uchun 3–5 ta asosiy ko'rsatkich (bo'lim sahifasi va asosiy sahifa plitkalari uchun)."""
    from .sections import sections
    _live(request)
    return sections(request)


# ------------------------------------------------------------------ modullar routerlari
from integrations.telegram.api import router as telegram_router  # noqa: E402
from modules.catalog.api import router as catalog_router  # noqa: E402
from modules.cms.api import router as cms_router  # noqa: E402
from modules.crm.api import router as crm_router  # noqa: E402
from modules.finance.api import router as finance_router  # noqa: E402
from modules.forecast.api import router as forecast_router  # noqa: E402
from modules.hr.api import router as hr_router  # noqa: E402
from modules.inventory.api import router as inventory_router  # noqa: E402
from modules.kds.api import router as kds_router  # noqa: E402
from modules.ops.api import router as ops_router  # noqa: E402
from modules.payments.api import router as payments_router  # noqa: E402
from modules.pos.api import router as pos_router  # noqa: E402
from modules.procurement.api import router as procurement_router  # noqa: E402
from modules.projects.api import router as projects_router  # noqa: E402
from modules.reservations.api import router as reservations_router  # noqa: E402
from modules.tables.api import router as tables_router  # noqa: E402
from modules.tasks.api import router as tasks_router  # noqa: E402
from modules.telegram.api import router as bot_router  # noqa: E402
from modules.training.api import router as training_router  # noqa: E402

api.add_router("/catalog", catalog_router)
api.add_router("/cms", cms_router)
api.add_router("/tasks", tasks_router)
api.add_router("/inventory", inventory_router)
api.add_router("/pos", pos_router)
api.add_router("/payments", payments_router)
api.add_router("/hr", hr_router)
api.add_router("/finance", finance_router)
api.add_router("/kds", kds_router)
api.add_router("/tables", tables_router)
api.add_router("/reservations", reservations_router)
api.add_router("/telegram", telegram_router)
api.add_router("/training", training_router)
api.add_router("/bot", bot_router)
api.add_router("/crm", crm_router)
api.add_router("/forecast", forecast_router)
api.add_router("/ops", ops_router)
api.add_router("/procurement", procurement_router)
api.add_router("/projects", projects_router)

from api.platform_api import router as platform_router  # noqa: E402

api.add_router("/platform", platform_router)


@api.get("/health", tags=["system"])
def health(request):
    return {"ok": True, "tenant": request.tenant.schema_name, "modules": request.tenant.enabled_modules}
'@

Put 'backend\api\sections.py' @'
"""
Bo'lim panellari — /api/v1/dashboard/sections
Har bo'lim (Savdo, Menyu va mijozlar, Ombor va xarid, Xodimlar, O'qitish, Vazifa va loyihalar, Moliya, Sozlamalar) uchun
3–5 ta asosiy ko'rsatkich: qiymat, izoh, rang (ok / warn / bad) va qaysi sahifaga olib borishi.
Modul o'chiq yoki ruxsat bo'lmasa — o'sha ko'rsatkich chiqmaydi. Bir blokdagi xato boshqasini to'xtatmaydi.
"""
from __future__ import annotations

import logging
from datetime import timedelta

from django.db.models import Sum
from django.utils import timezone

log = logging.getLogger(__name__)


def _m(v: int | float) -> str:
    v = int(v or 0)
    if abs(v) >= 1_000_000:
        return f"{v / 1_000_000:.1f}".replace(".", ",") + " mln"
    return f"{v:,}".replace(",", " ")


def _k(label, value, hint="", tone="", route="", icon=""):
    return {"label": label, "value": value, "hint": hint, "tone": tone, "route": route, "icon": icon}


def sections(request) -> dict:
    t, u = request.tenant, request.auth
    on = set(t.enabled_modules or [])
    can = u.has_perm_code
    today = timezone.localdate()
    ms = today.replace(day=1)
    out: dict[str, list] = {}

    def block(code, fn):
        try:
            rows = [r for r in fn() if r]
            if rows:
                out[code] = rows
        except Exception:
            log.exception("bo'lim paneli: %s", code)

    # ---------- Savdo va xizmat
    def sales():
        from modules.pos.models import Order
        rows = []
        if "pos" in on and (can("pos.sell") or can("finance.view")):
            q = Order.objects.filter(status="paid", paid_at__date=today)
            s = int(q.aggregate(s=Sum("total"))["s"] or 0)
            n = q.count()
            y = int(Order.objects.filter(status="paid", paid_at__date=today - timedelta(days=7),
                                         paid_at__time__lte=timezone.localtime().time()).aggregate(s=Sum("total"))["s"] or 0)
            d = round(100 * (s - y) / y) if y else None
            rows += [_k("Bugungi savdo", _m(s), f"{n} ta chek" + (f" · o'tgan haftaga {d:+d}%" if d is not None else ""), "ok" if (d or 0) >= 0 else "warn", "/pos", "💰"),
                     _k("O'rtacha chek", _m(s // n if n else 0), "so'm", "", "/reports", "🧾")]
        if "kds" in on:
            from modules.kds.models import Ticket
            act = Ticket.objects.exclude(status__in=["served", "cancelled"])
            ready = act.filter(status="ready").count()
            rows.append(_k("Oshxonada hozir", act.count(), f"{ready} tasi tayyor — olib chiqish kerak" if ready else "hammasi jarayonda", "warn" if ready else "", "/kds", "👨‍🍳"))
        if "tables" in on:
            from modules.tables.models import Table, TableSession
            busy = TableSession.objects.filter(closed_at__isnull=True).count()
            tot = Table.objects.filter(is_active=True).count()
            rows.append(_k("Band stollar", f"{busy} / {tot}", "zal xaritasi", "", "/tables", "🪑"))
        if "reservations" in on:
            from modules.reservations.models import Reservation
            r = Reservation.objects.filter(starts_at__date=today).exclude(status__in=["cancelled", "no_show"])
            rows.append(_k("Bugungi bronlar", r.count(), f"{r.aggregate(g=Sum('guests'))['g'] or 0} mehmon", "", "/reservations", "📅"))
        return rows
    block("sales", sales)

    # ---------- Menyu va mijozlar
    def menu():
        rows = []
        if "catalog" in on:
            from modules.catalog.models import Product
            ps = Product.objects.filter(deleted_at__isnull=True, is_active=True)
            stop = ps.filter(in_stop_list=True).count()
            rows.append(_k("Taomlar", ps.count(), f"{stop} tasi stop-listda" if stop else "hammasi sotuvda", "warn" if stop else "", "/catalog", "🍽️"))
        if "pos" in on:
            from modules.pos.models import OrderItem
            top = (OrderItem.objects.filter(order__status="paid", order__paid_at__date__gte=today - timedelta(days=6))
                   .values("name").annotate(q=Sum("qty")).order_by("-q").first())
            if top:
                rows.append(_k("Hafta xiti", top["name"], f"{top['q']} porsiya (7 kun)", "", "/reports", "🔥"))
        if "crm" in on and can("crm.view"):
            from modules.crm.models import Customer
            new = Customer.objects.filter(created_at__date__gte=today - timedelta(days=29)).count()
            rows.append(_k("Mijozlar", Customer.objects.count(), f"+{new} yangi (30 kun)", "ok" if new else "", "/crm", "❤️"))
        if "telegram" in on and can("telegram.view"):
            from modules.telegram.models import BotUser
            rows.append(_k("Telegram obunachilar", BotUser.objects.filter(is_blocked=False).count(), "botdagi mijozlar", "", "/telegram", "✈️"))
        return rows
    block("menu", menu)

    # ---------- Ombor va xarid
    def stock():
        rows = []
        if "inventory" in on and can("inventory.view"):
            from modules.inventory.models import Ingredient, Purchase
            ings = list(Ingredient.objects.filter(deleted_at__isnull=True, is_active=True))
            val = sum(float(i.stock) * float(i.price) for i in ings if i.stock > 0)
            low = [i for i in ings if i.is_low]
            rows.append(_k("Ombor qiymati", _m(val), f"{len(ings)} xil xomashyo", "", "/inventory", "📦"))
            rows.append(_k("Kam qolgan", len(low), ", ".join(str(i) for i in low[:3]) or "hammasi yetarli", "bad" if len(low) > 3 else "warn" if low else "ok",
                           "/inventory", "⚠️"))
            mp = int(Purchase.objects.filter(date__gte=ms).aggregate(s=Sum("total"))["s"] or 0)
            rows.append(_k("Shu oy xarid", _m(mp), "kirimlar jami", "", "/procurement" if "procurement" in on else "/inventory", "🛒"))
        if "procurement" in on and can("procurement.view"):
            from modules.procurement.models import Order as PO
            from modules.procurement.models import Trip
            from modules.procurement.services import debts
            dd = debts().values()
            debt = sum(x["debt"] for x in dd)
            over = sum(1 for x in dd if x["overdue"])
            rows.append(_k("Ta'minotchilarga qarz", _m(debt), f"{over} tasi muddati o'tgan" if over else "muddati o'tgani yo'q", "bad" if over else "", "/procurement?tab=debts", "💳"))
            way = PO.objects.filter(status__in=["sent", "confirmed"]).count()
            trips = Trip.objects.filter(status__in=["planned", "active"]).count()
            rows.append(_k("Yo'ldagi zakup", way, f"{trips} ta ochiq bozorlik" if trips else "buyurtmalar", "", "/procurement?tab=orders", "🚚"))
        return rows
    block("stock", stock)

    # ---------- Xodimlar
    def team():
        rows = []
        if "hr" in on and can("hr.view"):
            from modules.hr.models import Attendance, Employee, ShiftPlan
            emps = Employee.objects.filter(is_active=True)
            att = Attendance.objects.filter(check_in__date=today)
            planned = ShiftPlan.objects.filter(date=today).count()
            late = att.filter(late_minutes__gt=0).count()
            rows.append(_k("Xodimlar", emps.count(), f"{emps.values('position').distinct().count()} lavozimda", "", "/hr", "👥"))
            rows.append(_k("Bugun ishda", f"{att.values('employee').distinct().count()} / {planned}", "keldi / smenada", "", "/hr", "🕘"))
            rows.append(_k("Kechikishlar", late, "bugun" if late else "bugun hamma o'z vaqtida", "warn" if late else "ok", "/hr", "⏰"))
            if can("hr.recruit"):
                from modules.hr.models import Application, Vacancy
                vac = Vacancy.objects.filter(status="open").count()
                apps = Application.objects.exclude(stage__in=["hired", "rejected"]).count()
                rows.append(_k("Ishga olish", f"{vac} vakansiya", f"{apps} nomzod jarayonda", "", "/recruiting", "📣"))
        return rows
    block("team", team)

    # ---------- O'qitish va standartlar
    def training():
        rows = []
        if "training" in on:
            from modules.training.models import Course, Enrollment, Standard, StandardAck, Submission
            en = Enrollment.objects.filter(course__is_archived=False)
            tot = en.count()
            done = en.filter(status="completed").count()
            late = sum(1 for e in en.exclude(status="completed").only("status", "due_at") if e.due_at and e.due_at < timezone.now())
            rows.append(_k("Kurslar", Course.objects.filter(is_published=True, is_archived=False).count(), f"{tot} ta biriktirish", "", "/training?tab=courses", "🎓"))
            rows.append(_k("Tugatganlar", f"{round(100 * done / tot) if tot else 0}%", f"{done} / {tot} kurs yakunlangan", "ok" if tot and done / tot > 0.6 else "warn", "/training?tab=report", "✅"))
            rows.append(_k("Kechikkan o'qish", late, "muddati o'tgan kurslar" if late else "kechikkan yo'q", "bad" if late else "ok", "/training?tab=report", "⏳"))
            chk = Submission.objects.filter(status="submitted").count()
            rows.append(_k("Tekshirish kerak", chk, "topshiriq dalillari", "warn" if chk else "", "/training?tab=assignments", "📸"))
            stds = Standard.objects.count()
            if stds:
                rows.append(_k("Standartlar", stds, f"{StandardAck.objects.count()} ta imzo", "", "/training?tab=standards", "🛡️"))
        if "ops" in on and can("ops.view"):
            from modules.ops.models import PositionProfile
            rows.append(_k("Lavozim yo'riqnomalari", PositionProfile.objects.count(), "tashkiliy tuzilmada", "", "/positions", "🗂️"))
        return rows
    block("training", training)

    # ---------- Vazifa va loyihalar
    def work():
        rows = []
        if "tasks" in on and can("tasks.view"):
            from modules.tasks.models import ColumnKind, Task
            op = Task.objects.exclude(column__kind__in=[ColumnKind.DONE, ColumnKind.CANCELLED])
            over = op.filter(due_at__lt=timezone.now()).count()
            rows.append(_k("Ochiq vazifalar", op.count(), f"{over} tasi kechikkan" if over else "kechikkan yo'q", "bad" if over else "ok", "/tasks", "📋"))
            done = Task.objects.filter(done_at__date=today).count()
            rows.append(_k("Bugun bajarildi", done, "vazifa", "ok" if done else "", "/tasks", "✔️"))
        if "projects" in on and can("projects.view"):
            from modules.projects import services as ps
            live = [p for p in ps.visible_projects(u).filter(status__in=["plan", "active"]).prefetch_related("tasks")]
            risk = 0
            for p in live:
                tasks = list(p.tasks.all())
                prog = ps.progress(tasks, p.status)
                over = sum(1 for x in tasks if x.due and x.due < today and x.status != "done")
                if ps.health(p, prog, over, 25, ps.planned_progress(p, tasks)) in ("risk", "late"):
                    risk += 1
            rows.append(_k("Faol loyihalar", len(live), f"{risk} tasi xavf ostida" if risk else "hammasi o'z vaqtida", "warn" if risk else "ok", "/projects", "🚩"))
        return rows
    block("work", work)

    # ---------- Moliya
    def finance():
        rows = []
        if "finance" in on and can("finance.view") and "pos" in on:
            from modules.pos.models import Order
            q = Order.objects.filter(status="paid", paid_at__date__gte=ms)
            agg = q.aggregate(s=Sum("total"), c=Sum("cost_total"))
            rev, cost = int(agg["s"] or 0), int(agg["c"] or 0)
            from modules.finance.models import Expense
            exp = int(Expense.objects.filter(date__gte=ms).aggregate(s=Sum("amount"))["s"] or 0)
            fc = round(100 * cost / rev, 1) if rev else 0
            rows.append(_k("Shu oy savdo", _m(rev), f"{q.count()} ta chek", "", "/reports", "📈"))
            rows.append(_k("Food cost", f"{fc}%", "me'yor 28–35%", "ok" if 0 < fc <= 35 else "warn", "/reports", "🥘"))
            rows.append(_k("Xarajatlar (oy)", _m(exp), "ijara, kommunal, soliq…", "", "/reports", "💸"))
            rows.append(_k("Yalpi foyda", _m(rev - cost - exp), "savdo − tannarx − xarajat", "ok" if rev - cost - exp > 0 else "bad", "/reports", "💵"))
        return rows
    block("finance", finance)

    # ---------- Sozlamalar
    def settings_():
        from core.models import Branch, Membership
        rows = [_k("Filiallar", Branch.objects.filter(deleted_at__isnull=True, is_active=True).count(), "faol", "", "/branches", "🏪")]
        if can("core.users.manage"):
            rows.append(_k("Foydalanuvchilar", Membership.objects.filter(is_active=True).values("user").distinct().count(), "tizimga kira oladi", "", "/users", "👤"))
        rows.append(_k("Yoqilgan modullar", len(on), "tarifingiz bo'yicha", "", "/modules", "🧩"))
        if t.trial_ends_at and t.trial_ends_at > timezone.now():
            left = timezone.localtime(t.trial_ends_at).date() - today
            rows.append(_k("Sinov muddati", f"{max(0, left.days)} kun", "qoldi", "warn" if left.days < 7 else "", "/support", "⏳"))
        return rows
    block("settings", settings_)
    return out
'@

Put 'backend\modules\tasks\listeners.py' @'
"""
Hodisa tinglovchilari. Modul o'chirilgan bo'lsa bu funksiyalar umuman chaqirilmaydi (core/events.py).

Bu yerda modullar bir-biriga "yopishmaydi": ombor moduli keyin `inventory.low_stock` chiqaradi —
biz avtomatik vazifa ochamiz; POS `pos.shift_closed` chiqaradi — tozalash checklisti tug'iladi va h.k.
"""
from __future__ import annotations

import logging

from core.events import on

log = logging.getLogger("tasks")


@on("tenant.created")
def setup_board(payload: dict) -> None:
    """Yangi restoran: Kanban ustunlari, bo'limlar va muammo turlari darhol tayyor bo'lsin."""
    from .services import ensure_setup

    ensure_setup()


@on("inventory.low_stock")
def task_from_low_stock(payload: dict) -> None:
    """Ombor moduli (2-bosqich) kam qoldiq haqida xabar bersa — ta'minot vazifasi ochiladi."""
    from .models import Source, TaskCategory
    from .services import create_task

    class _Req:
        auth = None
        tenant = None

    from .models import ColumnKind, Task
    name = payload.get("product_name") or "Mahsulot"
    title = f"Ta'minot: {name} tugayapti"
    # har savdoda qayta ochilmasin — shu mahsulot bo'yicha ochiq vazifa bo'lsa, yangisi kerak emas
    if Task.objects.filter(title=title).exclude(column__kind__in=[ColumnKind.DONE, ColumnKind.CANCELLED]).exists():
        return
    create_task(_Req(), title=title,
                description=f"Qoldiq: {payload.get('qty', '—')}. Zakaz berish kerak.",
                category=TaskCategory.objects.filter(code="supply").first(),
                source=Source.SYSTEM)


@on("forecast.holiday_soon")
def task_from_holiday(payload: dict) -> None:
    """Bayram yaqinlashdi — ta'minot vazifasi: nima va qachongacha xarid qilish kerak."""
    from datetime import datetime, time

    from django.utils import timezone

    from .models import Source, TaskCategory
    from .services import create_task

    class _Req:
        auth = None
        tenant = None

    due = None
    try:
        due = timezone.make_aware(datetime.combine(datetime.strptime(payload.get("buy_by", ""), "%d.%m.%Y").date(), time(18, 0)))
    except ValueError:
        pass
    cost = f"{int(payload.get('total_cost') or 0):,}".replace(",", " ")
    items = ", ".join(payload.get("items") or [])
    desc = (f"{payload.get('name')} — {payload.get('date')}. " +
            (f"{payload.get('short_count')} ta xomashyo yetmaydi ({items}…), taxminan {cost} so'm. "
             if payload.get("short_count") else "Ombor yetarli, qoldiqlarni tekshiring. ") +
            "To'liq ro'yxat: Ombor → Xarid rejasi.")
    create_task(_Req(), title=f"Bayramga tayyorgarlik: {payload.get('name')}", description=desc, due_at=due,
                category=TaskCategory.objects.filter(code="supply").first(), source=Source.SYSTEM)


@on("tasks.overdue")
def notify_overdue(payload: dict) -> None:
    """Kechikkan vazifa — hozircha log, Telegram moduli ulangach o'sha yerga ketadi."""
    log.warning("Vazifa kechikdi: #%s %s", payload.get("number"), payload.get("title"))


# ------------------------------------------------------------------ Telegram bildirishnomalari (real Bot API)
def _tg(user_id, text: str) -> None:
    if not user_id:
        return
    from core.models import User
    from integrations.telegram import send_message

    u = User.objects.filter(pk=user_id, telegram_id__isnull=False).first()
    if u:
        send_message(u.telegram_id, text)


@on("tasks.created")
def tg_created(payload: dict) -> None:
    _tg(payload.get("assignee_id"), f"🆕 Yangi vazifa #{payload.get('number')}: <b>{payload.get('title')}</b>"
        + (f"\nMuddat: {payload['due_at'][:16].replace('T', ' ')}" if payload.get("due_at") else ""))


@on("tasks.submitted")
def tg_submitted(payload: dict) -> None:
    _tg(payload.get("supervisor_id"), f"🔎 Tekshiruvga topshirildi #{payload.get('number')}: <b>{payload.get('title')}</b>\nDalilni ko'rib tasdiqlang yoki qaytaring.")


@on("tasks.rejected")
def tg_rejected(payload: dict) -> None:
    _tg(payload.get("assignee_id"), f"↩️ Qaytarildi #{payload.get('number')}: <b>{payload.get('title')}</b>\nSabab: {payload.get('reason', '')}")


@on("tasks.approved")
def tg_approved(payload: dict) -> None:
    _tg(payload.get("assignee_id"), f"✅ Tasdiqlandi #{payload.get('number')}: <b>{payload.get('title')}</b>. Rahmat!")


@on("tasks.overdue")
def tg_overdue(payload: dict) -> None:
    _tg(payload.get("supervisor_id"), f"⚠️ Muddati o'tdi #{payload.get('number')}: <b>{payload.get('title')}</b>")
'@

Put 'backend\public\live.py' @'
"""
«Jonli demo» — namuna restoranlarda vaqt o'tgani sari hayot o'zi davom etadi (xuddi haqiqiy restoran ishlayotgandek).

Har gal panel ochilganda (ko'pi bilan 4 daqiqada bir marta) oxirgi holatdan hozirgacha bo'lgan bo'shliq to'ldiriladi:
  • kassa: kun/soat bo'yicha real taqsimotda cheklar (filial, zal/olib ketish/yetkazish, to'lov usuli — tarixdagi ulushlarda),
           mijozlar kartasi va bonus, ~1% bekor qilingan, kassa smenalari;
  • ombor: sotilgan taomlar tex-karta bo'yicha xomashyoni kamaytiradi → kam qolsa vazifa ochiladi;
  • zakup: kam qolgan xomashyo — kompaniyadan buyurtma (qabul, to'lov, nasiya) yoki bozorlik (avans, taksi/hammol, qaytgan pul);
  • hozir: oshxona ekranida 3–6 ta faol buyurtma, zalda band stollar;
  • xodimlar: smena jadvali va davomat (kechikishlar bilan);
  • bron: bugun va keyingi kunlarga bronlar; moliya: oy boshida ijara/kommunal/soliq; oylik varaqlari;
  • loyihalar: muddati o'tgan vazifalarning ko'pi bajariladi.
Faqat `tenant.settings["demo_live"] = True` bo'lgan restoranlarda ishlaydi (haqiqiy mijozlarga hech qachon tegmaydi).
Yoqish: python manage.py demo_live --slug namuna --on
"""
from __future__ import annotations

import logging
import random
from collections import Counter, defaultdict
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from django.core.cache import cache
from django.db import transaction
from django.db.models import Count, Max, Sum
from django.utils import timezone

log = logging.getLogger("live")

KEY = "demo_live"
HOURS = list(range(10, 23))                                  # 10:00–22:59
HOUR_W = [2, 3, 6, 8, 6, 4, 4, 5, 7, 9, 8, 5, 2]             # tushlik va kechki cho'qqi
MAX_GAP_DAYS = 45


def is_live(tenant) -> bool:
    try:
        return bool((tenant.settings or {}).get(KEY))
    except Exception:
        return False


def tick(tenant, *, force: bool = False, now: datetime | None = None) -> dict:
    """Bo'shliqni to'ldiradi. Tez: hech narsa qilish kerak bo'lmasa — bir necha mikrosoniya (kesh)."""
    if tenant is None or getattr(tenant, "schema_name", "public") == "public" or not is_live(tenant):
        return {}
    k = f"live:tick:{tenant.schema_name}"
    if force:
        cache.set(k, 1, 240)
    elif not cache.add(k, 1, 240):
        return {}
    lock = f"live:lock:{tenant.schema_name}"
    if not cache.add(lock, 1, 900):
        return {}
    try:
        return _run(tenant, timezone.localtime(now or timezone.now()))
    except Exception:                                    # demo xatosi hech qachon panelni yiqitmasin
        log.exception("live tick xatosi")
        return {"error": True}
    finally:
        cache.delete(lock)


# ------------------------------------------------------------------ asosiy
def _run(t, now: datetime) -> dict:
    from modules.pos.models import Order
    last = Order.objects.exclude(paid_at__isnull=True).aggregate(m=Max("paid_at"))["m"]
    if last is None:
        return {}
    last = timezone.localtime(last)
    start = max(last + timedelta(minutes=1), now - timedelta(days=MAX_GAP_DAYS))
    out = Counter()
    rnd = random.Random(f"{t.schema_name}:{now:%Y%m%d%H%M}")
    prof = _profile(start)
    day = start.date()
    while day <= now.date():
        a = max(start, _at(day, 10, 0))
        b = min(now, _at(day, 23, 0))
        done_day = b >= _at(day, 23, 0)
        with transaction.atomic():
            if a < b:
                out["orders"] += _sales(t, prof, day, a, b, rnd)
            if done_day or day < now.date():
                _close_shifts(day)
            out["restock"] += _restock(t, day, rnd, final=day < now.date())
            _people(day, now, rnd)
            _monthly(t, day, rnd)
        day += timedelta(days=1)
    with transaction.atomic():
        _now_kitchen(t, now, prof, rnd)
        _bookings(now, rnd)
        _projects(now, rnd)
        _payables(now)
        _daily_work(t, now, rnd)
        _learning(t, now, rnd)
    return dict(out)


def _at(d: date, h: int, m: int) -> datetime:
    return timezone.make_aware(datetime.combine(d, time(h, m)))


# ------------------------------------------------------------------ savdo profili (tarixdan)
def _profile(before: datetime) -> dict:
    from modules.catalog.models import Product
    from modules.crm.models import Customer
    from modules.pos.models import Order, OrderItem
    from modules.tables.models import Table
    since = before - timedelta(days=28)
    qs = Order.objects.filter(paid_at__gte=since, paid_at__lt=before, status="paid")
    per_wd = defaultdict(list)
    for r in qs.values("paid_at__date").annotate(n=Count("id")):
        per_wd[r["paid_at__date"].weekday()].append(r["n"])
    avg = {wd: (sum(v) / len(v)) for wd, v in per_wd.items() if v}
    base = (sum(avg.values()) / len(avg)) if avg else 60
    for wd in range(7):
        avg.setdefault(wd, base * (1.2 if wd >= 5 else 1))
    items = Counter(dict(OrderItem.objects.filter(order__in=qs).values_list("product_id").annotate(n=Sum("qty")).values_list("product_id", "n")))
    prods = {p.pk: p for p in Product.objects.filter(deleted_at__isnull=True, is_active=True, in_stop_list=False)}
    if not items:
        items = Counter({pid: 1 for pid in prods})
    pw = [(prods[pid], n) for pid, n in items.items() if pid in prods]
    def share(field):
        c = Counter(qs.values_list(field, flat=True))
        return list(c.keys()) or [None], list(c.values()) or [1]
    total = qs.count() or 1
    custs = list(Customer.objects.all().only("id", "phone", "name", "spent_total", "balance"))
    return {
        "avg": avg, "products": [p for p, _ in pw], "pw": [n for _, n in pw],
        "branch": share("branch_id"), "type": share("type"), "pay": share("payment_method"), "source": share("source"),
        "cust_ratio": qs.exclude(customer_phone="").count() / total,
        "customers": custs, "cw": [max(1.0, (c.spent_total or 0) / 100_000) for c in custs],
        "tables": list(Table.objects.filter(is_active=True).values_list("number", flat=True)) or [str(i) for i in range(1, 11)],
    }


def _pick_items(prof, rnd) -> list:
    if not prof["products"]:
        return []
    k = rnd.choices([1, 2, 3, 4], weights=[30, 38, 22, 10])[0]
    picks = {}
    for p in rnd.choices(prof["products"], weights=prof["pw"], k=k):
        picks[p.pk] = (p, picks.get(p.pk, (p, 0))[1] + rnd.choice([1, 1, 1, 2]))
    return list(picks.values())


def _shift(branch_id, d: date):
    from modules.pos.models import CashShift
    s = CashShift.objects.filter(branch_id=branch_id, opened_at__date=d).first()
    if s is None:
        from core.models import User
        cashier = User.objects.filter(memberships__role__code="cashier", is_active=True).first()
        s = CashShift.objects.create(branch_id=branch_id, opened_by=cashier, opened_at=_at(d, 9, 0), cash_start=200_000)
    return s


def _sales(t, prof, d: date, a: datetime, b: datetime, rnd) -> int:
    """[a, b) oralig'ida cheklar: kunlik o'rtacha × shu oraliqqa to'g'ri keladigan soatlar ulushi."""
    from modules.pos.models import Order, OrderItem, OrderStatus
    total_w = sum(HOUR_W)
    frac = 0.0
    slots = []
    for h, w in zip(HOURS, HOUR_W, strict=True):
        s, e = max(a, _at(d, h, 0)), min(b, _at(d, h, 0) + timedelta(hours=1))
        if e > s:
            part = (e - s).total_seconds() / 3600
            frac += w * part / total_w
            slots.append((s, e, w * part))
    if not slots:
        return 0
    n_day = prof["avg"][d.weekday()] * rnd.uniform(0.9, 1.1)
    n = int(n_day * frac + rnd.random())
    made = []
    usage = Counter()
    for _ in range(n):
        s, e, _w = rnd.choices(slots, weights=[x[2] for x in slots])[0]
        at = s + timedelta(seconds=rnd.uniform(0, (e - s).total_seconds()))
        branch_id = rnd.choices(*prof["branch"])[0]
        typ = rnd.choices(*prof["type"])[0] or "takeaway"
        o = Order(branch_id=branch_id, shift=_shift(branch_id, d), type=typ, status=OrderStatus.PAID,
                  payment_method=rnd.choices(*prof["pay"])[0] or "cash", paid_at=at,
                  source=rnd.choices(*prof["source"])[0] or "pos",
                  table_no=rnd.choice(prof["tables"]) if typ == "dine_in" else "")
        o.cashier = o.shift.opened_by
        if prof["customers"] and rnd.random() < prof["cust_ratio"]:
            c = rnd.choices(prof["customers"], weights=prof["cw"])[0]
            o.customer_phone, o.customer_name = c.phone, c.name
        o.save()
        for p, q in _pick_items(prof, rnd):
            OrderItem.objects.create(order=o, product=p, name=p.name.get("uz") or str(p), qty=q, price=p.price, cost=p.cost)
            usage[p.pk] += q
        o.recalc()
        if rnd.random() < 0.011:
            o.status, o.cancelled_at, o.cancel_reason, o.paid_at = OrderStatus.CANCELLED, at, "Mijoz bekor qildi", None
        o.save()
        Order.objects.filter(pk=o.pk).update(created_at=at - timedelta(minutes=rnd.randint(8, 25)))
        made.append(o)
    _crm(t, [o for o in made if o.status == "paid"], rnd)
    if usage:
        _consume(t, usage, d, b)
    return len(made)


def _consume(t, usage: Counter, d: date, at: datetime):
    from modules.inventory.models import StockMovement
    from modules.inventory.services import consume_for_sale
    ref = f"Savdo {d:%d.%m} (kassa)"
    before = StockMovement.objects.aggregate(m=Max("id"))["m"] or 0
    consume_for_sale([{"product_id": pid, "qty": q} for pid, q in usage.items()], ref=ref, tenant=t)
    StockMovement.objects.filter(id__gt=before, ref=ref).update(at=at)


def _crm(t, orders, rnd):
    """Mijoz kartasi: xarid soni, summa, bonus (daraja foizi bo'yicha) — kassa to'lovidagi kabi."""
    if not orders:
        return
    from modules.crm import services
    from modules.crm.models import BonusTxn, Customer, OrderLink, TxnKind
    cfg = services.conf(t)
    by = {c.phone: c for c in Customer.objects.filter(phone__in={o.customer_phone for o in orders if o.customer_phone})}
    for o in orders:
        c = by.get(o.customer_phone)
        if c is None:
            continue
        pct = services.level_of(c, cfg)["percent"]
        earned = o.total * pct // 100
        c.orders_count += 1
        c.spent_total += o.total
        c.balance += earned
        c.last_order_at = o.paid_at
        c.first_order_at = c.first_order_at or o.paid_at
        OrderLink.objects.create(order_id=o.pk, customer=c, earned=earned, settled=True)
        if earned:
            BonusTxn.objects.create(customer=c, kind=TxnKind.EARN, amount=earned, order_id=o.pk, note=f"Chek #{o.number} · {pct}%",
                                    created_at=o.paid_at)
    for c in by.values():
        c.save(update_fields=["orders_count", "spent_total", "balance", "last_order_at", "first_order_at", "updated_at"])
    # har kuni 1–3 ta yangi mijoz (birinchi xaridi bilan)
    from modules.crm.demo import MEN, SURN, WOMEN
    for o in [x for x in orders if not x.customer_phone][: rnd.randint(0, 2)]:
        f = rnd.random() < 0.5
        phone = f"+99893{rnd.randint(1000000, 9999999)}"
        if Customer.objects.filter(phone=phone).exists():
            continue
        name = f"{rnd.choice(WOMEN if f else MEN)} {rnd.choice(SURN)}{'a' if f else ''}"
        c = Customer.objects.create(phone=phone, name=name, gender="f" if f else "m", source=o.source if o.source in ("telegram", "site") else "pos",
                                    orders_count=1, spent_total=o.total, first_order_at=o.paid_at, last_order_at=o.paid_at)
        Customer.objects.filter(pk=c.pk).update(created_at=o.paid_at)
        from modules.pos.models import Order
        Order.objects.filter(pk=o.pk).update(customer_phone=phone, customer_name=name)
        OrderLink.objects.create(order_id=o.pk, customer=c, earned=0, settled=True)


def _close_shifts(d: date):
    from modules.pos.models import CashShift
    for s in CashShift.objects.filter(opened_at__date__lte=d, closed_at__isnull=True):
        if s.opened_at.date() < timezone.localdate() or d < timezone.localdate():
            tot = s.totals()
            s.closed_at = _at(s.opened_at.date(), 23, 0)
            s.cash_end = tot["expected_cash"] - random.choice([0, 0, 0, 5000, 10000])
            s.save(update_fields=["closed_at", "cash_end"])


# ------------------------------------------------------------------ ombor → zakup
def _restock(t, d: date, rnd, final: bool) -> int:
    """Kam qolgan xomashyo: bozor sotuvchisi/fermer — bozorlik; kompaniya — buyurtma. Bugun uchun — yo'lda (yuborilgan)."""
    from modules.inventory.models import Ingredient, StockMovement
    low = [i for i in Ingredient.objects.filter(deleted_at__isnull=True, is_active=True).select_related("supplier") if i.min_stock and i.stock < i.min_stock * Decimal("1.1")]
    if not low:
        return 0
    week = defaultdict(Decimal)
    for r in (StockMovement.objects.filter(kind="sale", at__date__gt=d - timedelta(days=7), at__date__lte=d, ingredient__in=low)
              .values("ingredient_id").annotate(q=Sum("qty"))):
        week[r["ingredient_id"]] = -r["q"]
    need = {}
    for i in low:
        daily = (week[i.pk] / 7) if week[i.pk] else i.min_stock / 3
        q = max(i.min_stock * Decimal("2.2"), daily * 4) - i.stock
        if q > 0:
            need[i] = _round_qty(q, i.unit)
    if not need:
        return 0
    if not t.module_enabled("procurement"):
        from modules.inventory.services import create_purchase
        create_purchase(lines=[{"ingredient_id": i.pk, "qty": q, "unit_price": i.price or 1000} for i, q in need.items()], date=d,
                        note="Ta'minot (avtomatik)", tenant=t)
        return len(need)
    from modules.procurement import services as ps
    from modules.procurement.models import Order, OrderStatus
    groups = defaultdict(dict)
    for i, q in need.items():
        groups[i.supplier_id][i] = q
    n = 0
    for sid, lines in groups.items():
        sup = next(iter(lines)).supplier
        info = ps.ensure_info(sup) if sup else None
        if Order.objects.filter(supplier_id=sid, status__in=[OrderStatus.SENT, OrderStatus.CONFIRMED]).exists():
            continue                                         # allaqachon yo'lda
        if sup is None or (info and info.kind in ("bazaar", "farmer")):
            n += _trip(t, d, lines, info, rnd, final)
        else:
            n += _order(t, d, sup, lines, rnd, final)
    return n


def _round_qty(q: Decimal, unit: str) -> Decimal:
    if unit == "dona":
        return Decimal(max(12, int((q + 11) // 12 * 12)))
    return Decimal(max(1, int(q + Decimal("0.99"))))


def _price(i, sup=None, market=None, rnd=None):
    from modules.procurement.models import SupplierPrice
    p = SupplierPrice.objects.filter(ingredient=i, **({"supplier": sup} if sup else {})).order_by("-date", "-id").values_list("price", flat=True).first()
    base = p or int(i.price) or 1000
    return max(100, int(base * (1 + (rnd.uniform(-0.04, 0.05) if rnd else 0)) / 100) * 100)


def _order(t, d: date, sup, lines: dict, rnd, final: bool) -> int:
    from modules.procurement import services as ps
    from modules.procurement.models import Order, OrderLine, OrderStatus, Payment
    o = Order.objects.create(supplier=sup, status=OrderStatus.DRAFT, expected_date=d + timedelta(days=0 if final else 1), note="Kam qolgan xomashyo (avtomatik)")
    for i, q in lines.items():
        OrderLine.objects.create(order=o, ingredient=i, qty=q, price=_price(i, sup, rnd=rnd))
    ps.recalc(o)
    Order.objects.filter(pk=o.pk).update(created_at=_at(d, 8, rnd.randint(0, 50)))
    if not final:                                        # bugun: yuborildi / tasdiqlandi — ertaga keladi
        Order.objects.filter(pk=o.pk).update(status=rnd.choice([OrderStatus.SENT, OrderStatus.CONFIRMED]), sent_at=timezone.now())
        return 1
    o.status = OrderStatus.CONFIRMED
    o.save(update_fields=["status"])
    ps.receive(o, None, tenant=t)
    _backdate_purchase(o.purchase_id, _at(d, 11, 5))
    Order.objects.filter(pk=o.pk).update(received_at=_at(d, 11, rnd.randint(0, 59)), sent_at=_at(d, 8, 10),
                                         rating=rnd.choices([5, 4, 4, 3], weights=[45, 35, 15, 5])[0])
    info = ps.ensure_info(sup)
    if info.terms != "credit":
        o.refresh_from_db()
        Payment.objects.create(supplier=sup, order=o, amount=o.total, method="cash" if info.terms == "cash" else "transfer", date=d,
                               note="Qabulda to'landi")
    return 1


def _trip(t, d: date, lines: dict, info, rnd, final: bool) -> int:
    from core.models import User
    from modules.procurement import services as ps
    from modules.procurement.models import Trip, TripExpense, TripItem
    if not final:
        return 0                                         # bozorlik ertalab — bugungi kam qolganlar ertangi bozorlikka
    buyer = (User.objects.filter(memberships__role__code="buyer", is_active=True).first()
             or User.objects.filter(memberships__role__code__in=["cook", "manager"], is_active=True).first())
    if buyer is None:
        return 0
    market = info.market if info and info.market_id else None
    t_obj = Trip.objects.create(buyer=buyer, date=d, market=market, advance=0, overhead_to_cost=ps.setting(t, "overhead_to_cost", True),
                                note="Kunlik bozorlik (kam qolganlar)")
    items = 0
    for i, q in lines.items():
        price = _price(i, market=market, rnd=rnd)
        TripItem.objects.create(trip=t_obj, ingredient=i, name=str(i), unit=i.unit, planned_qty=q, qty=q, price=price, total=int(q * price),
                                seller=rnd.choice(["Ahmad aka", "Dilshod", "Sobir opa", "Qator 12", "Ravshan aka", ""]))
        items += int(q * price)
    TripExpense.objects.create(trip=t_obj, kind="taxi", amount=rnd.choice([40_000, 50_000, 60_000]), note="Bozorga borish-qaytish")
    if items > 800_000:
        TripExpense.objects.create(trip=t_obj, kind="porter", amount=rnd.choice([20_000, 30_000]), note="Qoplarni ortish")
    spent = ps.trip_totals(t_obj)["spent"]
    t_obj.advance = int(spent * rnd.uniform(1.03, 1.2) / 50_000 + 1) * 50_000
    t_obj.save(update_fields=["advance"])
    bal = ps.trip_totals(t_obj)["balance"]
    ps.close_trip(t_obj, max(0, bal) - (rnd.choice([10_000, 20_000]) if rnd.random() < 0.12 else 0), tenant=t)
    _backdate_purchase(t_obj.purchase_id, _at(d, 12, 0))
    Trip.objects.filter(pk=t_obj.pk).update(closed_at=_at(d, 12, rnd.randint(0, 59)), created_at=_at(d, 6, 30))
    return 1


def _backdate_purchase(pid, at: datetime):
    if not pid:
        return
    from modules.inventory.models import Purchase, StockMovement
    p = Purchase.objects.filter(pk=pid).first()
    if p:
        Purchase.objects.filter(pk=pid).update(date=at.date())
        StockMovement.objects.filter(ref=f"Kirim #{p.number}").update(at=at)


def _payables(now: datetime):
    """Nasiya muddati kelgan qarzlarni to'lash (qarzdorlik o'sib ketmasin, lekin bir qismi qolsin)."""
    from modules.procurement.models import Order, Payment
    from modules.procurement.services import debts
    for sid, dd in debts().items():
        if Payment.objects.filter(supplier_id=sid, date=now.date()).exists():
            continue
        if dd["debt"] and dd["oldest"] and (now.date() - date.fromisoformat(dd["oldest"])).days > 10:
            o = Order.objects.filter(supplier_id=sid, status="received").order_by("received_at").first()
            if o:
                Payment.objects.create(supplier_id=sid, amount=int(dd["debt"] * 0.7) // 1000 * 1000, method="transfer", date=now.date(),
                                       note="Nasiya bo'yicha to'lov")


# ------------------------------------------------------------------ hozirgi lahza: oshxona va zal
def _now_kitchen(t, now: datetime, prof, rnd):
    from modules.kds.models import Ticket
    from modules.kds.services import create_tickets
    from modules.pos.models import Order, OrderItem, OrderStatus
    opened = list(Order.objects.filter(status=OrderStatus.OPEN).order_by("created_at"))
    # 25 daqiqadan eski ochiq buyurtmalar — to'landi (oshxona ekrani «muzlab» qolmasin)
    for o in opened:
        if now - timezone.localtime(o.created_at) > timedelta(minutes=25) or not (10 <= now.hour < 23):
            o.status, o.paid_at = OrderStatus.PAID, min(now, o.created_at + timedelta(minutes=rnd.randint(20, 35)))
            o.payment_method = o.payment_method or rnd.choices(*prof["pay"])[0] or "cash"
            o.save()
            Ticket.objects.filter(order=o).exclude(status="served").update(status="served", ready_at=o.paid_at)
            _table_close(t, o)
    if not (10 <= now.hour < 23):
        return
    live = Order.objects.filter(status=OrderStatus.OPEN).count()
    for _ in range(max(0, rnd.randint(3, 6) - live)):
        branch_id = rnd.choices(*prof["branch"])[0]
        typ = rnd.choices(["dine_in", "dine_in", "takeaway", "delivery"])[0]
        o = Order.objects.create(branch_id=branch_id, shift=_shift(branch_id, now.date()), type=typ, status=OrderStatus.OPEN,
                                 table_no=rnd.choice(prof["tables"]) if typ == "dine_in" else "",
                                 source="telegram" if typ == "delivery" else "pos")
        o.cashier = o.shift.opened_by
        for p, q in _pick_items(prof, rnd):
            OrderItem.objects.create(order=o, product=p, name=p.name.get("uz") or str(p), qty=q, price=p.price, cost=p.cost)
        o.recalc()
        o.save()
        ago = rnd.randint(1, 18)
        Order.objects.filter(pk=o.pk).update(created_at=now - timedelta(minutes=ago))
        create_tickets(o, t)
        st = "new" if ago < 5 else rnd.choice(["cooking", "cooking", "ready"])
        upd = {"status": st}
        if st != "new":
            upd["started_at"] = now - timedelta(minutes=ago - 2)
        if st == "ready":
            upd["ready_at"] = now - timedelta(minutes=1)
        Ticket.objects.filter(order=o).update(**upd)
        if typ == "dine_in" and t.module_enabled("tables"):
            from modules.tables.services import find_by_number, open_session
            table = find_by_number(o.table_no)
            if table and not table.session:
                open_session(table, order=o, waiter=o.cashier, source="pos", tenant=t, guests=rnd.randint(2, 5))


def _table_close(t, o):
    if not t.module_enabled("tables"):
        return
    from modules.tables.models import Table, TableSession
    from modules.tables.services import close_session
    s = TableSession.objects.filter(order_id=o.pk, closed_at__isnull=True).first()
    if s:
        close_session(s, tenant=t)
        Table.objects.filter(pk=s.table_id).update(needs_cleaning=False)


# ------------------------------------------------------------------ xodimlar: smena va davomat
def _people(d: date, now: datetime, rnd):
    from modules.hr.models import Attendance, Employee, ShiftPlan
    today = now.date()
    emps = list(Employee.objects.filter(is_active=True).select_related("position", "branch")) if hasattr(Employee, "is_active") else \
        list(Employee.objects.select_related("position", "branch"))
    for e in emps:
        for k in range(0, 7):                            # 1 hafta oldinga smena jadvali
            day = d + timedelta(days=k)
            if (e.pk + day.toordinal()) % 7 == 0:        # haftada 1 kun dam
                continue
            if not ShiftPlan.objects.filter(employee=e, date=day).exists():
                cashier = e.position and e.position.name == "Kassir"
                ShiftPlan.objects.create(employee=e, branch=e.branch, date=day, start=time(9, 0), end=time(23, 0) if cashier else time(18, 0))
        sp = ShiftPlan.objects.filter(employee=e, date=d).first()
        if sp is None or Attendance.objects.filter(employee=e, check_in__date=d).exists():
            continue
        start = _at(d, sp.start.hour, sp.start.minute)
        if d == today and now < start:
            continue
        r = random.Random(f"{e.pk}:{d}")
        if r.random() < 0.04:                            # kelmadi
            continue
        late = r.choice([0] * 8 + [5, 12, 25])
        cin = start + timedelta(minutes=late - r.randint(0, 6) if not late else late)
        end = _at(d, sp.end.hour, sp.end.minute)
        cout = None if (d == today and now < end) else end + timedelta(minutes=r.randint(-5, 20))
        Attendance.objects.create(employee=e, branch=sp.branch, check_in=cin, check_out=cout, late_minutes=late, source=r.choice(["panel", "telegram", "pos"]))


# ------------------------------------------------------------------ oylik: xarajat va oylik varaqlari
def _monthly(t, d: date, rnd):
    if d.day != 1 and not (d == timezone.localdate()):
        return
    first = d.replace(day=1)
    try:
        from modules.finance.models import Expense, ExpenseCategory, ensure_categories
    except Exception:
        return
    ensure_categories()
    cats = {c.code: c for c in ExpenseCategory.objects.all()}
    rows = [("rent", 30_000_000, 3, "Ijara (oylik)"), ("utilities", rnd.randint(6_500_000, 8_000_000), 10, "Svet, gaz, suv"),
            ("software", 490_000, 2, "RestoPOS obuna"), ("marketing", 2_500_000, 5, "Instagram va Telegram reklama"),
            ("packaging", 1_400_000, 8, "Olib ketish idishlari"), ("repair", rnd.choice([450_000, 900_000]), 18, "Jihoz ta'miri"),
            ("delivery", rnd.randint(1_800_000, 2_600_000), 25, "Kuryer yoqilg'isi"), ("other", 700_000, 20, "Xo'jalik mollari")]
    today = timezone.localdate()
    for code, amount, day, note in rows:
        dd = first + timedelta(days=day - 1)
        if dd <= today and code in cats and not Expense.objects.filter(category=cats[code], date__gte=first, date__lt=first + timedelta(days=32), note=note).exists():
            Expense.objects.create(date=dd, category=cats[code], amount=amount, note=note)
    # o'tgan oy uchun aylanmadan soliq (4%) — oy tugagach
    prev = (first - timedelta(days=1)).replace(day=1)
    if "tax" in cats and not Expense.objects.filter(category=cats["tax"], date__gte=first, date__lt=first + timedelta(days=32)).exists() and today.day >= 15:
        from modules.pos.models import Order
        rev = Order.objects.filter(status="paid", paid_at__date__gte=prev, paid_at__date__lt=first).aggregate(s=Sum("total"))["s"] or 0
        if rev:
            Expense.objects.create(date=first + timedelta(days=14), category=cats["tax"], amount=int(rev * 0.04), note="Aylanmadan soliq 4%")
    try:
        from modules.hr.models import Employee, Payslip
    except Exception:
        return
    for e in Employee.objects.all():
        if not Payslip.objects.filter(employee=e, period=first).exists():
            s = Payslip(employee=e, period=first, salary_type=e.salary_type, rate=e.rate, hours=160, shifts=22, sales_base=0)
            s.compute()
            s.save()


# ------------------------------------------------------------------ bron
def _bookings(now: datetime, rnd):
    try:
        from modules.reservations.models import Reservation, ReservationStatus
        from modules.tables.models import Table
    except Exception:
        return
    tables = list(Table.objects.filter(is_active=True))
    if not tables:
        return
    from modules.reservations.demo import NAMES, OCCASIONS
    # o'tgan bronlar — yakunlangan / kelmagan
    Reservation.objects.filter(starts_at__lt=now - timedelta(hours=3), status__in=[ReservationStatus.NEW, ReservationStatus.CONFIRMED]).update(status=ReservationStatus.DONE)
    for k, want in ((0, 5), (1, 4), (2, 3)):
        d = now.date() + timedelta(days=k)
        have = Reservation.objects.filter(starts_at__date=d).count()
        for j in range(max(0, want - have)):
            h = rnd.choice([12, 13, 13, 18, 19, 19, 20])
            at = _at(d, h, rnd.choice([0, 30]))
            if k == 0 and at < now:
                at = now + timedelta(hours=rnd.randint(1, 4))
                at = at.replace(minute=0 if at.minute < 30 else 30, second=0, microsecond=0)
            Reservation.objects.create(guest_name=rnd.choice(NAMES), phone=f"+99890{rnd.randint(1000000, 9999999)}", guests=rnd.choice([2, 2, 4, 4, 6, 8]),
                                       table=rnd.choice(tables), starts_at=at, duration_minutes=90,
                                       status=rnd.choice([ReservationStatus.CONFIRMED, ReservationStatus.CONFIRMED, ReservationStatus.NEW]),
                                       source=rnd.choice(["phone", "telegram", "hall"]), occasion=rnd.choice(OCCASIONS))


# ------------------------------------------------------------------ loyihalar
def _projects(now: datetime, rnd):
    try:
        from modules.projects import services as S
        from modules.projects.models import PTask, Status, TaskStatus
    except Exception:
        return
    if not cache.add(f"live:proj:{now:%Y%m%d}", 1, 86400):
        return
    for t in PTask.objects.filter(project__status=Status.ACTIVE, due__lt=now.date() - timedelta(days=1)).exclude(status=TaskStatus.DONE).select_related("project"):
        if rnd.random() < 0.6:
            S.set_task_status(t, TaskStatus.DONE, actor=t.assignee)


# ------------------------------------------------------------------ kundalik vazifalar
ISSUES = [
    ("Muzlatkich harorati +7°C — tekshirish", "equipment"), ("Kassa printerida qog'oz tugayapti", "supply"),
    ("Zalda 5-stol oyog'i qimirlayapti", "furniture"), ("Hojatxonada qog'oz sochiq yo'q", "sanitary"),
    ("Mijoz shikoyati: osh sovuq keldi", "safety"), ("Tandir o't olishi sekin", "equipment"),
    ("Yetkazib berish sumkasi yirtilgan", "supply"), ("Kechki smenaga ofitsiant yetmayapti", "staff"),
    ("Oshxona vytyajkasini tozalash", "sanitary"), ("Wi-Fi zalda uzilib qolyapti", "it"),
]


def _daily_work(t, now: datetime, rnd):
    """Har kuni: muddati o'tgan vazifalarning bir qismi bajariladi, 1–2 ta yangi muammo tushadi."""
    if "tasks" not in (t.enabled_modules or []) or not cache.add(f"live:tasks:{t.schema_name}:{now:%Y%m%d}", 1, 86400):
        return
    from core.models import User
    from modules.tasks.models import ColumnKind, Task, TaskCategory, TaskColumn
    from modules.tasks.services import create_task
    done = TaskColumn.objects.filter(kind=ColumnKind.DONE).first()
    active = TaskColumn.objects.filter(kind=ColumnKind.ACTIVE).first()
    if done is None:
        return
    op = list(Task.objects.exclude(column__kind__in=[ColumnKind.DONE, ColumnKind.CANCELLED]).order_by("due_at"))
    for tk in op:
        r = rnd.random()
        if (tk.due_at and tk.due_at < now and r < 0.6) or (tk.column.kind == ColumnKind.ACTIVE and r < 0.25):
            Task.objects.filter(pk=tk.pk).update(column=done, done_at=now.replace(hour=rnd.randint(9, max(9, min(now.hour, 20))), minute=rnd.randint(0, 59)))
        elif active and tk.column.kind == ColumnKind.BACKLOG and r < 0.3:
            Task.objects.filter(pk=tk.pk).update(column=active)
    staff = list(User.objects.filter(is_active=True, memberships__role__code__in=["manager", "cook", "waiter", "cashier"]).distinct())
    if Task.objects.filter(created_at__date=now.date(), title__in=[x[0] for x in ISSUES]).exists() or not staff:
        return

    class _Req:
        auth = None
        tenant = t
    for title, cat in rnd.sample(ISSUES, rnd.randint(1, 2)):
        create_task(_Req(), title=title, description="Xodim tomonidan qayd etilgan (jonli demo).",
                    category=TaskCategory.objects.filter(code=cat).first(), assignee=rnd.choice(staff),
                    due_at=now + timedelta(hours=rnd.choice([4, 8, 24])))


# ------------------------------------------------------------------ o'qitish: xodimlar kursni asta-sekin o'tadi
def _learning(t, now: datetime, rnd):
    if "training" not in (t.enabled_modules or []) or not cache.add(f"live:learn:{t.schema_name}:{now:%Y%m%d}", 1, 86400):
        return
    from modules.training import services as tr
    from modules.training.models import Enrollment, LessonProgress, QuizAttempt
    for e in Enrollment.objects.exclude(status="completed").select_related("course", "user"):
        if rnd.random() > 0.35:
            continue
        c, u = e.course, e.user
        done = tr.lesson_done_ids(u, c)
        nxt = next((les for les in c.lessons.order_by("sort_order", "id") if les.pk not in done), None) if hasattr(c, "lessons") else None
        if nxt is not None:
            p, _ = LessonProgress.objects.get_or_create(user=u, lesson=nxt)
            p.percent, p.completed_at, p.views = 100, now - timedelta(minutes=rnd.randint(10, 600)), p.views + 1
            p.max_position = p.last_position = p.duration = p.duration or 300
            p.watched_seconds = p.duration
            p.save()
        else:
            for q in c.quizzes.all():
                if not QuizAttempt.objects.filter(quiz=q, user=u, passed=True).exists():
                    n = max(1, q.questions.count()) if hasattr(q, "questions") else 10
                    ok = max(1, round(n * rnd.uniform(0.75, 1)))
                    QuizAttempt.objects.create(quiz=q, user=u, finished_at=now, total=n, correct_count=ok, score=round(100 * ok / n), passed=True)
        tr.recompute(c, u)
'@

Put 'backend\public\management\commands\bootstrap_dev.py' @'
"""
Dev muhitini bir buyruq bilan tayyorlash:
public sxema migratsiyasi → tariflar → 'localhost' public domeni → demo tenant 'lazzat' (lazzat.localhost).
"""
from django.core.management import call_command
from django.core.management.base import BaseCommand
from django_tenants.utils import schema_context

from public.models import Domain, Plan, Tenant
from public.services import create_tenant


class Command(BaseCommand):
    help = "Dev: migratsiya + tariflar + platforma domeni + demo tenant"

    def handle(self, *args, **options):
        call_command("migrate_schemas", "--shared", verbosity=0)
        for code, name, price, mods in [
            ("start", "Start", 199_000, ["catalog", "cms", "pos", "fiscal", "payments", "telegram", "reports"]),
            ("pro", "Pro", 490_000, ["*"]),
            ("network", "Tarmoq", 990_000, ["*"]),
        ]:
            Plan.objects.update_or_create(code=code, defaults={"name": name, "price_per_branch": price, "allowed_modules": mods, "max_branches": 1 if code == "start" else 100})

        if not Tenant.objects.filter(schema_name="public").exists():
            public = Tenant(schema_name="public", name="Platforma", slug="public", enabled_modules=[])
            public.save()
            Domain.objects.get_or_create(tenant=public, domain="localhost", defaults={"is_primary": True})
            self.stdout.write("public tenant + localhost domeni yaratildi")

        if not Tenant.objects.filter(slug="lazzat").exists():
            t = create_tenant(name="Lazzat", slug="lazzat", owner_phone="998901234567", preset="fast_food",
                              owner_name="Akmal T.", plan_code="pro", domain="lazzat.localhost")
            with schema_context(t.schema_name):
                from modules.catalog.demo import seed_demo_menu
                from modules.finance.demo import seed_demo_expenses
                from modules.hr.demo import seed_demo_hr
                from modules.inventory.demo import seed_demo_inventory
                from modules.pos.demo import seed_demo_orders
                from modules.reservations.demo import seed_demo_reservations
                from modules.tables.demo import seed_demo_tables
                from modules.tasks.demo import seed_demo_tasks
                seed_demo_menu()
                seed_demo_tasks()
                seed_demo_inventory(t)      # tex-kartalar → taom tannarxi real
                seed_demo_orders()          # 14 kunlik savdo → hisobotlar
                seed_demo_hr()              # xodimlar, smena, davomat, oylik
                from core.models import Membership
                from modules.hr.demo import seed_demo_recruit_people
                seed_demo_recruit_people(Membership.objects.filter(role__code="owner").first().user)
                seed_demo_expenses()        # ijara, kommunal, marketing
                seed_demo_tables()          # zal xaritasi: 2 zal, 14 stol
                seed_demo_reservations()    # bugungi/ertangi bronlar + navbat
                from modules.training.demo import seed_demo_training
                seed_demo_training()        # kurslar, testlar, standartlar, topshiriqlar
                from modules.crm.demo import seed_demo_crm
                seed_demo_crm(t)            # mijozlar, bonus tarixi, aksiyalar
                from modules.forecast.demo import seed_demo_forecast
                seed_demo_forecast(t)       # bayramlar + ob-havo
                from modules.ops.demo import seed_demo_ops
                seed_demo_ops(t, demo=True)            # tashkiliy tuzilma
                from modules.procurement.demo import seed_demo_procurement
                seed_demo_procurement(t)    # zakup: ta'minotchi, narx, buyurtma, bozorlik
                from modules.projects.demo import seed_demo_projects
                seed_demo_projects(t)       # loyihalar: filial ochish, menyu, ta'mir, aksiya
            from public.services import set_modules
            set_modules(t, [*t.enabled_modules, "training", "crm", "forecast", "ops", "procurement", "projects"])
            t.settings = {**(t.settings or {}), "demo_live": True}      # jonli demo: savdo va boshqalar vaqt o'tgani sari davom etadi
            t.save(update_fields=["settings"])
            self.stdout.write(self.style.SUCCESS("Demo tenant: http://lazzat.localhost:8000  (egasi: +998901234567, OTP dev rejimida javobda qaytadi)"))
        call_command("seed_hq", "--demo", verbosity=0)   # RESTROOS HQ: http://localhost:8000/hq/ (+998901234567)
        self.stdout.write(self.style.SUCCESS("HQ: http://localhost:8000/hq/  (+998901234567)"))
        self.stdout.write(self.style.SUCCESS("Tayyor."))
'@

Put 'backend\public\management\commands\demo_live.py' @'
"""
Jonli demo — namuna restoranlarda savdo, ombor, zakup, davomat, bron… vaqt o'tgani sari o'zi davom etadi.
    python manage.py demo_live --slug namuna --on     (yoqish + hozirgacha to'ldirish)
    python manage.py demo_live --slug namuna          (faqat hozirgacha to'ldirish)
    python manage.py demo_live --slug namuna --off    (o'chirish)
    python manage.py demo_live --all --on             (hamma demo restoranlar: lazzat, namuna)
Haqiqiy mijoz restoranida YOQMANG — u yerga soxta cheklar qo'shiladi.
"""
from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from django_tenants.utils import schema_context

DEMO_SLUGS = ("lazzat", "namuna")


class Command(BaseCommand):
    help = "Jonli demo: yoqish/o'chirish va bo'shliqni to'ldirish"

    def add_arguments(self, parser):
        parser.add_argument("--slug", default="")
        parser.add_argument("--all", action="store_true", help="lazzat va namuna")
        parser.add_argument("--on", action="store_true")
        parser.add_argument("--off", action="store_true")

    def handle(self, *args, **o):
        from public.live import KEY, tick
        from public.models import Tenant
        slugs = list(DEMO_SLUGS) if o["all"] else [o["slug"]] if o["slug"] else []
        if not slugs:
            raise CommandError("--slug NOM yoki --all kerak")
        for t in Tenant.objects.filter(slug__in=slugs):
            if o["on"] or o["off"]:
                t.settings = {**(t.settings or {}), KEY: bool(o["on"])}
                t.save(update_fields=["settings"])
            with schema_context(t.schema_name):
                connection.set_tenant(t)
                r = tick(t, force=True) if not o["off"] else {}
            state = "yoqilgan" if (t.settings or {}).get(KEY) else "o'chiq"
            self.stdout.write(f"{t.slug}: jonli demo {state}" + (f" · yangi cheklar: {r.get('orders', 0)}, zakup: {r.get('restock', 0)}" if r else ""))
        self.stdout.write(self.style.SUCCESS("Tayyor."))
'@

Put 'backend\public\showcase.py' @'
"""
Namuna restoran «Navro'z milliy taomlar» — barcha imkoniyatlarni ko'rsatish va sinash uchun to'liq soxta baza.

Hamma ma'lumot to'qima (ismlar, telefonlar, mijozlar). Narxlar esa haqiqatga yaqin — 2026-yil Toshkent:
  • bozor narxlari (pul24.uz, 2026-06-01): mol go'shti 75–106 ming, qo'y 90–130 ming, guruch 12 mingdan, pomidor ≤13 ming…
  • osh markazlarida 1 porsiya osh Toshkentda 30 200 so'm (uz24.uz, 2024) → 2026-yil o'rta restoranda 42–60 ming
  • somsa, lag'mon, kabob — hostella.uz (2026) va o'rta toifadagi restoran menyulari darajasida
Tannarx tex-kartalardan hisoblanadi (food cost ≈ 28–38%).

Ishga tushirish:  python manage.py seed_showcase          → http://namuna.localhost:8000
                  python manage.py seed_showcase --reset  → o'chirib, qaytadan yaratadi
"""
from __future__ import annotations

import random
from datetime import timedelta
from decimal import Decimal

from django.db import connection
from django.db.models import F
from django.utils import timezone
from django_tenants.utils import schema_context

SLUG = "namuna"
NAME = "Navro'z milliy taomlar"
OWNER_PHONE = "+998901234567"          # demo egasi (Lazzat bilan bir xil — eslab qolish oson)
EXTRA_OWNERS = [("+998888203830", "Nizomiddin")]   # loyiha egasi o'z raqami bilan ham kira oladi

# ------------------------------------------------------------------ taomnoma
CATS = [("Osh", "Плов", "Plov"), ("Sho'rvalar", "Супы", "Soups"), ("Issiq taomlar", "Горячие блюда", "Main dishes"),
        ("Kaboblar", "Шашлыки", "Kebabs"), ("Somsa va non", "Самса и хлеб", "Samsa & bread"), ("Salatlar", "Салаты", "Salads"),
        ("Shirinliklar", "Десерты", "Desserts"), ("Ichimliklar", "Напитки", "Drinks")]

# (kategoriya, nomi uz, nomi ru, tavsif, narx, vazn g, kkal, teglar, modifikator guruhlari)
MENU = [
    ("Osh", "To'y oshi", "Свадебный плов", "Devzira guruch, mol go'shti, sariq sabzi, no'xat va mayiz bilan", 48000, 400, 780, ["hit"], ["porsiya"]),
    ("Osh", "Choyxona oshi", "Чайханский плов", "Qo'y go'shti va dumba yog'ida, ko'p sabzili", 42000, 380, 820, [], ["porsiya"]),
    ("Osh", "Samarqand oshi", "Самаркандский плов", "Qatlam-qatlam, go'sht ustida, sabzi alohida qovurilgan", 45000, 400, 760, [], ["porsiya"]),
    ("Osh", "Qazili osh", "Плов с казы", "To'y oshi + uy qazisi va bedana tuxumi", 62000, 450, 950, ["new"], ["porsiya"]),
    ("Sho'rvalar", "Sho'rva", "Шурпа", "Qo'y go'shti, kartoshka, sabzi va ko'katlar bilan", 38000, 450, 420, [], []),
    ("Sho'rvalar", "Mastava", "Мастава", "Guruchli sho'rva, suzma bilan", 30000, 400, 380, [], []),
    ("Sho'rvalar", "Chuchvara sho'rva", "Суп с чучварой", "Qo'lda tugilgan chuchvara, qatiq bilan", 32000, 400, 410, [], []),
    ("Sho'rvalar", "Mosh xo'rda", "Маш-кхурда", "Mosh, guruch va go'sht — uy taomi", 28000, 400, 360, [], []),
    ("Issiq taomlar", "Qovurma lag'mon", "Жареный лагман", "Qo'lda cho'zilgan xamir, mol go'shti va sabzavot", 40000, 380, 690, ["hit"], ["achchiqlik"]),
    ("Issiq taomlar", "Suyuq lag'mon", "Лагман", "Go'shtli sabzavotli sho'rva va cho'zma xamir", 35000, 450, 540, [], ["achchiqlik"]),
    ("Issiq taomlar", "Manti (5 dona)", "Манты (5 шт)", "Qo'y go'shti va piyoz, bug'da pishirilgan", 36000, 300, 620, [], []),
    ("Issiq taomlar", "Dimlama", "Димлама", "Go'sht va sabzavotlar o'z sharbatida dimlangan", 45000, 450, 560, [], []),
    ("Issiq taomlar", "Qozon kabob", "Казан-кабоб", "Qo'y go'shti va kartoshka qozonda qovurilgan", 69000, 450, 980, ["hit"], []),
    ("Issiq taomlar", "Norin", "Нарын", "Mayda to'g'ralgan xamir va qazi, sovuq holda", 38000, 300, 540, [], []),
    ("Kaboblar", "Qo'y go'shti kabob", "Шашлык из баранины", "1 six, piyoz va non bilan", 28000, 160, 420, ["hit"], ["garnir"]),
    ("Kaboblar", "Mol go'shti kabob", "Шашлык из говядины", "1 six", 26000, 160, 380, [], ["garnir"]),
    ("Kaboblar", "Jigar kabob", "Шашлык из печени", "1 six, dumba bilan", 22000, 150, 350, [], ["garnir"]),
    ("Kaboblar", "Lula kabob", "Люля-кебаб", "Qiyma, ziravorlar bilan", 26000, 150, 390, [], ["garnir"]),
    ("Kaboblar", "Tovuq kabob", "Шашлык из курицы", "1 six, marinadlangan", 20000, 170, 290, [], ["garnir"]),
    ("Somsa va non", "Tandir somsa", "Самса тандырная", "Qo'y go'shti va dumba", 13000, 150, 380, ["hit"], []),
    ("Somsa va non", "Qovoqli somsa", "Самса с тыквой", "Mavsumiy, yengil", 9000, 150, 260, [], []),
    ("Somsa va non", "Obi non", "Лепёшка", "Tandirda yopilgan", 5000, 400, 900, [], []),
    ("Somsa va non", "Patir non", "Патыр", "Qatlamli, sutli", 9000, 350, 1050, [], []),
    ("Salatlar", "Achchiq-chuchuk", "Ачик-чучук", "Pomidor, piyoz, achchiq qalampir", 15000, 250, 70, [], []),
    ("Salatlar", "Toshkent salati", "Салат «Ташкент»", "Ko'k turp, mol go'shti, tuxum", 32000, 250, 380, [], []),
    ("Salatlar", "Suzma ko'katlar bilan", "Сюзьма с зеленью", "Uy suzmasi", 14000, 200, 240, [], []),
    ("Salatlar", "Olivye", "Оливье", "Tovuq go'shti bilan", 26000, 250, 420, [], []),
    ("Salatlar", "Ko'k salat", "Зелёный салат", "Bodring, pomidor, ko'katlar", 18000, 250, 90, ["veg"], []),
    ("Shirinliklar", "Chak-chak", "Чак-чак", "Asal bilan", 18000, 150, 520, [], []),
    ("Shirinliklar", "Halvo", "Халва", "Uy halvosi", 20000, 120, 560, [], []),
    ("Ichimliklar", "Ko'k choy (choynak)", "Зелёный чай (чайник)", "", 8000, 800, 0, [], []),
    ("Ichimliklar", "Qora choy (choynak)", "Чёрный чай (чайник)", "", 8000, 800, 0, [], []),
    ("Ichimliklar", "Limonli choy", "Чай с лимоном", "Limon va asal", 15000, 800, 60, [], []),
    ("Ichimliklar", "Kompot (1 l)", "Компот (1 л)", "Quritilgan mevalardan", 20000, 1000, 240, [], []),
    ("Ichimliklar", "Ayron", "Айран", "Uy ayroni, 0,4 l", 12000, 400, 120, [], []),
    ("Ichimliklar", "Coca-Cola 0,5", "Coca-Cola 0,5", "", 12000, 500, 210, [], []),
    ("Ichimliklar", "Suv 0,5", "Вода 0,5", "Gazsiz", 5000, 500, 0, [], []),
]

# ------------------------------------------------------------------ xomashyo (nom, kategoriya, birlik, narx, min qoldiq, boshlang'ich kirim)
ING = [
    ("Mol go'shti", "Go'sht", "kg", 95000, 10, 45), ("Qo'y go'shti", "Go'sht", "kg", 115000, 8, 40),
    ("Dumba", "Go'sht", "kg", 85000, 3, 10), ("Tovuq go'shti", "Go'sht", "kg", 45000, 5, 20),
    ("Mol jigari", "Go'sht", "kg", 60000, 2, 6), ("Qazi", "Go'sht", "kg", 180000, 3, 2),
    ("Guruch (devzira)", "Don", "kg", 28000, 20, 80), ("Un", "Don", "kg", 6500, 25, 100),
    ("No'xat", "Don", "kg", 18000, 3, 10), ("Mosh", "Don", "kg", 20000, 2, 8), ("Mayiz", "Quruq", "kg", 40000, 2, 5),
    ("Sariq sabzi", "Sabzavot", "kg", 6000, 20, 90), ("Piyoz", "Sabzavot", "kg", 5000, 15, 60),
    ("Kartoshka", "Sabzavot", "kg", 5000, 20, 60), ("Pomidor", "Sabzavot", "kg", 12000, 8, 25),
    ("Bodring", "Sabzavot", "kg", 10000, 5, 15), ("Bolgar qalampir", "Sabzavot", "kg", 12000, 3, 10),
    ("Karam", "Sabzavot", "kg", 4000, 5, 15), ("Qovoq", "Sabzavot", "kg", 5000, 5, 15), ("Ko'k turp", "Sabzavot", "kg", 6000, 3, 8),
    ("Sarimsoq", "Sabzavot", "kg", 25000, 2, 4), ("Ko'katlar", "Sabzavot", "kg", 20000, 1, 3), ("Limon", "Meva", "kg", 50000, 2, 1),
    ("Paxta yog'i", "Yog'", "l", 24000, 20, 60), ("Tuxum", "Sut", "dona", 1500, 60, 300), ("Suzma", "Sut", "kg", 35000, 3, 12),
    ("Mayonez", "Sous", "kg", 30000, 2, 6), ("Ziravorlar", "Quruq", "kg", 60000, 1, 3), ("Tuz", "Quruq", "kg", 3000, 3, 10),
    ("Shakar", "Quruq", "kg", 12000, 5, 15), ("Asal", "Quruq", "kg", 90000, 1, 3),
    ("Ko'k choy", "Choy", "kg", 90000, 1, 3), ("Qora choy", "Choy", "kg", 80000, 1, 3), ("Quritilgan meva", "Quruq", "kg", 45000, 2, 6),
    ("Obi non (tayyor)", "Non", "dona", 3000, 40, 120), ("Patir (tayyor)", "Non", "dona", 5500, 20, 40),
    ("Chak-chak (tayyor)", "Shirinlik", "kg", 60000, 2, 4), ("Halvo (tayyor)", "Shirinlik", "kg", 70000, 2, 3),
    ("Coca-Cola 0,5", "Ichimlik", "dona", 7500, 24, 96), ("Suv 0,5", "Ichimlik", "dona", 2500, 24, 96),
]

# taom → [(xomashyo, miqdor: g / ml / dona, chiqindi %)]
RECIPES = {
    "To'y oshi": [("Guruch (devzira)", 150, 0), ("Mol go'shti", 90, 8), ("Sariq sabzi", 120, 10), ("Piyoz", 40, 10), ("Paxta yog'i", 45, 0),
                  ("No'xat", 15, 0), ("Mayiz", 8, 0), ("Sarimsoq", 10, 5), ("Ziravorlar", 3, 0), ("Tuz", 3, 0)],
    "Choyxona oshi": [("Guruch (devzira)", 150, 0), ("Qo'y go'shti", 70, 8), ("Dumba", 20, 0), ("Sariq sabzi", 150, 10), ("Piyoz", 40, 10),
                      ("Paxta yog'i", 30, 0), ("Ziravorlar", 3, 0), ("Tuz", 3, 0)],
    "Samarqand oshi": [("Guruch (devzira)", 150, 0), ("Mol go'shti", 100, 8), ("Sariq sabzi", 120, 10), ("Piyoz", 40, 10), ("Paxta yog'i", 40, 0),
                       ("No'xat", 15, 0), ("Ziravorlar", 3, 0), ("Tuz", 3, 0)],
    "Qazili osh": [("Guruch (devzira)", 150, 0), ("Mol go'shti", 80, 8), ("Qazi", 50, 0), ("Sariq sabzi", 120, 10), ("Piyoz", 40, 10),
                   ("Paxta yog'i", 45, 0), ("No'xat", 15, 0), ("Tuxum", 1, 0), ("Ziravorlar", 3, 0)],
    "Sho'rva": [("Qo'y go'shti", 90, 10), ("Kartoshka", 120, 15), ("Sariq sabzi", 60, 10), ("Piyoz", 40, 10), ("Pomidor", 40, 5),
                ("Bolgar qalampir", 20, 10), ("Ko'katlar", 5, 0), ("Ziravorlar", 2, 0)],
    "Mastava": [("Guruch (devzira)", 50, 0), ("Mol go'shti", 60, 8), ("Kartoshka", 60, 15), ("Sariq sabzi", 50, 10), ("Piyoz", 30, 10),
                ("Pomidor", 30, 5), ("Paxta yog'i", 15, 0), ("Suzma", 30, 0)],
    "Chuchvara sho'rva": [("Un", 80, 0), ("Mol go'shti", 70, 8), ("Piyoz", 40, 10), ("Suzma", 30, 0), ("Ko'katlar", 5, 0)],
    "Mosh xo'rda": [("Mosh", 60, 0), ("Guruch (devzira)", 40, 0), ("Mol go'shti", 50, 8), ("Piyoz", 30, 10), ("Paxta yog'i", 15, 0), ("Suzma", 30, 0)],
    "Qovurma lag'mon": [("Un", 150, 0), ("Tuxum", 1, 0), ("Mol go'shti", 90, 8), ("Bolgar qalampir", 40, 10), ("Pomidor", 50, 5),
                        ("Piyoz", 40, 10), ("Sarimsoq", 5, 5), ("Paxta yog'i", 30, 0)],
    "Suyuq lag'mon": [("Un", 130, 0), ("Mol go'shti", 80, 8), ("Kartoshka", 60, 15), ("Bolgar qalampir", 30, 10), ("Pomidor", 40, 5), ("Piyoz", 30, 10)],
    "Manti (5 dona)": [("Un", 120, 0), ("Qo'y go'shti", 90, 8), ("Dumba", 20, 0), ("Piyoz", 100, 10), ("Ziravorlar", 2, 0)],
    "Dimlama": [("Mol go'shti", 110, 8), ("Kartoshka", 150, 15), ("Sariq sabzi", 80, 10), ("Karam", 100, 10), ("Pomidor", 60, 5),
                ("Bolgar qalampir", 40, 10), ("Piyoz", 50, 10)],
    "Qozon kabob": [("Qo'y go'shti", 170, 10), ("Kartoshka", 200, 15), ("Paxta yog'i", 40, 0), ("Piyoz", 40, 10), ("Ziravorlar", 3, 0)],
    "Norin": [("Un", 100, 0), ("Qazi", 40, 0), ("Mol go'shti", 30, 5), ("Piyoz", 30, 10)],
    "Qo'y go'shti kabob": [("Qo'y go'shti", 75, 5), ("Dumba", 15, 0), ("Piyoz", 30, 10), ("Ziravorlar", 1, 0)],
    "Mol go'shti kabob": [("Mol go'shti", 80, 5), ("Piyoz", 30, 10), ("Ziravorlar", 1, 0)],
    "Jigar kabob": [("Mol jigari", 90, 5), ("Dumba", 15, 0), ("Piyoz", 30, 10)],
    "Lula kabob": [("Mol go'shti", 40, 5), ("Qo'y go'shti", 35, 5), ("Dumba", 10, 0), ("Piyoz", 30, 10), ("Ziravorlar", 2, 0)],
    "Tovuq kabob": [("Tovuq go'shti", 120, 10), ("Paxta yog'i", 10, 0), ("Ziravorlar", 2, 0)],
    "Tandir somsa": [("Un", 70, 0), ("Qo'y go'shti", 30, 5), ("Dumba", 10, 0), ("Piyoz", 40, 10)],
    "Qovoqli somsa": [("Un", 70, 0), ("Qovoq", 100, 15), ("Piyoz", 20, 10), ("Dumba", 10, 0)],
    "Obi non": [("Obi non (tayyor)", 1, 0)],
    "Patir non": [("Patir (tayyor)", 1, 0)],
    "Achchiq-chuchuk": [("Pomidor", 150, 5), ("Piyoz", 40, 10), ("Ko'katlar", 3, 0)],
    "Toshkent salati": [("Mol go'shti", 60, 8), ("Ko'k turp", 100, 15), ("Tuxum", 1, 0), ("Mayonez", 30, 0), ("Ko'katlar", 5, 0)],
    "Suzma ko'katlar bilan": [("Suzma", 150, 0), ("Ko'katlar", 5, 0)],
    "Olivye": [("Kartoshka", 60, 15), ("Tovuq go'shti", 50, 10), ("Tuxum", 1, 0), ("Bodring", 30, 5), ("Mayonez", 40, 0)],
    "Ko'k salat": [("Bodring", 100, 5), ("Pomidor", 80, 5), ("Ko'katlar", 10, 0), ("Paxta yog'i", 10, 0)],
    "Chak-chak": [("Chak-chak (tayyor)", 150, 0)],
    "Halvo": [("Halvo (tayyor)", 120, 0)],
    "Ko'k choy (choynak)": [("Ko'k choy", 8, 0)],
    "Qora choy (choynak)": [("Qora choy", 8, 0)],
    "Limonli choy": [("Qora choy", 8, 0), ("Limon", 40, 10), ("Asal", 20, 0)],
    "Kompot (1 l)": [("Quritilgan meva", 150, 0), ("Shakar", 60, 0)],
    "Ayron": [("Suzma", 120, 0), ("Tuz", 2, 0)],
    "Coca-Cola 0,5": [("Coca-Cola 0,5", 1, 0)],
    "Suv 0,5": [("Suv 0,5", 1, 0)],
}

# xodimlar: vazifalar demosi ro'yxati (+ zal va oshxona uchun qo'shimchalar)
EXTRA_STAFF = [("+998901110011", "Bobur Rahmonov", "waiter"), ("+998901110012", "Shahzoda Umarova", "waiter"),
               ("+998901110013", "Otabek Nurmatov", "waiter"), ("+998901110014", "Ravshan Hakimov", "cook"),
               ("+998901110015", "Farhod Tursunov", "cook"), ("+998901110016", "Elyor Qosimov", "courier")]

# Taom rasmlari — Wikimedia Commons (erkin litsenziya: CC BY-SA / CC BY / PD; muallif — fayl sahifasida).
# Rasm bazaga yuklanmaydi, havola saqlanadi; havola ochilmasa kassa va sayt bosh harfni ko'rsatadi.
COMMONS = "https://commons.wikimedia.org/wiki/Special:FilePath/{}?width=640"
PHOTOS = {
    "To'y oshi": "Plov_Tashkent.jpg",
    "Choyxona oshi": "Uzbek_palov_in_Yerevan_Food_Court.jpg",
    "Samarqand oshi": "Samarkand_Zigir-pilaf.jpg",
    "Qazili osh": "Plov_Tashkent.jpg",
    "Sho'rva": "Shorpo.jpg",
    "Mastava": "Мастава.jpg",
    "Chuchvara sho'rva": "Chuchvara.jpg",
    "Mosh xo'rda": "Мастава.jpg",
    "Qovurma lag'mon": "Лагман.jpg",
    "Suyuq lag'mon": "Uyghur_Lagman.jpg",
    "Manti (5 dona)": "Uzbek_Manti_(bright).jpg",
    "Dimlama": "Dimlama_(16425713838).jpg",
    "Qozon kabob": "Qozon_kabob_(Uzbek_national_cuisine).jpg",
    "Norin": "Naryn_tashkent_2024.jpg",
    "Qo'y go'shti kabob": "Barbecued_lamb_sticks.jpg",
    "Mol go'shti kabob": "Shashlik.jpg",
    "Jigar kabob": "Shashlik.jpg",
    "Lula kabob": "Lula_kebab.jpg",
    "Tovuq kabob": "Shashlik.jpg",
    "Tandir somsa": "Ouzbékistan-Samsas.jpg",
    "Qovoqli somsa": "Самса.jpg",
    "Obi non": "Samarqand_noni.jpg",
    "Patir non": "Патир-нон-02.jpg",
    "Achchiq-chuchuk": "سالاد_شیرازی.jpg",
    "Suzma ko'katlar bilan": "Turkish_strained_yogurt.jpg",
    "Olivye": "Салат_Оливье_03.jpg",
    "Ko'k salat": "سالاد_شیرازی.jpg",
    "Chak-chak": "Чак-чак.jpg",
    "Halvo": "Orient_sweets_(special_halva)_Samarkand,_Siyab.jpg",
    "Ko'k choy (choynak)": "Green_Tea.jpg",
    "Qora choy (choynak)": "Cup_of_black_tea.jpg",
    "Limonli choy": "Russiantea1.jpg",
    "Kompot (1 l)": "Peach_kompot.jpg",
    "Ayron": "Fresh_ayran.jpg",
    "Coca-Cola 0,5": "6_Coca-Cola_bottles.jpg",
    "Suv 0,5": "PET_Bottle_Water.jpg",
}

# O'qitish videolari (YouTube, ochiq): dars nomi → havola
VIDEOS = {
    "Zirvak": "https://www.youtube.com/watch?v=nPCynUmy-uA",
    "Guruch solish va damlash": "https://www.youtube.com/watch?v=CEXa3aEiTJU",
    "Forma va tashqi ko'rinish": "https://www.youtube.com/watch?v=FOM3SUFY030",
    "Mahsulotlarni saqlash": "https://www.youtube.com/watch?v=wxFj4_TBjeg",
    "Kutib olish": "https://www.youtube.com/watch?v=jBe8e69ypcc",
    "Shikoyat bilan ishlash": "https://www.youtube.com/watch?v=zrnL0FUYz4M",
    "Pichoq bilan xavfsiz ishlash": "https://www.youtube.com/watch?v=oLTaMPjAgLo",
    "O't o'chirgich (PASS usuli)": "https://www.youtube.com/watch?v=heVKavoFhKA",
}
LESSON_LINKS = {
    "Qo'lni to'g'ri yuvish": [("JSST: qo'l yuvish plakati (PDF)", "https://www.who.int/docs/default-source/patient-safety/how-to-handwash-poster.pdf")],
}
SAFETY_COURSE = {
    "title": "Oshxona xavfsizligi", "category": "Xavfsizlik", "roles": ["cook", "manager"], "due_days": 14,
    "description": "Pichoq, olov va issiq idish bilan xavfsiz ishlash — jarohatsiz smena.",
    "lessons": [
        ("Pichoq bilan xavfsiz ishlash", "Pichoq o'tkir bo'lsin, taxta sirpanmasin (ostiga nam sochiq), barmoqlar «mushuk panjasi» holatida.",
         ["O'tkir pichoq — xavfsizroq", "Taxta ostida nam sochiq", "«Mushuk panjasi»"]),
        ("O't o'chirgich (PASS usuli)", "P — chekani torting, A — shlangni olov tagiga qarating, S — bosing, S — u yoqdan-bu yoqqa suring. Yog' yonsa — suv sepilmaydi!",
         ["PASS", "Yog'ga suv sepilmaydi", "O't o'chirgich joyi — eshik yonida"]),
    ],
    "quiz": ("Xavfsizlik testi", 120, [
        ("Qozondagi yog' yonib ketsa nima qilinadi?", ["Suv sepiladi", "Qopqoq yopiladi / o't o'chirgich", "Qochiladi", "Pufiladi"], 1, "Yog'ga suv — portlashga olib keladi."),
        ("PASS da birinchi harakat?", ["Bosish", "Chekani tortish", "Surish", "Qaratish"], 1, "Avval chekani torting."),
        ("Qaysi pichoq xavfsizroq?", ["O'tmas", "O'tkir", "Farqi yo'q", "Plastik"], 1, "O'tmas pichoq sirpanadi — jarohat ko'proq."),
    ]),
}

OSH_COURSE = {
    "title": "Osh tayyorlash standarti", "category": "Oshxona", "roles": ["cook", "manager"], "due_days": 7,
    "description": "Zirvakdan damlashgacha — har qozon bir xil ta'm, rang va porsiyada bo'lishi uchun.",
    "lessons": [
        ("Mahsulot tanlash va tayyorlash", "Devzira guruch 1 soat oldin ivitiladi, sabzi somoncha to'g'raladi (3–4 mm), go'sht 50–60 g bo'laklarga bo'linadi.",
         ["Guruch — 1 soat ivitish", "Sabzi — somoncha 3–4 mm", "Go'sht — 50–60 g bo'lak"]),
        ("Zirvak", "Yog' tutun chiqquncha qizdiriladi, piyoz tillarang bo'lguncha, keyin go'sht va sabzi. Zirvak 40 daqiqa qaynaydi.",
         ["Yog' harorati", "Piyoz — tillarang", "Zirvak — 40 daqiqa"]),
        ("Guruch solish va damlash", "Guruch tekis yoyiladi, suv 1,5 barmoq ustida. Suv singgach — tepasi to'planadi, 25 daqiqa dam.",
         ["Suv — 1,5 barmoq", "Olov pasaytiriladi", "Dam — 25 daqiqa"]),
        ("Porsiya va berish", "Porsiya: 150 g guruch, 90 g go'sht, sabzi ustida. Lagan issiq bo'lishi shart, achchiq-chuchuk bilan.",
         ["Tarozida porsiya", "Issiq lagan", "Salat bilan"]),
    ],
    "quiz": ("Osh standarti — yakuniy test", 240, [
        ("Devzira guruch necha vaqt ivitiladi?", ["10 daqiqa", "1 soat", "1 kun", "Ivitilmaydi"], 1, "1 soat — guruch bir tekis pishadi."),
        ("Zirvak necha daqiqa qaynaydi?", ["5", "15", "40", "90"], 2, "40 daqiqa — go'sht yumshaydi, sabzi shirasini beradi."),
        ("Suv guruch ustida qancha bo'ladi?", ["Guruch bilan barobar", "1,5 barmoq", "5 barmoq", "Suv qo'yilmaydi"], 1, "1,5 barmoq — ortiqcha bo'lsa osh bo'tqa bo'ladi."),
        ("Bir porsiyada qancha go'sht bo'ladi?", ["30 g", "90 g", "200 g", "Ko'z bilan"], 1, "Standart — 90 g, tarozida."),
        ("Osh qanday idishda beriladi?", ["Sovuq likopchada", "Issiq laganda", "Qog'ozda", "Farqi yo'q"], 1, "Issiq lagan — osh sovib qolmaydi."),
    ]),
}


# ------------------------------------------------------------------ yordamchilar
def _tenant_exists():
    from public.models import Tenant
    return Tenant.objects.filter(slug=SLUG).first()


def drop() -> bool:
    """Namuna restoranni butunlay o'chiradi (sxema bilan). Faqat shu namunaga tegadi."""
    from public.models import Domain, Tenant
    t = Tenant.objects.filter(slug=SLUG).first()
    if t is None:
        return False
    schema = t.schema_name
    Domain.objects.filter(tenant=t).delete()
    Tenant.objects.filter(pk=t.pk).delete()
    with connection.cursor() as c:
        c.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
    return True


def build(domain: str = "namuna.localhost", log=print):
    from public.services import create_tenant, set_modules
    if _tenant_exists():
        raise RuntimeError("Namuna restoran allaqachon bor. Qaytadan yaratish uchun: --reset")
    t = create_tenant(name=NAME, slug=SLUG, owner_phone=OWNER_PHONE, preset="restaurant", owner_name="Bahodir Qodirov",
                      plan_code="pro", domain=domain, branch_name="Chilonzor filiali", trial_days=30)
    set_modules(t, [*t.enabled_modules, "training", "crm", "forecast", "ops", "procurement", "projects"])
    t.settings = {**(t.settings or {}), "demo_live": True}          # jonli demo (public/live.py)
    t.save(update_fields=["settings"])
    log(f"Restoran yaratildi: {t.name} ({domain})")
    with schema_context(t.schema_name):
        connection.set_tenant(t)
        _staff(t, log)
        _menu(t, log)
        _inventory(t, log)
        _operations(t, log)
        _training(t, log)
        _crm_and_telegram(t, log)
        _site(t, log)
        _kitchen_now(t, log)
    connection.set_schema_to_public()
    return t


def _staff(t, log):
    from core.models import Membership, Role, User
    from modules.tasks.demo import STAFF
    roles = {r.code: r for r in Role.objects.all()}
    for phone, name in EXTRA_OWNERS:
        u, _ = User.objects.get_or_create(phone=phone, defaults={"full_name": name})
        Membership.objects.get_or_create(user=u, role=roles["owner"])
    n = 0
    for phone, name, code in [*STAFF, *EXTRA_STAFF]:
        u, _ = User.objects.get_or_create(phone=phone, defaults={"full_name": name})
        Membership.objects.get_or_create(user=u, role=roles[code])
        n += 1
    log(f"Xodimlar: {n}")


def _menu(t, log):
    from modules.catalog import services as cat_services
    from modules.catalog.models import Category, Modifier, ModifierGroup, Product
    cats = {}
    for i, (uz, ru, en) in enumerate(CATS):
        cats[uz] = Category.objects.create(name={"uz": uz, "ru": ru, "en": en}, sort_order=i)
    groups = {}
    g = ModifierGroup.objects.create(name={"uz": "Porsiya", "ru": "Порция", "en": "Portion"}, min_select=1, max_select=1)
    for j, (n, ru, p) in enumerate([("To'liq", "Полная", 0), ("Yarim", "Половина", -12000), ("Katta (1,5)", "Большая", 18000)]):
        Modifier.objects.create(group=g, name={"uz": n, "ru": ru, "en": n}, price=p, is_default=(j == 0), sort_order=j)
    groups["porsiya"] = g
    g = ModifierGroup.objects.create(name={"uz": "Achchiqlik", "ru": "Острота", "en": "Spiciness"}, min_select=1, max_select=1)
    for j, n in enumerate(["Oddiy", "O'rtacha", "Achchiq"]):
        Modifier.objects.create(group=g, name={"uz": n, "ru": n, "en": n}, price=0, is_default=(j == 0), sort_order=j)
    groups["achchiqlik"] = g
    g = ModifierGroup.objects.create(name={"uz": "Garnir", "ru": "Гарнир", "en": "Side"}, min_select=0, max_select=2)
    for j, (n, ru, p) in enumerate([("Marinadlangan piyoz", "Маринованный лук", 0), ("Non", "Лепёшка", 5000), ("Achchiq sous", "Острый соус", 3000)]):
        Modifier.objects.create(group=g, name={"uz": n, "ru": ru, "en": n}, price=p, sort_order=j)
    groups["garnir"] = g
    for i, (cat, uz, ru, desc, price, w, kcal, tags, gcodes) in enumerate(MENU):
        p = Product.objects.create(category=cats[cat], name={"uz": uz, "ru": ru, "en": uz}, description={"uz": desc, "ru": desc, "en": desc},
                                   price=price, weight_g=w, kcal=kcal, tags=tags, sort_order=i)
        p.modifier_groups.set([groups[c] for c in gcodes])
        if uz in PHOTOS:
            Product.objects.filter(pk=p.pk).update(image_url=COMMONS.format(PHOTOS[uz]),
                                                   custom_data={"image_credit": "Wikimedia Commons (erkin litsenziya)"})
    Product.objects.filter(name__uz="Norin").update(in_stop_list=True)      # stop-list namunasi
    cat_services.publish(by="namuna", note="Boshlang'ich taomnoma", tenant=t)
    log(f"Taomnoma: {len(MENU)} taom, {len(CATS)} bo'lim")


def _inventory(t, log):
    from modules.catalog.models import Product
    from modules.inventory.models import Ingredient, Recipe, RecipeLine, Supplier
    from modules.inventory.services import create_purchase, recompute_all
    sups = {k: Supplier.objects.create(name=n, phone=ph) for k, n, ph in [
        ("go'sht", "Go'sht ulgurji (Chorsu bozori)", "+998901230001"), ("don", "Guruch va un ulgurji savdo", "+998901230002"),
        ("sabzavot", "Sabzavot va ko'kat (Parkent bozori)", "+998901230003"), ("ichimlik", "Ichimliklar distribyutori", "+998901230004")]}
    sup_of = {"Go'sht": "go'sht", "Don": "don", "Quruq": "don", "Choy": "don", "Yog'": "don", "Ichimlik": "ichimlik", "Non": "sabzavot"}
    ings = {}
    for name, cat, unit, price, mn, _ in ING:
        ings[name] = Ingredient.objects.create(name={"uz": name, "ru": name, "en": name}, category=cat, unit=unit, price=0,
                                               min_stock=mn, supplier=sups[sup_of.get(cat, "sabzavot")])
    today = timezone.localdate()
    # 4 hafta kirimlari: har hafta bozorlik, narxlar biroz o'zgaradi (tarix grafik bo'sh bo'lmasin)
    rnd = random.Random(21)
    for wk in (21, 14, 7, 0):
        for key, sup in sups.items():
            lines = [{"ingredient_id": ings[n].pk, "qty": round(q / 4 if wk else q, 2),
                      "unit_price": int(price * (1 + rnd.uniform(-0.06, 0.06)))}
                     for n, cat, unit, price, mn, q in ING if sup_of.get(cat, "sabzavot") == key]
            if lines:
                create_purchase(lines=lines, supplier=sup, date=today - timedelta(days=wk), note=f"Haftalik bozorlik ({sup.name})", tenant=t)
    # kam qolgan xomashyo (ogohlantirish namunasi)
    for n, left in [("Qazi", Decimal("1.2")), ("Limon", Decimal("0.4")), ("Mayonez", Decimal("1.0"))]:
        Ingredient.objects.filter(pk=ings[n].pk).update(stock=left)
    for pname, lines in RECIPES.items():
        p = Product.objects.get(name__uz=pname)
        r = Recipe.objects.create(product=p)
        for i, (iname, qty, waste) in enumerate(lines):
            RecipeLine.objects.create(recipe=r, ingredient=ings[iname], qty=Decimal(qty), waste_percent=Decimal(waste), sort_order=i)
    recompute_all(t)
    log(f"Ombor: {len(ING)} xomashyo, {len(RECIPES)} tex-karta, 4 hafta kirim")


def _operations(t, log):
    from modules.hr.demo import seed_demo_hr
    from modules.pos.demo import seed_demo_orders
    from modules.pos.models import Order, OrderStatus
    from modules.reservations.demo import seed_demo_reservations
    from modules.tables.demo import seed_demo_tables
    from modules.tasks.demo import seed_demo_tasks
    tasks = seed_demo_tasks()
    pop = {"To'y oshi": 6, "Choyxona oshi": 4, "Samarqand oshi": 3, "Qazili osh": 2, "Qo'y go'shti kabob": 4, "Mol go'shti kabob": 3,
           "Lula kabob": 2, "Tandir somsa": 4, "Obi non": 5, "Ko'k choy (choynak)": 5, "Qora choy (choynak)": 3, "Achchiq-chuchuk": 3,
           "Qovurma lag'mon": 3, "Sho'rva": 2, "Manti (5 dona)": 2, "Coca-Cola 0,5": 2, "Qozon kabob": 1.5}
    orders = seed_demo_orders(days=65, per_day=(100, 135), weights=pop)
    _branches(t)
    # zalda o'tirganlarga stol raqami — hisobot va stol tarixi haqiqiy ko'rinsin
    rnd = random.Random(5)
    for o in Order.objects.filter(type="dine_in", status=OrderStatus.PAID).only("id")[:4000]:
        Order.objects.filter(pk=o.pk).update(table_no=str(rnd.randint(1, 10)))
    hr = seed_demo_hr()
    _payroll_rates()
    from core.models import Membership
    from modules.hr.demo import seed_demo_recruit_people
    own = Membership.objects.filter(role__code="owner").select_related("user").first()
    rec = seed_demo_recruit_people(own.user if own else None)
    log(f"HR: vakansiya {rec.get('vacancies', 0)} · nomzod {rec.get('applications', 0)} · profil {rec.get('profiles', 0)}")
    _payroll_history()
    exp = _expenses()
    tables = seed_demo_tables()
    res = seed_demo_reservations()
    log(f"Kassa: {orders} chek (65 kun) · vazifalar: {tasks} · xodim kartalari: {hr} · chiqimlar: {exp} · stollar: {tables} · bronlar: {res}")


def _branches(t):
    """3 ta filial: savdo 50 / 30 / 20 % — filiallar jadvali va filial tanlagichi bo'sh turmasin. ~1,2% chek bekor qilingan."""
    from core.models import Branch
    from modules.pos.models import CashShift, Order, OrderStatus
    main = Branch.objects.filter(deleted_at__isnull=True).first()
    b2 = Branch.objects.create(name="Yunusobod filiali", address="Toshkent sh., Yunusobod tumani, 4-kvartal (namuna)", phone="+998712000001", sort_order=1)
    b3 = Branch.objects.create(name="Sergeli filiali", address="Toshkent sh., Sergeli tumani, 7-kvartal (namuna)", phone="+998712000002", sort_order=2)
    rnd = random.Random(17)
    ids = list(Order.objects.values_list("id", flat=True))
    to2, to3, cancel = [], [], []
    for i in ids:
        x = rnd.random()
        (to2 if x < 0.30 else to3 if x < 0.50 else []).append(i)
        if rnd.random() < 0.012:
            cancel.append(i)
    Order.objects.filter(pk__in=to2).update(branch=b2)
    Order.objects.filter(pk__in=to3).update(branch=b3)
    Order.objects.filter(pk__in=cancel, status=OrderStatus.PAID).update(
        status=OrderStatus.CANCELLED, cancel_reason="Mijoz bekor qildi", cancelled_at=F("paid_at"), paid_at=None)
    CashShift.objects.filter(branch__isnull=True).update(branch=main)
    return [main, b2, b3]


def _payroll_history():
    """O'tgan 2 oy oyliklari (to'langan) — mehnat xarajati va oylik tarixi taqqoslansin."""
    from modules.hr.models import Employee, PayrollStatus, Payslip
    first = timezone.localdate().replace(day=1)
    rnd = random.Random(4)
    for k in (1, 2):
        per = first
        for _ in range(k):
            per = (per - timedelta(days=1)).replace(day=1)
        for e in Employee.objects.all():
            s = Payslip(employee=e, period=per, salary_type=e.salary_type, rate=e.rate, hours=rnd.choice([168, 176, 184]),
                        shifts=rnd.choice([24, 26, 27]), bonus=rnd.choice([0, 0, 200_000, 400_000]), penalty=rnd.choice([0, 0, 0, 50_000]),
                        status=PayrollStatus.PAID, paid_at=timezone.now() - timedelta(days=30 * k - 5))
            s.compute()
            s.save()


def _expenses() -> int:
    """O'rta restoran (120 o'rin) oylik xarajatlari, 2026: ijara ~30 mln, kommunal ~7 mln, aylanmadan soliq 4%…"""
    from django.db.models import Sum

    from modules.finance.models import Expense, ExpenseCategory, ensure_categories
    from modules.pos.models import Order
    ensure_categories()
    cats = {c.code: c for c in ExpenseCategory.objects.all()}
    today = timezone.localdate()
    rnd = random.Random(13)
    n = 0
    first = today.replace(day=1)
    months = [first]
    for _ in range(2):
        months.insert(0, (months[0] - timedelta(days=1)).replace(day=1))
    for m in months:
        nxt = (m + timedelta(days=32)).replace(day=1)
        rev = Order.objects.filter(status="paid", paid_at__date__gte=m, paid_at__date__lt=nxt).aggregate(s=Sum("total"))["s"] or 0
        rows = [("rent", 30_000_000, 3, "Ijara (oylik)"), ("utilities", rnd.randint(6_500_000, 8_000_000), 10, "Svet, gaz, suv"),
                ("tax", int(rev * 0.04), 15, "Aylanmadan soliq 4%"), ("software", 490_000, 2, "RestoPOS obuna"),
                ("marketing", 2_500_000, 5, "Instagram va Telegram reklama"), ("packaging", 1_400_000, 8, "Olib ketish idishlari"),
                ("repair", rnd.choice([450_000, 900_000, 1_200_000]), 18, "Tandir va qozon ta'miri"),
                ("delivery", rnd.randint(1_800_000, 2_600_000), 25, "Kuryer yoqilg'isi / Yandex"), ("other", 700_000, 20, "Xo'jalik mollari")]
        for code, amount, day, note in rows:
            d = m + timedelta(days=day - 1)
            if d <= today and code in cats and amount:
                Expense.objects.create(date=d, category=cats[code], amount=amount, note=note)
                n += 1
    return n


def _payroll_rates():
    """Toshkent o'rta restorani 2026: menejer ~5 mln, oshpaz ~4,5 mln, ofitsiant soatbay + chaychaqa, kassir smenabay."""
    from modules.hr.models import Employee, Payslip, Position
    rates = {"Menejer": 5_000_000, "Oshpaz": 4_500_000, "Kassir": 150_000, "Ofitsiant": 16_000, "Buxgalter": 3_500_000, "Marketolog": 3_000_000}
    for name, r in rates.items():
        Position.objects.filter(name=name).update(default_rate=r)
        Employee.objects.filter(position__name=name).update(rate=r)
    for s in Payslip.objects.select_related("employee"):
        s.rate = s.employee.rate
        s.compute()
        s.save()


def _training(t, log):
    from modules.training.demo import COURSES, seed_demo_training
    n = seed_demo_training(courses=[OSH_COURSE, COURSES[1], COURSES[2], SAFETY_COURSE],
                           cook_task=("Oshni standart bo'yicha damlang", "Bitta qozon oshni darsdagi tartibda damlab, laganda porsiya rasmini yuboring."))
    from modules.training.models import Lesson, LessonFile
    for title, url in VIDEOS.items():
        Lesson.objects.filter(title=title, video_url="").update(video_url=url)
    for title, links in LESSON_LINKS.items():
        for les in Lesson.objects.filter(title=title):
            for lt, url in links:
                LessonFile.objects.create(lesson=les, title=lt, url=url)
    vids = Lesson.objects.exclude(video_url="").count()
    log(f"O'qitish: {n} kurs, {vids} ta video dars, testlar, standartlar, topshiriqlar")


def _crm_and_telegram(t, log):
    from modules.crm.demo import seed_demo_crm
    from modules.crm.models import Customer, Promo
    from modules.pos.models import Order
    from modules.telegram.models import Audience, BotUser, Broadcast, BroadcastStatus
    n = seed_demo_crm(t)
    from modules.forecast.demo import seed_demo_forecast
    seed_demo_forecast(t)
    from modules.ops.demo import seed_demo_ops
    seed_demo_ops(t, demo=True)
    from modules.procurement.demo import seed_demo_procurement
    seed_demo_procurement(t)
    from modules.projects.demo import seed_demo_projects
    seed_demo_projects(t)
    Promo.objects.filter(code="LAZZAT10").update(name="NAVROZ10 promokod", code="NAVROZ10", description="Instagram va Telegram kanal obunachilari uchun")
    Promo.objects.filter(name__startswith="Happy hour").update(name="Tushlik vaqti −15%", description="Har kuni 12:00–15:00 butun menyuga", hour_from=12, hour_to=15)
    rnd = random.Random(9)
    now = timezone.now()
    tg = list(Customer.objects.filter(source="telegram")) + list(Customer.objects.exclude(source="telegram").order_by("?")[:12])
    for i, c in enumerate(tg):
        BotUser.objects.create(chat_id=700_000_000 + i, phone=c.phone, full_name=c.name, username="",
                               orders_count=0, spent_total=0, last_seen_at=now - timedelta(days=rnd.randint(0, 20)))
    for i in range(14):                                  # telefon ulashmagan obunachilar ham bo'ladi
        BotUser.objects.create(chat_id=710_000_000 + i, full_name=rnd.choice(["Aziz", "Madina", "Sherzod", "Laylo", "Temur", "Kamola"]),
                               last_seen_at=now - timedelta(days=rnd.randint(0, 30)), is_blocked=(i % 7 == 0))
    # mijoz buyurtmalarining bir qismi Telegram Mini App'dan kelgan
    phones = [c.phone for c in tg]
    ids = list(Order.objects.filter(customer_phone__in=phones, status="paid").values_list("id", flat=True))
    rnd.shuffle(ids)
    Order.objects.filter(pk__in=ids[: len(ids) // 3]).update(source="telegram", type="delivery")
    for bu in BotUser.objects.exclude(phone=""):
        qs = Order.objects.filter(customer_phone=bu.phone, status="paid", source="telegram")
        BotUser.objects.filter(pk=bu.pk).update(orders_count=qs.count(), spent_total=sum(qs.values_list("total", flat=True)))
    total = BotUser.objects.filter(is_blocked=False).count()
    for text, days, aud in [("🌷 Navro'z bayrami munosabati bilan butun menyuga −15%! 21–23-mart. Bron: botda «Stol bron qilish»", 12, Audience.ALL),
                            ("🆕 Yangi taom: Qazili osh — uy qazisi va bedana tuxumi bilan. Tatib ko'ring!", 5, Audience.ALL)]:
        Broadcast.objects.create(text=text, audience=aud, status=BroadcastStatus.SENT, total=total, sent=total - 2, failed=2,
                                 sent_at=now - timedelta(days=days))
    Broadcast.objects.create(text="Sizni sog'indik! Shu hafta NAVROZ10 promokodi bilan −10% 🙂", audience=Audience.BUYERS)
    tcfg = {"welcome_text": "Assalomu alaykum! «Navro'z» — milliy taomlar. Menyu, yetkazib berish va stol bron — shu yerda 👇",
            "delivery_fee": 15000, "free_delivery_from": 150000, "min_order": 50000, "allow_dine_in": True}
    mods = dict((t.settings or {}).get("modules") or {})
    mods["telegram"] = {**(mods.get("telegram") or {}), **tcfg}
    mods["crm"] = {**(mods.get("crm") or {}), "welcome_bonus": 10000, "birthday_bonus": 50000}
    t.settings = {**(t.settings or {}), "modules": mods}
    t.save(update_fields=["settings"])
    log(f"Mijozlar: {n} · Telegram obunachilar: {BotUser.objects.count()} · xabarlar: {Broadcast.objects.count()}")


def _site(t, log):
    from modules.cms.models import SiteSettings
    s = SiteSettings.get()
    s.title = NAME
    s.tagline = {"uz": "Toshkentning mazali oshi va kaboblari — 2016-yildan beri", "ru": "Вкусный плов и шашлык Ташкента — с 2016 года",
                 "en": "Tashkent's tasty plov and kebabs — since 2016"}
    s.phone = "+998712000000"
    s.address = "Toshkent sh., Chilonzor tumani, 9-kvartal (namuna manzil)"
    s.delivery = {"free_from": 150000, "fee": 15000, "eta_min": 35, "eta_max": 50}
    s.theme = {**(s.theme or {}), "primary": "#B5452B", "accent": "#1E6F5C", "bg": "#FBF6EE", "ink": "#23170F"}
    s.save()
    from core.models import Branch
    from modules.cms.models import SiteSection
    Branch.objects.update(address="Toshkent sh., Chilonzor tumani, 9-kvartal (namuna)", phone="+998712000000")
    for sec in SiteSection.objects.all():
        if sec.type == "hero":
            sec.props = {**sec.props, "title": "Toshkentning haqiqiy oshi va kaboblari",
                         "subtitle": "Qozon oshi, tandir somsa va kaboblar — zalda, olib ketish yoki 35–50 daqiqada yetkazib berish",
                         "cta": "Buyurtma berish"}
        elif sec.type == "bonus":
            sec.props = {**sec.props, "percent": 3}
        sec.save()
    log("Sayt: sarlavha, aloqa, yetkazib berish, rang, filial manzili")


def _kitchen_now(t, log):
    """Hozir oshxonada tayyorlanayotgan 4 ta buyurtma — oshxona ekrani va kassa «ochiq» holati bo'sh turmasin."""
    from core.events import emit
    from core.models import User
    from modules.catalog.models import Product
    from modules.pos.models import CashShift, Order, OrderItem
    shift = CashShift.objects.filter(closed_at__isnull=True).first()
    cashier = User.objects.filter(memberships__role__code="cashier").first()
    rnd = random.Random(3)
    prods = list(Product.objects.filter(in_stop_list=False))
    from modules.kds.models import Ticket, TicketStatus
    plan = [("dine_in", "4", "new"), ("dine_in", "VIP-1", "cooking"), ("takeaway", "", "new"), ("delivery", "", "cooking"),
            ("dine_in", "7", "ready"), ("dine_in", "2", "cooking"), ("delivery", "", "ready"), ("takeaway", "", "new")]
    cooks = list(User.objects.filter(memberships__role__code="cook"))
    for k, (typ, table, kst) in enumerate(plan):
        o = Order.objects.create(shift=shift, branch=shift.branch if shift else None, cashier=cashier, type=typ, table_no=table, source="telegram" if typ == "delivery" else "pos",
                                 note="Piyozsiz" if k == 1 else "")
        for p in rnd.sample(prods, k=rnd.randint(2, 4)):
            OrderItem.objects.create(order=o, product=p, name=p.name["uz"], qty=rnd.randint(1, 3), price=p.price, cost=p.cost)
        o.recalc()
        o.save()
        emit("pos.order_created", {"order_id": o.pk, "number": o.number, "total": o.total, "_tenant": t}, tenant=t)
        started = timezone.now() - timedelta(minutes=rnd.randint(4, 14))
        upd = {"status": kst}
        if kst in (TicketStatus.COOKING, TicketStatus.READY):
            upd.update(started_at=started, cook=rnd.choice(cooks) if cooks else None)
        if kst == TicketStatus.READY:
            upd["ready_at"] = started + timedelta(minutes=rnd.randint(6, 11))
        Ticket.objects.filter(order=o).update(**upd)
        Order.objects.filter(pk=o.pk).update(created_at=timezone.now() - timedelta(minutes=(8 - k) * 3))
    log("Oshxona ekrani: 8 ta faol buyurtma (yangi / tayyorlanmoqda / tayyor)")
'@

Put 'backend\tests\test_live.py' @'
"""
Jonli demo: tarix bilan hozir orasidagi bo'shliq to'ldiriladi — cheklar (kun/soat taqsimoti), ombor yechiladi, kam qolgan
xomashyo zakup qilinadi, davomat va bron paydo bo'ladi, oshxonada faol buyurtmalar; takror chaqirilsa ko'paymaydi;
demo belgisi bo'lmagan restoranga umuman tegmaydi.
"""
from datetime import timedelta

import pytest
from django.core.cache import cache
from django.db.models import F
from django.utils import timezone
from django_tenants.utils import schema_context


@pytest.fixture
def demo(tenant):
    from public.services import set_modules
    with schema_context("public"):
        set_modules(tenant, sorted({*tenant.enabled_modules, "inventory", "procurement", "hr", "kds", "tables", "reservations", "crm", "finance"}))
    with schema_context("lazzat"):
        from django.db import connection
        connection.set_tenant(tenant)
        from modules.catalog.demo import seed_demo_menu
        from modules.hr.demo import seed_demo_hr
        from modules.inventory.demo import seed_demo_inventory
        from modules.pos.demo import seed_demo_orders
        from modules.pos.models import Order
        from modules.tables.demo import seed_demo_tables
        seed_demo_menu()
        seed_demo_inventory(tenant)
        seed_demo_orders(days=10, per_day=(30, 40))
        from core.models import Membership, Role, User
        for ph, code in (("998935559001", "cook"), ("998935559002", "cashier")):
            u = User.objects.filter(phone=f"+{ph}").first() or User.objects.create_user(ph, full_name=f"Xodim {code}")
            Membership.objects.get_or_create(user=u, role=Role.objects.get(code=code))
        from modules.hr.models import Attendance, Employee
        Employee.objects.all().delete()
        seed_demo_hr()
        Attendance.objects.all().delete()
        seed_demo_tables()
        Order.objects.update(paid_at=F("paid_at") - timedelta(days=3), created_at=F("created_at") - timedelta(days=3))
    cache.clear()
    yield tenant
    with schema_context("public"):
        tenant.settings = {k: v for k, v in (tenant.settings or {}).items() if k != "demo_live"}
        tenant.save(update_fields=["settings"])


def _set_live(t, on=True):
    with schema_context("public"):
        t.settings = {**(t.settings or {}), "demo_live": on}
        t.save(update_fields=["settings"])


@pytest.mark.django_db
def test_not_live_does_nothing(demo):
    from public.live import tick
    with schema_context("lazzat"):
        assert tick(demo, force=True) == {}


@pytest.mark.django_db
def test_fills_gap_and_links_everything(demo):
    from public.live import tick
    _set_live(demo)
    with schema_context("lazzat"):
        from modules.hr.models import Attendance
        from modules.inventory.models import StockMovement
        from modules.pos.models import Order
        from modules.reservations.models import Reservation
        before = Order.objects.count()
        r = tick(demo, force=True)
        assert "error" not in r and r["orders"] > 30
        today = timezone.localdate()
        days = set(Order.objects.filter(paid_at__date__gt=today - timedelta(days=3)).values_list("paid_at__date", flat=True))
        assert today - timedelta(days=1) in days and today - timedelta(days=2) in days
        hours = {timezone.localtime(x).hour for x in Order.objects.filter(pk__gt=0).exclude(paid_at__isnull=True).values_list("paid_at", flat=True)[:4000]}
        assert hours <= set(range(10, 23)) | set(range(0, 24))                 # soatlar mavjud (tarixdagilar ham)
        assert StockMovement.objects.filter(kind="sale", ref__startswith="Savdo ").exists()
        assert Attendance.objects.filter(check_in__date=today - timedelta(days=1)).exists()
        assert Reservation.objects.filter(starts_at__date=today + timedelta(days=1)).count() >= 4
        n = Order.objects.count()
        assert n > before
        assert tick(demo, force=True).get("orders", 0) <= 3                    # takror chaqirilsa — deyarli hech narsa
        assert tick(demo) == {}                                                # kesh: 4 daqiqada bir marta


@pytest.mark.django_db
def test_low_stock_is_restocked(demo):
    from public.live import tick
    _set_live(demo)
    with schema_context("lazzat"):
        from modules.inventory.models import Ingredient, Purchase
        from modules.tasks.models import Task
        Ingredient.objects.filter(min_stock__gt=0).update(stock=F("min_stock") * 0.5)
        p0 = Purchase.objects.count()
        tick(demo, force=True)
        assert Purchase.objects.count() > p0                                    # kechagi kunlar uchun zakup qabul qilindi
        assert Task.objects.filter(title__startswith="Ta'minot:").count() == len(set(Task.objects.filter(title__startswith="Ta'minot:").values_list("title", flat=True)))
'@

Put 'frontend\apps\admin\src\layouts\AppShell.vue' @'
<script setup lang="ts">
/**
 * Panel qobig'i. Menyu ikki bosqichli:
 *   1) Asosiy menyu — «Asosiy sahifa» va bo'limlar (Savdo, Menyu va mijozlar, Ombor va xarid, Xodimlar, …);
 *   2) bo'limga kirilganda — faqat shu bo'lim modullari, pastida «Asosiy sahifaga qaytish».
 * Telefon: pastki tab-bar + drawer; planshet: ikonkali tor menyu; kompyuter: to'liq.
 */
import { computed, ref, watch } from 'vue'
import { RouterLink, RouterView, useRoute, useRouter } from 'vue-router'
import { UiAvatar, UiIcon } from '@restopos/ui'
import { t } from '@restopos/ui'
import { useAuth } from '@/stores/auth'
import { useUi } from '@/stores/ui'
import { HOME, matches, useNav } from '@/nav/sections'

const a = useAuth(), ui = useUi(), route = useRoute(), router = useRouter()
const { items, sections, current, currentItem, sectionLink } = useNav()
/** Platforma yordami rejimi — egasi bergan ruxsat bilan kirilgan; tepada ogohlantirish */
const supportMode = computed(() => (a.me?.roles ?? []).includes('platform_support'))

/** Menyuda qaysi daraja ko'rinadi: odatda joriy sahifa bo'limi; «Bo'limlar» tugmasi bilan asosiy menyuni ko'rish mumkin */
const browse = ref<string | null | undefined>(undefined)     // undefined — sahifaga qarab; '' — asosiy menyu; kod — shu bo'lim
watch(() => route.fullPath, () => { browse.value = undefined })
const shown = computed(() => (browse.value === undefined ? current.value : browse.value ? sections.value.find(s => s.code === browse.value) ?? null : null))

function goHome() { ui.sidebarOpen = false; browse.value = undefined; router.push('/') }
function openRoot() { browse.value = ''; ui.sidebarOpen = true }
const close = () => { ui.sidebarOpen = false }

// telefon pastki paneli: Asosiy + eng ko'p ishlatiladigan 3 ta modul + «Bo'limlar»
const PIN = ['/pos', '/tasks', '/training', '/market', '/projects', '/inventory', '/hr', '/reports']   // Kassa · Vazifalar · O'qitish (rolga qarab)
const phoneNav = computed(() => PIN.map(r => items.value.find(i => i.route === r)).filter(Boolean).slice(0, 3) as typeof items.value)
const title = computed(() => {
  if (route.path.startsWith('/s/') && current.value) return current.value.title
  const it = currentItem.value ?? items.value.find(i => matches(i.route, route.path))
  return it ? t(it.label, ui.lang) : ((route.meta.title as string) ?? (route.path === '/' ? 'Boshqaruv paneli' : ''))
})
const trialDays = computed(() => { const d = a.me?.tenant.trial_ends_at; if (!d) return null; return Math.max(0, Math.ceil((new Date(d).getTime() - Date.now()) / 86400000)) })
</script>
<template>
  <div class="shell">
    <aside class="side" :class="{ open: ui.sidebarOpen }">
      <div class="brand">
        <span class="logo">{{ (a.me?.tenant.name ?? 'R').slice(0, 1) }}</span>
        <div class="bt"><b>{{ a.me?.tenant.name }}</b><span>{{ a.me?.roles.includes('owner') ? 'Egasi · superadmin' : (a.me?.role_names?.length ? a.me.role_names : a.me?.roles ?? []).join(', ') }}</span></div>
      </div>
      <!-- 1-daraja: asosiy menyu -->
      <nav v-if="!shown" class="nav">
        <RouterLink to="/" class="item" :class="{ on: route.path === '/' }" @click="close"><UiIcon :name="HOME.icon" /><span class="lbl">Boshqaruv paneli</span></RouterLink>
        <div class="grp">Bo'limlar</div>
        <RouterLink v-for="s in sections" :key="s.code" :to="sectionLink(s)" class="item sec" :style="{ '--sc': s.color }" :title="s.title" @click="s.items.length === 1 && close()">
          <span class="si"><UiIcon :name="s.icon" :size="18" /></span><span class="lbl">{{ s.title }}</span>
          <UiIcon v-if="s.items.length > 1" name="chevron" :size="14" class="chev" />
        </RouterLink>
      </nav>
      <!-- 2-daraja: bo'lim ichi -->
      <nav v-else class="nav in" :style="{ '--sc': shown.color }">
        <RouterLink :to="`/s/${shown.code}`" class="sh" :title="shown.title" @click="close"><span class="si"><UiIcon :name="shown.icon" :size="18" /></span><span class="lbl"><small>Bo'lim</small>{{ shown.title }}</span></RouterLink>
        <RouterLink v-for="n in shown.items" :key="n.route" :to="n.route" class="item" :class="{ on: matches(n.route, route.path) }" :title="t(n.label, ui.lang)" @click="close">
          <UiIcon :name="n.icon" /><span class="lbl">{{ t(n.label, ui.lang) }}</span>
        </RouterLink>
        <div class="navsp"></div>
        <button type="button" class="item alt" title="Boshqa bo'limlar" @click="browse = ''"><UiIcon name="columns" /><span class="lbl">Boshqa bo'limlar</span></button>
        <button type="button" class="item back" title="Asosiy sahifaga qaytish" @click="goHome"><UiIcon name="home" /><span class="lbl">Asosiy sahifaga qaytish</span></button>
      </nav>
      <div class="foot">
        <a class="item ponly" href="/" target="_blank" rel="noopener"><UiIcon name="globe" /><span class="lbl">Saytni ochish</span></a>
        <a class="item ponly" href="/tv/menu-board/" target="_blank" rel="noopener"><UiIcon name="tv" /><span class="lbl">TV menyu</span></a>
        <div v-if="trialDays" class="trial">Sinov: <b>{{ trialDays }} kun</b></div>
        <button class="item" type="button" @click="ui.cycleTheme()"><UiIcon :name="ui.theme === 'dark' ? 'moon' : 'sun'" /><span class="lbl">{{ ui.theme === 'auto' ? 'Tema: avto' : ui.theme === 'dark' ? 'Tema: dark' : 'Tema: light' }}</span></button>
        <button class="item" type="button" @click="a.logout()"><UiIcon name="logout" /><span class="lbl">Chiqish</span></button>
      </div>
    </aside>
    <div v-if="ui.sidebarOpen" class="scrim" @click="ui.sidebarOpen = false"></div>

    <div class="main">
      <header class="top">
        <button class="burger" type="button" aria-label="Menyu" @click="ui.sidebarOpen = !ui.sidebarOpen"><UiIcon name="menu" /></button>
        <div class="ttl">
          <RouterLink v-if="current && !route.path.startsWith('/s/') && current.items.length > 1" :to="`/s/${current.code}`" class="crumb">{{ current.title }} ›</RouterLink>
          <h1>{{ title }}</h1>
        </div>
        <div class="sp"></div>
        <a class="link" :href="`/`" target="_blank" rel="noopener"><UiIcon name="globe" /><span class="hp">Sayt</span></a>
        <a class="link" :href="`/tv/menu-board/`" target="_blank" rel="noopener"><UiIcon name="tv" /><span class="hp">TV</span></a>
        <RouterLink to="/settings" class="me" :title="`${a.me?.full_name ?? ''} · ${a.me?.phone ?? ''} — profil`"><UiAvatar :name="a.me?.full_name || a.me?.phone" :src="a.me?.avatar" :size="36" /></RouterLink>
      </header>
      <div v-if="supportMode" class="sup">🛟 Platforma yordami rejimi — egasi bergan ruxsat bilan. Barcha harakatlar «O'zgarishlar tarixi»ga yoziladi. <button type="button" @click="a.logout()">Chiqish</button></div>
      <main class="content"><RouterView /></main>
      <nav class="tabbar">
        <RouterLink to="/" class="tab" :class="{ on: route.path === '/' }"><UiIcon name="home" :size="22" /><span>Panel</span></RouterLink>
        <RouterLink v-for="n in phoneNav" :key="n.route" :to="n.route" class="tab" :class="{ on: matches(n.route, route.path) }"><UiIcon :name="n.icon" :size="22" /><span>{{ t(n.label, ui.lang).split(' ')[0] }}</span></RouterLink>
        <button class="tab" type="button" @click="openRoot()"><UiIcon name="menu" :size="22" /><span>Bo'limlar</span></button>
      </nav>
    </div>
  </div>
</template>
<style scoped>
.sup { background: #1D4ED8; color: #fff; padding: 8px 16px; font-size: var(--fs-s); font-weight: 700; display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
.sup button { border: 1px solid rgba(255,255,255,.6); background: transparent; color: #fff; border-radius: 8px; padding: 4px 10px; font: inherit; cursor: pointer; }
.shell { display: flex; min-height: 100vh; }
.side { width: var(--sidebar-w); flex-shrink: 0; background: var(--surface); border-right: 1px solid var(--line); display: flex; flex-direction: column; padding: 16px 12px; gap: 4px; position: sticky; top: 0; height: 100vh; overflow-y: auto; }
.brand { display: flex; align-items: center; gap: 10px; padding: 4px 8px 14px; }
.logo { width: 34px; height: 34px; border-radius: 10px; background: var(--brand); color: var(--brand-ink); display: grid; place-items: center; font-family: var(--font-display); font-weight: 800; flex-shrink: 0; }
.bt { display: flex; flex-direction: column; min-width: 0; } .bt b { font-size: var(--fs-b); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; } .bt span { font-size: var(--fs-xs); color: var(--muted); }
.nav { display: flex; flex-direction: column; gap: 4px; flex: 1; }
.grp { font-size: 11px; font-weight: 800; letter-spacing: .06em; text-transform: uppercase; color: var(--muted); padding: 14px 12px 4px; }
.si { width: 30px; height: 30px; border-radius: 9px; display: grid; place-items: center; flex-shrink: 0; background: color-mix(in srgb, var(--sc) 14%, transparent); color: var(--sc); }
.sec .cnt { margin-left: auto; font-size: 11px; font-weight: 800; color: var(--muted); background: var(--surface-2); border-radius: 99px; padding: 1px 7px; }
.sec .chev { transform: rotate(-90deg); color: var(--muted); flex-shrink: 0; margin-left: auto; }
.sh { display: flex; align-items: center; gap: 10px; padding: 10px 12px; margin-bottom: 6px; border-radius: var(--radius); text-decoration: none; color: var(--ink);
  background: color-mix(in srgb, var(--sc) 10%, var(--surface)); border: 1px solid color-mix(in srgb, var(--sc) 30%, transparent); }
.sh .lbl { display: flex; flex-direction: column; font-weight: 800; font-size: var(--fs-b); } .sh small { font-size: 10px; font-weight: 700; color: var(--muted); text-transform: uppercase; letter-spacing: .05em; }
.in .item.on { background: color-mix(in srgb, var(--sc) 14%, var(--surface)); color: var(--sc); }
.navsp { flex: 1; min-height: 12px; }
.item.alt { color: var(--muted); font-size: var(--fs-s); min-height: 40px; }
.item.back { border: 1px dashed var(--line); color: var(--ink); font-weight: 700; }
.item.back:hover { border-color: var(--accent); color: var(--accent); }
.ttl { display: flex; flex-direction: column; min-width: 0; }
.crumb { font-size: var(--fs-xs); font-weight: 700; color: var(--muted); text-decoration: none; line-height: 1.1; margin-top: 4px; }
.crumb:hover { color: var(--accent); }
.item { display: flex; align-items: center; gap: 10px; min-height: var(--touch); padding: 0 12px; border-radius: var(--radius); color: var(--ink-2); text-decoration: none; font-weight: 600; font-size: var(--fs-b); border: 0; background: transparent; cursor: pointer; text-align: left; flex-shrink: 0; }
.item .lbl { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; min-width: 0; }
.ponly { display: none; }
.item:hover { background: var(--surface-3); }
.item.on { background: var(--accent-tint); color: var(--accent); font-weight: 700; }
.foot { display: flex; flex-direction: column; gap: 4px; border-top: 1px solid var(--line-2); padding-top: 8px; margin-top: 8px; }
.trial { font-size: var(--fs-xs); color: var(--muted); padding: 8px 12px; border-radius: var(--radius); background: var(--surface-2); }
.main { flex: 1; min-width: 0; display: flex; flex-direction: column; }
.top { position: sticky; top: 0; z-index: 5; display: flex; align-items: center; gap: 10px; min-height: var(--topbar-h); padding: 0 var(--gutter); background: var(--surface); border-bottom: 1px solid var(--line); }
.top h1 { margin: 0; font-family: var(--font-display); font-size: var(--fs-xl); font-weight: 800; letter-spacing: -.02em; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.sp { flex: 1; }
.link { display: inline-flex; align-items: center; gap: 6px; min-height: var(--touch); padding: 0 10px; border-radius: var(--radius); border: 1px solid var(--line); color: var(--ink-2); text-decoration: none; font-size: var(--fs-s); font-weight: 700; }
.me { display: inline-flex; border-radius: 12px; text-decoration: none; }
.me:hover { box-shadow: 0 0 0 3px var(--accent-tint); }
.burger { display: none; width: var(--touch); height: var(--touch); border-radius: var(--radius); border: 1px solid var(--line); background: var(--surface); cursor: pointer; }
.content { padding: var(--gutter); display: flex; flex-direction: column; gap: 16px; }
.tabbar { display: none; }
.scrim { display: none; }
/* planshet: tor ikonkali menyu */
@media (min-width: 601px) and (max-width: 1024px) { .side { padding: 12px 8px; } .lbl, .sh .lbl, .bt, .trial, .grp, .cnt, .chev, .crumb { display: none; } .sh { border: 0; background: transparent; } .item, .sh { justify-content: center; padding: 0; } .sh { min-height: var(--touch); } .brand { justify-content: center; padding-bottom: 10px; } }
/* telefon: drawer + tab-bar */
@media (max-width: 600px) {
  .side { position: fixed; left: 0; top: 0; z-index: 40; width: min(300px, 86vw); transform: translateX(-100%); transition: transform .2s; box-shadow: var(--shadow); }
  .side.open { transform: none; }
  .scrim { display: block; position: fixed; inset: 0; background: rgba(0,0,0,.35); z-index: 30; }
  .burger { display: grid; place-items: center; }
  .content { padding-bottom: calc(var(--gutter) + 64px); }
  .hp, .top .link { display: none; }
  .ponly { display: flex; }
  .top h1 { font-size: var(--fs-l); } .crumb { display: none; }
  .tabbar { display: flex; position: fixed; left: 0; right: 0; bottom: 0; z-index: 20; background: var(--surface); border-top: 1px solid var(--line); padding: 6px 4px calc(6px + env(safe-area-inset-bottom)); }
  .tab { flex: 1; display: flex; flex-direction: column; align-items: center; gap: 2px; padding: 6px 2px; font-size: 10px; font-weight: 700; color: var(--muted); text-decoration: none; border: 0; background: transparent; }
  .tab.on { color: var(--accent); }
}
</style>
'@

Put 'frontend\apps\admin\src\nav\sections.ts' @'
/**
 * Menyu tuzilmasi: asosiy bo'limlar → ichki modullar.
 * Modullar menyusi backenddan (me.nav, rol va yoqilgan modullar bo'yicha) keladi; bu yerda faqat qaysi bo'limga tegishliligi.
 * Yangi modul qo'shilsa — `routes` ga yo'lini yozing (yozilmasa «Boshqa» bo'limiga tushadi).
 */
import { computed, ref } from 'vue'
import { api } from '@restopos/api'
import { useRoute } from 'vue-router'
import { useAuth } from '@/stores/auth'

export type NavItem = { route: string; label: { uz?: string; ru?: string; en?: string }; icon: string; order: number; perm?: string }
export type Section = { code: string; title: string; icon: string; emoji: string; color: string; desc: string; routes: string[] }
export type SectionView = Section & { items: (NavItem & { desc: string })[] }

export const SECTIONS: Section[] = [
  { code: 'sales', title: 'Savdo va xizmat', icon: 'receipt', emoji: '💳', color: '#EA580C', desc: 'Kassa, oshxona ekrani, zal va bron',
    routes: ['/pos', '/kds', '/tables', '/reservations', '/delivery'] },
  { code: 'menu', title: 'Menyu va mijozlar', icon: 'book', emoji: '🍽️', color: '#DB2777', desc: 'Taomnoma, mijozlar va bonus, Telegram bot, sayt',
    routes: ['/catalog', '/crm', '/telegram', '/site'] },
  { code: 'stock', title: 'Ombor va xarid', icon: 'box', emoji: '📦', color: '#2563EB', desc: 'Qoldiq va tannarx, zakup, bozorlik, bayram prognozi',
    routes: ['/inventory', '/procurement', '/market', '/forecast'] },
  { code: 'team', title: 'Xodimlar', icon: 'users', emoji: '👥', color: '#059669', desc: 'Xodimlar, smena va davomat, ishga olish, baholash va KPI',
    routes: ['/hr', '/recruiting', '/kpi'] },
  { code: 'training', title: "O'qitish va standartlar", icon: 'book', emoji: '🎓', color: '#CA8A04', desc: "Kurslar, testlar, standartlar, tashkiliy tuzilma va lavozim yo'riqnomalari",
    routes: ['/training', '/org', '/positions'] },
  { code: 'work', title: 'Vazifa va loyihalar', icon: 'check', emoji: '✅', color: '#7C3AED', desc: 'Kundalik vazifalar, muammolar va katta loyihalar',
    routes: ['/tasks', '/projects'] },
  { code: 'finance', title: 'Moliya va hisobot', icon: 'chart', emoji: '📊', color: '#0891B2', desc: 'Savdo, foyda-zarar, food cost, menyu tahlili',
    routes: ['/reports'] },
  { code: 'settings', title: 'Sozlamalar', icon: 'sliders', emoji: '⚙️', color: '#64748B', desc: 'Filiallar, foydalanuvchilar, modullar, yordam',
    routes: ['/branches', '/users', '/modules', '/settings', '/support', '/audit'] },
]

/** Har modul kartasi uchun bir qatorli tushuntirish (bo'lim sahifasida) */
export const DESC: Record<string, string> = {
  '/pos': "Buyurtma olish, to'lov, smena ochish-yopish",
  '/kds': 'Oshpazlar uchun buyurtmalar ekrani',
  '/tables': 'Zal xaritasi, stollar holati, ofitsiantlar',
  '/reservations': 'Stol bron qilish va navbat',
  '/delivery': 'Yetkazib berish buyurtmalari va kuryerlar',
  '/catalog': 'Taomlar, narxlar, qo\'shimchalar, stop-list',
  '/crm': 'Mijozlar bazasi, keshbek, promo-kodlar',
  '/telegram': 'Bot, Mini App, xabar tarqatish',
  '/site': 'Restoran sayti, logotip va ranglar',
  '/inventory': 'Qoldiq, kirim, tex-karta, tannarx, xarid rejasi',
  '/procurement': "Ta'minotchilar, bozorlar ro'yxati, narx, buyurtma, qarz",
  '/market': 'Bozorchi avansi, xarid, taksi/hammol, kamomad',
  '/forecast': 'Bayramlar, ob-havo va savdo prognozi',
  '/hr': 'Xodimlar ro\'yxati, smena, davomat, oylik',
  '/recruiting': 'Vakansiyalar, nomzodlar, suhbatlar',
  '/kpi': 'Baholash, KPI va reyting',
  '/training': 'Kurslar, testlar, sertifikatlar, standartlar',
  '/org': "Bo'limlar va kim kimga bo'ysunadi",
  '/positions': 'Lavozim vazifalari va talablari',
  '/tasks': 'Kundalik vazifalar, muammolar, nazorat',
  '/projects': "Filial ochish, yangi menyu, ta'mir — katta ishlar",
  '/reports': 'Savdo, foyda-zarar, food cost, menyu tahlili',
  '/branches': "Filiallar, manzil, ish vaqti",
  '/users': 'Foydalanuvchilar va rollar (ruxsatlar)',
  '/modules': "Modullarni yoqish va o'chirish",
  '/settings': 'Restoran va profil sozlamalari',
  '/support': 'Texnik yordam va platforma bilan aloqa',
  '/audit': "Kim, qachon, nimani o'zgartirgani",
}

const TAIL: NavItem[] = [
  { route: '/branches', label: { uz: 'Filiallar', ru: 'Филиалы', en: 'Branches' }, icon: 'store', order: 80, perm: 'core.branches.manage' },
  { route: '/users', label: { uz: 'Foydalanuvchilar', ru: 'Пользователи', en: 'Users' }, icon: 'users', order: 85, perm: 'core.users.manage' },
  { route: '/modules', label: { uz: 'Modullar', ru: 'Модули', en: 'Modules' }, icon: 'sliders', order: 95, perm: 'core.modules.manage' },
  { route: '/settings', label: { uz: 'Sozlamalar', ru: 'Настройки', en: 'Settings' }, icon: 'bars', order: 96, perm: 'core.settings.view' },
  { route: '/support', label: { uz: 'Yordam', ru: 'Поддержка', en: 'Support' }, icon: 'headset', order: 97, perm: 'core.settings.view' },
  { route: '/audit', label: { uz: "O'zgarishlar tarixi", ru: 'Журнал изменений', en: 'Audit log' }, icon: 'clock', order: 98, perm: 'core.settings.view' },
]
export const HOME: NavItem = { route: '/', label: { uz: 'Boshqaruv paneli', ru: 'Панель', en: 'Dashboard' }, icon: 'home', order: 0 }

export const matches = (route: string, path: string) => (route === '/' ? path === '/' : path === route || path.startsWith(route + '/'))

export function useNav() {
  const a = useAuth(), route = useRoute()
  const items = computed<NavItem[]>(() => [...((a.me?.nav ?? []) as NavItem[]), ...TAIL.filter(i => !i.perm || a.can(i.perm))])
  const sections = computed<SectionView[]>(() => {
    const used = new Set<string>()
    const out: SectionView[] = SECTIONS.map(s => {
      const its = items.value.filter(i => s.routes.includes(i.route)).sort((x, y) => s.routes.indexOf(x.route) - s.routes.indexOf(y.route))
      its.forEach(i => used.add(i.route))
      return { ...s, items: its.map(i => ({ ...i, desc: DESC[i.route] ?? '' })) }
    })
    const rest = items.value.filter(i => !used.has(i.route))
    if (rest.length) out.splice(out.length - 1, 0, { code: 'other', title: 'Boshqa', icon: 'bars', emoji: '🧩', color: '#475569', desc: 'Qo\'shimcha modullar', routes: rest.map(r => r.route), items: rest.map(i => ({ ...i, desc: DESC[i.route] ?? '' })) })
    return out.filter(s => s.items.length)
  })
  /** Joriy sahifa qaysi bo'limda: /s/<kod> yoki modul yo'li bo'yicha (ichki sahifalar ham, masalan /projects/5) */
  const current = computed<SectionView | null>(() => {
    const p = route.path
    if (p.startsWith('/s/')) return sections.value.find(s => s.code === p.slice(3)) ?? null
    return sections.value.find(s => s.items.some(i => matches(i.route, p))) ?? null
  })
  const currentItem = computed(() => current.value?.items.find(i => matches(i.route, route.path)) ?? null)
  /** Bo'limga kirish: bitta modul bo'lsa — to'g'ridan-to'g'ri o'sha sahifaga */
  const sectionLink = (s: SectionView) => (s.items.length === 1 ? s.items[0].route : `/s/${s.code}`)
  return { items, sections, current, currentItem, sectionLink }
}

/** Bo'lim ko'rsatkichlari (/dashboard/sections) — bir marta yuklanadi, 60 soniyada yangilanadi, sahifalar o'rtasida ulashiladi */
export type Kpi = { label: string; value: string | number; hint: string; tone: '' | 'ok' | 'warn' | 'bad'; route: string; icon: string }
const stats = ref<Record<string, Kpi[]> | null>(null)
let loadedAt = 0
let pending: Promise<void> | null = null
export function useSectionStats() {
  async function load(force = false) {
    if (!force && stats.value && Date.now() - loadedAt < 60_000) return
    if (pending) return pending
    pending = api.get<Record<string, Kpi[]>>('/dashboard/sections').then((r) => { stats.value = r; loadedAt = Date.now() }).catch(() => { /* ko'rsatkichsiz ham ishlaydi */ }).finally(() => { pending = null })
    return pending
  }
  return { stats, load }
}
'@

Put 'frontend\apps\admin\src\views\DashboardView.vue' @'
<script setup lang="ts">
/**
 * Boshqaruv paneli — menejer bir qarashda ko'radigan hamma narsa:
 * KPI (o'tgan davrga nisbatan) · savdo dinamikasi · buyurtmalar holati · eng ko'p sotilganlar ·
 * filiallar · so'nggi buyurtmalar · ombor ogohlantirishlari · tezkor amallar · bugungi vazifalar · so'nggi faoliyat.
 * Davr (bugun/kecha/7 kun/oy/yil) va filial tanlanadi; har 60 soniyada yangilanadi.
 */
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { RouterLink, useRouter } from 'vue-router'
import { api } from '@restopos/api'
import { UiAvatar, UiCard, UiChip, UiEmpty, UiIcon, money } from '@restopos/ui'
import { useAuth } from '@/stores/auth'
import HolidayAlert from '@/components/forecast/HolidayAlert.vue'
import WeatherStrip from '@/components/forecast/WeatherStrip.vue'
import { useNav, useSectionStats } from '@/nav/sections'

const a = useAuth(), router = useRouter()
const { sections, sectionLink } = useNav()
const { stats: secStats, load: loadSec } = useSectionStats()
const secKpi = (code: string) => secStats.value?.[code]?.[0]
const D = ref<any>(null)
const S = ref<any>(null)
const loading = ref(false)
const period = ref<string>(localStorage.getItem('dash.period') || 'today')
const branch = ref<string>('')
const metric = ref<'revenue' | 'orders'>('revenue')
let timer: number | undefined

async function load() {
  loading.value = true
  try {
    const q: Record<string, any> = { period: period.value }
    if (branch.value) q.branch_id = branch.value
    D.value = await api.get('/dashboard/overview', q)
  } finally { loading.value = false }
}
onMounted(async () => {
  await load()
  S.value = await api.get('/dashboard/summary').catch(() => null)
  loadSec(true)
  timer = window.setInterval(() => { if (period.value === 'today' && !document.hidden) { load(); loadSec(true) } }, 60000)
})
onBeforeUnmount(() => clearInterval(timer))
watch([period, branch], () => { try { localStorage.setItem('dash.period', period.value) } catch { /* private */ } load() })

const hello = computed(() => { const h = new Date().getHours(); return h < 5 ? 'Xayrli tun' : h < 11 ? 'Xayrli tong' : h < 18 ? 'Xayrli kun' : 'Xayrli kech' })
const setupLeft = computed(() => (S.value?.checklist ?? []).filter((c: any) => !c.done))
const today = ['Yakshanba', 'Dushanba', 'Seshanba', 'Chorshanba', 'Payshanba', 'Juma', 'Shanba'][new Date().getDay()]
const dateLabel = computed(() => { const d = new Date(); return `${String(d.getDate()).padStart(2, '0')}.${String(d.getMonth() + 1).padStart(2, '0')}.${d.getFullYear()}` })

// ---------- KPI
const ICON_BG = ['var(--series-3)', 'var(--series-1)', '#7C5CC4', 'var(--series-2)', '#D0485A', '#1E8FA0']
function kval(k: any) { if (k.money && Math.abs(k.value) >= 10_000_000) return `${(k.value / 1e6).toFixed(1).replace('.', ',')} mln`; return k.money ? money(k.value) : k.percent ? `${k.value}%` : String(k.value) }
function kgood(k: any) { if (k.delta == null) return null; const up = k.delta > 0; return k.lower_is_better ? !up : up }
function kdelta(k: any) { if (k.delta == null) return ''; const v = Math.abs(k.delta); return `${k.delta > 0 ? '+' : k.delta < 0 ? '−' : ''}${v}${k.percent ? ' p.p.' : '%'}` }
function spark(vals: number[] | undefined, w = 72, h = 26) {
  if (!vals || vals.length < 2) return null
  const max = Math.max(...vals), min = Math.min(...vals), r = max - min || 1
  const pts = vals.map((v, i) => [(i / (vals.length - 1)) * (w - 4) + 2, h - 3 - ((v - min) / r) * (h - 6)])
  return { d: pts.map((p, i) => `${i ? 'L' : 'M'}${p[0].toFixed(1)},${p[1].toFixed(1)}`).join(' '), last: pts[pts.length - 1] }
}

// ---------- savdo dinamikasi (bitta o'q: savdo YOKI buyurtmalar — ikki o'qli grafik chalg'itadi)
const W = 640, H = 240, PL = 44, PB = 26, PT = 12
const hover = ref<number | null>(null)
const chart = computed(() => {
  const pts = D.value?.series?.points ?? []
  if (!pts.length) return null
  const vals = pts.map((p: any) => p[metric.value])
  const rawMax = Math.max(...vals, 1)
  const step = niceStep(rawMax / 4)
  const max = Math.ceil(rawMax / step) * step
  const bw = (W - PL - 8) / pts.length
  const bars = pts.map((p: any, i: number) => {
    const v = p[metric.value], hh = ((H - PB - PT) * v) / max
    return { x: PL + i * bw + bw * 0.18, w: Math.max(3, bw * 0.64), y: H - PB - hh, h: Math.max(0, hh), p, i }
  })
  const ticks = Array.from({ length: 5 }, (_, k) => ({ v: step * k, y: H - PB - ((H - PB - PT) * step * k) / max }))
  const every = Math.ceil(pts.length / 10)
  return { bars, ticks, every, bw }
})
function niceStep(x: number) { const p = Math.pow(10, Math.floor(Math.log10(x || 1))); const n = x / p; return (n <= 1 ? 1 : n <= 2 ? 2 : n <= 5 ? 5 : 10) * p }
function short(v: number) { return metric.value === 'orders' ? String(v) : v >= 1e6 ? `${+(v / 1e6).toFixed(1)}M` : v >= 1e3 ? `${Math.round(v / 1e3)}k` : String(v) }
const hp = computed(() => (hover.value != null && chart.value ? chart.value.bars[hover.value] : null))
const nowLabel = computed(() => `${String(new Date().getHours()).padStart(2, '0')}:00`)

// ---------- buyurtmalar holati (donut)
const ST_COLOR: Record<string, string> = { done: 'var(--series-1)', cooking: 'var(--series-2)', new: 'var(--series-3)', ready: 'var(--series-4)', cancelled: 'var(--series-mute)' }
const donut = computed(() => {
  const items = (D.value?.status?.items ?? []).filter((x: any) => x.value > 0)
  const total = D.value?.status?.total || 0
  const R = 52, C = 2 * Math.PI * R, gap = items.length > 1 ? 3 : 0
  let acc = 0
  return { total, R, C, segs: items.map((x: any) => { const len = total ? (C * x.value) / total : 0; const s = { ...x, len: Math.max(0, len - gap), off: -acc }; acc += len; return s }) }
})
const hoverSeg = ref<string | null>(null)

// ---------- qolganlar
const RC: Record<string, any> = { new: 'info', cooking: 'warn', ready: 'ok', done: 'neutral', delivered: 'accent' }
const LV: Record<string, [string, any]> = { critical: ['Kritik', 'danger'], low: ['Kam', 'warn'], watch: ['Kuzatuvda', 'neutral'] }
const BST: Record<string, [string, string]> = { ok: ['Yaxshi', 'ok'], warn: ['E\'tibor', 'warn'], bad: ['Yuqori', 'danger'], idle: ['Savdo yo\'q', 'muted'] }
const ago = (iso: string) => { const m = Math.round((Date.now() - new Date(iso).getTime()) / 60000); return m < 1 ? 'hozir' : m < 60 ? `${m} daq` : m < 1440 ? `${Math.floor(m / 60)} soat` : `${Math.floor(m / 1440)} kun` }
const QUICK = [
  { to: '/pos', label: 'Yangi buyurtma', icon: 'plus', mod: 'pos', perm: 'pos.sell', main: true },
  { to: '/kds', label: 'Oshxona ekrani', icon: 'play', mod: 'kds', perm: 'kds.view' },
  { to: '/inventory?tab=purchases', label: 'Ombor kirimi', icon: 'box', mod: 'inventory', perm: 'inventory.view' },
  { to: '/reports', label: 'Hisobotlar', icon: 'chart', mod: 'finance', perm: 'finance.view' },
  { to: '/catalog', label: 'Menyu', icon: 'book', mod: 'catalog', perm: 'catalog.view' },
  { to: '/tasks', label: 'Vazifa qo\'shish', icon: 'check', mod: 'tasks', perm: 'tasks.view' },
  { to: '/reservations', label: 'Bron', icon: 'calendar', mod: 'reservations', perm: 'reservations.view' },
  { to: '/users', label: 'Xodim qo\'shish', icon: 'users', mod: '', perm: 'core.users.manage' },
]
const quick = computed(() => QUICK.filter(q => (!q.mod || a.hasModule(q.mod)) && a.can(q.perm)).slice(0, 8))
const F = computed(() => D.value?.forecast)
const accessReq = computed(() => a.can('core.settings.edit') ? (a.me?.tenant.settings as any)?.platform?.access_request ?? null : null)
const fmtD = (x: string) => x.split('-').reverse().join('.')
const branchName = computed(() => D.value?.branches_list.find((b: any) => String(b.id) === branch.value)?.name)
</script>

<template>
  <div v-if="D" class="db" :class="{ busy: loading }">
    <!-- SARLAVHA -->
    <header class="top">
      <div class="hi">
        <h1>{{ hello }}, {{ D.user.first_name || 'hurmatli rahbar' }}! 👋</h1>
        <p>{{ D.tenant.name }} · {{ today }}, {{ dateLabel }}<template v-if="branchName"> · {{ branchName }}</template></p>
      </div>
      <div class="ctl">
        <select v-if="D.branches_list.length > 1" v-model="branch" class="sel" aria-label="Filial">
          <option value="">Barcha filiallar ({{ D.branches_list.length }})</option>
          <option v-for="b in D.branches_list" :key="b.id" :value="String(b.id)">{{ b.name }}</option>
        </select>
        <div class="seg" role="tablist" aria-label="Davr">
          <button v-for="p in D.period.periods" :key="p.code" type="button" role="tab" :aria-selected="period === p.code" :class="{ on: period === p.code }" @click="period = p.code">{{ p.label }}</button>
        </div>
      </div>
    </header>

    <!-- BO'LIMLAR: asosiy sahifadan har bo'limga bir bosishda -->
    <nav class="secs" aria-label="Bo'limlar">
      <RouterLink v-for="sc in sections" :key="sc.code" :to="sectionLink(sc)" class="sec-t" :style="{ '--sc': sc.color }">
        <span class="sec-e">{{ sc.emoji }}</span>
        <span class="sec-x"><b>{{ sc.title }}</b>
          <small v-if="secKpi(sc.code)" :class="secKpi(sc.code)?.tone" :title="`${secKpi(sc.code)?.label}: ${secKpi(sc.code)?.value}`"><strong>{{ secKpi(sc.code)?.value }}</strong> · {{ secKpi(sc.code)?.label }}</small>
          <small v-else>{{ sc.items.length > 1 ? `${sc.items.length} ta modul` : sc.desc.split(',')[0] }}</small></span>
      </RouterLink>
    </nav>

    <RouterLink v-if="accessReq" to="/support" class="setup req">🛟 <b>Platforma yordami panelingizga kirish uchun ruxsat so'rayapti</b> — {{ accessReq.reason }}. Ko'rib chiqish →</RouterLink>
    <RouterLink v-if="setupLeft.length" :to="setupLeft[0].route" class="setup">
      <UiIcon name="alert" :size="16" /> <b>Ishga tushirish: {{ (S?.checklist.length ?? 0) - setupLeft.length }}/{{ S?.checklist.length }} tayyor.</b>
      Keyingi qadam: {{ setupLeft[0].label }} <UiIcon name="chevron" :size="14" style="transform: rotate(-90deg)" />
    </RouterLink>

    <!-- BAYRAM VA OB-HAVO -->
    <section v-if="F && (F.alerts.length || F.weather.length || F.next)" class="r0" :class="{ solo: !F.weather.length }">
      <div v-if="F.alerts.length" class="alerts">
        <HolidayAlert v-for="al in F.alerts" :key="al.id" :a="al" :compact="F.alerts.length > 1" show-link />
      </div>
      <RouterLink v-else-if="F.next" :to="a.can('forecast.view') ? '/forecast' : '/'" class="nx">
        <span class="nx-i">📅</span>
        <span class="nx-b"><small>Keyingi bayram</small><b>{{ F.next.name.uz }}</b><span>{{ fmtD(F.next.date) }} · {{ F.next.days_left }} kun qoldi · savdo {{ F.next.uplift_percent >= 0 ? '+' : '' }}{{ F.next.uplift_percent }}%</span></span>
        <small class="nx-n">{{ F.next.prep_days }} kun oldin xarid rejasi tayyorlanadi</small>
      </RouterLink>
      <UiCard v-if="F.weather.length" :title="`Ob-havo · ${F.location}`" subtitle="Savdoga ta'siri prognozda hisobga olinadi">
        <template #actions><RouterLink v-if="a.can('forecast.view')" to="/forecast" class="lnk">Batafsil</RouterLink></template>
        <WeatherStrip :days="F.weather" :hints="2" />
      </UiCard>
    </section>

    <!-- KPI -->
    <section v-if="D.kpis.length" class="kpis">
      <component :is="k.route ? RouterLink : 'div'" v-for="(k, i) in D.kpis" :key="k.key" :to="k.route" class="kpi">
        <div class="kh"><span class="ki" :style="{ background: ICON_BG[i % 6] }"><UiIcon :name="k.icon || 'chart'" :size="18" /></span><span class="kl">{{ k.label }}</span></div>
        <b class="kv" :class="{ long: kval(k).length > 8 }" :title="k.money ? money(k.value) + ' so\'m' : ''">{{ kval(k) }}<small v-if="k.money"> so'm</small></b>
        <div class="kf">
          <span v-if="k.delta != null" class="kd" :class="kgood(k) ? 'good' : 'bad'">{{ k.delta > 0 ? '↑' : k.delta < 0 ? '↓' : '→' }} {{ kdelta(k) }}</span>
          <svg v-if="spark(k.spark)" class="sp" width="72" height="26" viewBox="0 0 72 26" aria-hidden="true">
            <path :d="spark(k.spark)!.d" fill="none" stroke="var(--series-mute)" stroke-width="2" stroke-linejoin="round" stroke-linecap="round" />
            <circle :cx="spark(k.spark)!.last[0]" :cy="spark(k.spark)!.last[1]" r="3.5" fill="var(--accent)" stroke="var(--surface)" stroke-width="2" />
          </svg>
        </div>
        <small class="kn">{{ k.prev != null ? `${k.prev_label}: ${k.money ? money(k.prev) : k.prev}` : k.norm }}<template v-if="k.norm && k.prev == null && k.ok != null"> {{ k.ok ? '✓' : '⚠' }}</template></small>
      </component>
    </section>

    <!-- 1-QATOR: dinamika · holat · top -->
    <div class="row r1">
      <UiCard v-if="D.series" :title="'Savdo dinamikasi'" :subtitle="`${D.period.label} · ${D.series.unit} bo'yicha${D.series.best ? ' · eng yuqori: ' + D.series.best : ''}`">
        <template #actions>
          <div class="seg sm"><button type="button" :class="{ on: metric === 'revenue' }" @click="metric = 'revenue'">Savdo</button><button type="button" :class="{ on: metric === 'orders' }" @click="metric = 'orders'">Buyurtmalar</button></div>
        </template>
        <div v-if="chart" class="chart" @mouseleave="hover = null">
          <svg :viewBox="`0 0 ${W} ${H}`" preserveAspectRatio="none" role="img" :aria-label="`${metric === 'revenue' ? 'Savdo' : 'Buyurtmalar'} dinamikasi`">
            <g v-for="tk in chart.ticks" :key="tk.v"><line :x1="PL" :x2="W - 4" :y1="tk.y" :y2="tk.y" stroke="var(--line-2)" stroke-width="1" /><text :x="PL - 8" :y="tk.y + 4" text-anchor="end" class="ax">{{ short(tk.v) }}</text></g>
            <g v-for="b in chart.bars" :key="b.i">
              <rect :x="b.x" :y="b.y" :width="b.w" :height="b.h" rx="4" :fill="(period === 'today' && b.p.label === nowLabel) || hover === b.i ? 'var(--accent)' : 'color-mix(in srgb, var(--accent) 55%, var(--surface))'" />
              <rect :x="PL + b.i * chart.bw" :y="PT" :width="chart.bw" :height="H - PB - PT" fill="transparent" @mouseenter="hover = b.i" @touchstart.passive="hover = b.i" />
              <text v-if="b.i % chart.every === 0" :x="b.x + b.w / 2" :y="H - 8" text-anchor="middle" class="ax">{{ b.p.label }}</text>
            </g>
          </svg>
          <div v-if="hp" class="tip" :style="{ left: `${((hp.x + hp.w / 2) / W) * 100}%`, top: `${(hp.y / H) * 100}%` }">
            <b>{{ hp.p.label }}</b><span>{{ money(hp.p.revenue) }} so'm</span><span>{{ hp.p.orders }} ta buyurtma</span>
          </div>
        </div>
        <UiEmpty v-else title="Bu davrda savdo yo'q" />
      </UiCard>

      <UiCard v-if="D.status" title="Buyurtmalar holati" :subtitle="D.period.label">
        <div class="dn">
          <svg viewBox="0 0 140 140" width="150" height="150" role="img" :aria-label="`Jami ${donut.total} buyurtma`">
            <circle cx="70" cy="70" :r="donut.R" fill="none" stroke="var(--surface-3)" stroke-width="16" />
            <circle v-for="sg in donut.segs" :key="sg.key" cx="70" cy="70" :r="donut.R" fill="none" :stroke="ST_COLOR[sg.key]"
                    :stroke-width="hoverSeg === sg.key ? 20 : 16" :stroke-dasharray="`${sg.len} ${donut.C}`" :stroke-dashoffset="sg.off"
                    transform="rotate(-90 70 70)" @mouseenter="hoverSeg = sg.key" @mouseleave="hoverSeg = null"><title>{{ sg.label }}: {{ sg.value }} ({{ sg.share }}%)</title></circle>
            <text x="70" y="68" text-anchor="middle" class="dt">{{ donut.total }}</text><text x="70" y="86" text-anchor="middle" class="ds">jami</text>
          </svg>
          <ul class="lg">
            <li v-for="it in D.status.items" :key="it.key" :class="{ dim: !it.value, hl: hoverSeg === it.key }" @mouseenter="hoverSeg = it.key" @mouseleave="hoverSeg = null">
              <i :style="{ background: ST_COLOR[it.key] }"></i><span>{{ it.label }}</span><b>{{ it.value }}</b><small>{{ it.share }}%</small>
            </li>
          </ul>
        </div>
        <RouterLink v-if="a.hasModule('kds')" to="/kds" class="more">Oshxona ekrani <UiIcon name="chevron" :size="14" style="transform: rotate(-90deg)" /></RouterLink>
      </UiCard>

      <UiCard v-if="D.top" title="Eng ko'p sotilganlar" :subtitle="D.period.label">
        <template #actions><RouterLink to="/reports?tab=menu" class="lnk">Barchasi</RouterLink></template>
        <ol class="top5">
          <li v-for="(p, i) in D.top" :key="p.name">
            <span class="n">{{ i + 1 }}</span>
            <span class="th"><img v-if="p.image" :src="p.image" alt="" loading="lazy" referrerpolicy="no-referrer" @error="p.image = null" /><span v-else>{{ p.name.slice(0, 1) }}</span></span>
            <span class="tn"><b>{{ p.name }}</b><span class="bar"><i :style="{ width: `${(p.qty / D.top[0].qty) * 100}%` }"></i></span></span>
            <span class="tq"><b>{{ p.qty }}</b><small>{{ p.share }}%</small></span>
          </li>
        </ol>
        <UiEmpty v-if="!D.top.length" title="Hali sotuv yo'q" />
      </UiCard>
    </div>

    <!-- 2-QATOR: filiallar · so'nggi buyurtmalar · ombor -->
    <div class="row r2">
      <UiCard v-if="D.branches" title="Filiallar ko'rsatkichlari" :subtitle="D.period.label">
        <template #actions><RouterLink to="/branches" class="lnk">Barchasi</RouterLink></template>
        <table class="tb">
          <thead><tr><th>Filial</th><th class="r">Savdo</th><th class="r">Chek</th><th class="r">Food cost</th></tr></thead>
          <tbody>
            <tr v-for="b in D.branches" :key="b.id" class="click" @click="branch = String(b.id)">
              <td class="w"><UiIcon name="store" :size="14" /> {{ b.name }}</td><td class="r">{{ money(b.revenue) }}</td><td class="r">{{ b.orders }}</td>
              <td class="r"><span class="st" :class="BST[b.state][1]" :title="BST[b.state][0]"><i></i>{{ b.food_cost }}%</span></td>
            </tr>
          </tbody>
        </table>
      </UiCard>

      <UiCard v-if="D.recent" title="So'nggi buyurtmalar">
        <template #actions><RouterLink to="/pos" class="lnk">Kassa</RouterLink></template>
        <table class="tb">
          <thead><tr><th>#</th><th>Qayerga</th><th class="r">Summa</th><th>Holat</th></tr></thead>
          <tbody>
            <tr v-for="o in D.recent" :key="o.id"><td class="nt"><b>{{ o.number }}</b><small>{{ o.time }}</small></td><td class="w">{{ o.where }}</td><td class="r">{{ money(o.total) }}</td><td><UiChip :tone="RC[o.status]">{{ o.status_label }}</UiChip></td></tr>
          </tbody>
        </table>
        <UiEmpty v-if="!D.recent.length" title="Buyurtma yo'q" />
      </UiCard>

      <UiCard v-if="D.stock" title="Omborda kam qolgan" :subtitle="D.stock.count ? `${D.stock.count} ta xomashyo buyurtma qilinishi kerak` : 'Hammasi yetarli'">
        <template #actions><RouterLink to="/inventory?tab=stock" class="lnk">Barchasi</RouterLink></template>
        <ul class="stk">
          <li v-for="s in D.stock.items" :key="s.id">
            <span class="sn"><b>{{ s.name }}</b><span class="bar"><i :class="s.level" :style="{ width: `${Math.min(100, s.ratio * 66)}%` }"></i></span></span>
            <span class="sq">{{ +s.stock.toFixed(2) }} {{ s.unit }}<small>min {{ +s.min.toFixed(1) }}</small></span>
            <span class="st" :class="LV[s.level][1]"><i></i>{{ LV[s.level][0] }}</span>
          </li>
        </ul>
        <p v-if="!D.stock.items.length" class="okmsg">✓ Hamma xomashyo yetarli</p>
      </UiCard>
    </div>

    <!-- 3-QATOR: tezkor amallar · vazifalar · faoliyat -->
    <div class="row r3">
      <UiCard title="Tezkor amallar">
        <div class="qa">
          <RouterLink v-for="q in quick" :key="q.to" :to="q.to" class="qb" :class="{ main: q.main }"><span><UiIcon :name="q.icon" :size="20" /></span>{{ q.label }}</RouterLink>
        </div>
      </UiCard>

      <UiCard v-if="D.tasks" title="Bugungi vazifalar" :subtitle="`${D.tasks.open} ta ochiq${D.tasks.overdue ? ` · ${D.tasks.overdue} ta kechikkan` : ''}`">
        <template #actions><RouterLink to="/tasks" class="lnk">Barchasi</RouterLink></template>
        <ul class="tk">
          <li v-for="tk in D.tasks.items" :key="tk.id" class="click" @click="router.push(`/tasks?open=${tk.id}`)">
            <span class="cb" :class="{ on: tk.done }"><UiIcon v-if="tk.done" name="check" :size="12" /></span>
            <span class="tt" :class="{ done: tk.done }">{{ tk.title }}<small v-if="tk.assignee">{{ tk.assignee }}</small></span>
            <span class="tm" :class="{ late: tk.overdue }">{{ tk.overdue ? '⚠ ' : '' }}{{ tk.time }}</span>
          </li>
        </ul>
        <p v-if="!D.tasks.items.length" class="okmsg">✓ Bugunga vazifa qolmadi</p>
      </UiCard>

      <UiCard title="So'nggi faoliyat">
        <ul class="act">
          <li v-for="(e, i) in D.activity" :key="i">
            <UiAvatar :name="e.who" :size="32" />
            <span class="at"><b>{{ e.who }}</b><small>{{ e.text }}</small></span>
            <span class="tm">{{ e.at ? ago(e.at) : '' }}</span>
          </li>
        </ul>
        <UiEmpty v-if="!D.activity.length" title="Hali faoliyat yo'q" />
      </UiCard>
    </div>
  </div>
</template>

<style scoped>
.secs { display: grid; grid-template-columns: repeat(auto-fill, minmax(210px, 1fr)); gap: 10px; }
.sec-t { display: flex; align-items: center; gap: 10px; padding: 12px; border-radius: 14px; background: var(--surface); border: 1px solid var(--line); text-decoration: none; color: var(--ink); min-width: 0; }
.sec-t:hover { border-color: var(--sc); box-shadow: 0 4px 14px rgba(0,0,0,.05); }
.sec-e { width: 42px; height: 42px; border-radius: 12px; display: grid; place-items: center; font-size: 22px; flex-shrink: 0; background: color-mix(in srgb, var(--sc) 13%, transparent); }
.sec-x { display: flex; flex-direction: column; min-width: 0; } .sec-x b { font-size: var(--fs-s); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; } .sec-x small { font-size: 11px; color: var(--muted); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.sec-x small strong { color: var(--ink); } .sec-x small.bad strong { color: var(--danger); } .sec-x small.warn strong { color: #B45309; }
@media (max-width: 640px) { .secs { grid-template-columns: 1fr 1fr; gap: 8px; } .sec-t { padding: 10px; } .sec-x b { white-space: normal; line-height: 1.2; } .sec-e { width: 36px; height: 36px; font-size: 19px; } }

.db { display: flex; flex-direction: column; gap: 16px; transition: opacity .2s; } .db.busy { opacity: .72; }
.top { display: flex; align-items: flex-end; justify-content: space-between; gap: 16px; flex-wrap: wrap; }
.hi h1 { margin: 0; font-family: var(--font-display); font-size: 28px; font-weight: 800; letter-spacing: -.02em; }
.hi p { margin: 4px 0 0; color: var(--muted); font-size: var(--fs-s); text-transform: none; }
.ctl { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
.sel { min-height: 40px; border: 1px solid var(--line); border-radius: 10px; padding: 0 12px; font: inherit; font-weight: 700; font-size: var(--fs-s); background: var(--surface); color: var(--ink); }
.seg { display: inline-flex; background: var(--surface-3); border-radius: 10px; padding: 3px; gap: 2px; }
.seg button { border: 0; background: transparent; padding: 0 12px; min-height: 34px; border-radius: 8px; font: inherit; font-weight: 700; font-size: var(--fs-s); color: var(--muted); cursor: pointer; white-space: nowrap; }
.seg button.on { background: var(--ink); color: var(--surface); }
.seg.sm button { min-height: 28px; padding: 0 10px; font-size: var(--fs-xs); } .seg.sm button.on { background: var(--surface); color: var(--ink); box-shadow: 0 1px 3px rgba(0,0,0,.08); }
.setup.req { background: #DBE7FF; color: #1E3A8A; }
.setup { display: flex; align-items: center; gap: 8px; padding: 10px 14px; border-radius: 12px; background: var(--warn-tint); color: var(--warn-ink); text-decoration: none; font-size: var(--fs-s); flex-wrap: wrap; }

.r0 { display: grid; grid-template-columns: minmax(0, 1.15fr) minmax(0, 1fr); gap: 16px; align-items: stretch; } .r0.solo { grid-template-columns: minmax(0, 1fr); }
.r0 > :deep(.ui-card) { min-width: 0; }
.nx { display: flex; flex-direction: column; justify-content: center; gap: 10px; padding: 16px 18px; border-radius: 16px; background: var(--surface); border: 1px solid var(--line); color: var(--ink); text-decoration: none; min-width: 0; }
.nx:hover { border-color: var(--accent); }
.nx-i { font-size: 28px; } .nx-b { display: flex; flex-direction: column; gap: 2px; } .nx-b small, .nx-n { font-size: var(--fs-xs); color: var(--muted); font-weight: 700; }
.nx-b b { font-family: var(--font-display); font-size: var(--fs-xl); font-weight: 800; } .nx-b span { font-size: var(--fs-s); color: var(--ink-2); }
.alerts { display: flex; flex-direction: column; gap: 10px; min-width: 0; } .alerts > * { flex: 1; }
.kpis { display: grid; grid-template-columns: repeat(6, minmax(0, 1fr)); gap: 12px; }
.kpi { background: var(--surface); border: 1px solid var(--line); border-radius: 16px; padding: 14px; display: flex; flex-direction: column; gap: 6px; min-width: 0; color: var(--ink); text-decoration: none; transition: border-color .15s, transform .15s; }
a.kpi:hover { border-color: var(--accent); transform: translateY(-1px); }
.kh { display: flex; align-items: center; gap: 10px; }
.ki { width: 36px; height: 36px; border-radius: 10px; display: grid; place-items: center; color: #fff; flex-shrink: 0; }
.kl { font-size: var(--fs-s); font-weight: 700; color: var(--ink-2); }
.kv { font-family: var(--font-display); font-size: 22px; font-weight: 800; letter-spacing: -.02em; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.kv.long { font-size: 19px; } .kv.long small { display: none; }
.kv small { font-size: 13px; font-weight: 700; color: var(--muted); }
.kf { display: flex; align-items: center; justify-content: space-between; gap: 6px; min-height: 26px; }
.kd { font-size: var(--fs-s); font-weight: 800; white-space: nowrap; } .kd.good { color: var(--ok); } .kd.bad { color: var(--danger); }
.sp { flex-shrink: 0; margin-left: auto; }
.kn { font-size: var(--fs-xs); color: var(--muted); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }

.row { display: grid; gap: 16px; align-items: stretch; }
.r1 { grid-template-columns: minmax(0, 1.55fr) minmax(0, 1fr) minmax(0, 1.05fr); }
.r2, .r3 { grid-template-columns: repeat(3, minmax(0, 1fr)); }
.row > :deep(.ui-card) { min-width: 0; }
.lnk { color: var(--accent); font-weight: 700; font-size: var(--fs-s); text-decoration: none; white-space: nowrap; }
.more { display: inline-flex; align-items: center; gap: 4px; color: var(--accent); font-weight: 700; font-size: var(--fs-s); text-decoration: none; align-self: flex-start; }

.chart { position: relative; width: 100%; }
.chart svg { width: 100%; height: 240px; display: block; }
.ax { font-size: 11px; fill: var(--muted); font-family: var(--font-body, inherit); }
.tip { position: absolute; transform: translate(-50%, calc(-100% - 8px)); background: var(--ink); color: var(--surface); border-radius: 8px; padding: 6px 10px; font-size: 12px; display: flex; flex-direction: column; pointer-events: none; white-space: nowrap; box-shadow: var(--shadow); }
.tip b { font-size: 12px; }

.dn { display: flex; align-items: center; gap: 16px; flex-wrap: wrap; justify-content: center; }
.dn circle { transition: stroke-width .15s; cursor: pointer; }
.dt { font-family: var(--font-display); font-size: 26px; font-weight: 800; fill: var(--ink); } .ds { font-size: 11px; fill: var(--muted); }
.lg { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 6px; flex: 1; min-width: 170px; }
.lg li { display: grid; grid-template-columns: 12px 1fr auto 44px; gap: 8px; align-items: center; font-size: var(--fs-s); padding: 3px 6px; border-radius: 6px; }
.lg li.hl { background: var(--surface-2); } .lg li.dim { opacity: .5; }
.lg i { width: 12px; height: 12px; border-radius: 3px; } .lg b { font-variant-numeric: tabular-nums; } .lg small { color: var(--muted); text-align: right; }

.top5 { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 10px; }
.top5 li { display: grid; grid-template-columns: 18px 40px minmax(0, 1fr) auto; gap: 10px; align-items: center; }
.top5 .n { font-weight: 800; color: var(--muted); font-size: var(--fs-s); }
.th { width: 40px; height: 40px; border-radius: 10px; overflow: hidden; background: var(--surface-3); display: grid; place-items: center; font-weight: 800; color: var(--muted); }
.th img { width: 100%; height: 100%; object-fit: cover; }
.tn { display: flex; flex-direction: column; gap: 5px; min-width: 0; } .tn b { font-size: var(--fs-s); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.bar { height: 6px; border-radius: 99px; background: var(--surface-3); overflow: hidden; display: block; }
.bar i { display: block; height: 100%; border-radius: 99px; background: var(--series-2); }
.tq { display: flex; flex-direction: column; align-items: flex-end; } .tq b { font-variant-numeric: tabular-nums; } .tq small { color: var(--muted); font-size: var(--fs-xs); }

.tb { width: 100%; border-collapse: collapse; font-size: var(--fs-s); }
.tb th { text-align: left; font-size: var(--fs-xs); color: var(--muted); font-weight: 700; padding: 6px 6px; border-bottom: 1px solid var(--line); white-space: nowrap; }
.tb td { padding: 9px 6px; border-bottom: 1px solid var(--line-2); white-space: nowrap; font-variant-numeric: tabular-nums; }
.tb tr:last-child td { border-bottom: 0; } .nt b { display: block; } .nt small { color: var(--muted); font-size: var(--fs-xs); } .tb .r { text-align: right; } .tb .w { max-width: 150px; overflow: hidden; text-overflow: ellipsis; }
.click { cursor: pointer; } .tb tr.click:hover td { background: var(--surface-2); }
.st { display: inline-flex; align-items: center; gap: 6px; font-size: var(--fs-xs); font-weight: 700; white-space: nowrap; }
.st i { width: 8px; height: 8px; border-radius: 50%; background: currentColor; }
.st.ok { color: var(--ok); } .st.warn { color: var(--warn-ink); } .st.danger { color: var(--danger); } .st.muted, .st.neutral { color: var(--muted); }

.stk { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 12px; }
.stk li { display: grid; grid-template-columns: minmax(0, 1fr) auto 92px; gap: 10px; align-items: center; }
.sn { display: flex; flex-direction: column; gap: 5px; min-width: 0; } .sn b { font-size: var(--fs-s); }
.bar i.critical { background: var(--danger); } .bar i.low { background: var(--warn); } .bar i.watch { background: var(--series-mute); }
.sq { font-size: var(--fs-s); font-weight: 700; text-align: right; display: flex; flex-direction: column; } .sq small { color: var(--muted); font-weight: 500; font-size: var(--fs-xs); }
.okmsg { margin: 0; color: var(--ok); font-weight: 700; font-size: var(--fs-s); }

.qa { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px; }
.qb { display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 8px; min-height: 88px; padding: 10px 6px; border-radius: 14px; background: var(--surface-2); border: 1px solid var(--line-2); color: var(--ink); text-decoration: none; font-weight: 700; font-size: var(--fs-xs); text-align: center; line-height: 1.2; }
.qb span { width: 38px; height: 38px; border-radius: 12px; display: grid; place-items: center; background: var(--surface); color: var(--accent); }
.qb:hover { border-color: var(--accent); }
.qb.main { background: var(--accent); color: var(--accent-ink); border-color: var(--accent); } .qb.main span { background: color-mix(in srgb, var(--accent-ink) 18%, transparent); color: var(--accent-ink); }

.tk, .act { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; }
.tk li { display: flex; align-items: center; gap: 10px; padding: 8px 4px; border-bottom: 1px solid var(--line-2); border-radius: 6px; } .tk li:last-child { border-bottom: 0; }
.tk li:hover { background: var(--surface-2); }
.cb { width: 20px; height: 20px; border-radius: 6px; border: 2px solid var(--line); display: grid; place-items: center; color: #fff; flex-shrink: 0; } .cb.on { background: var(--series-1); border-color: var(--series-1); }
.tt { flex: 1; min-width: 0; font-size: var(--fs-s); font-weight: 600; display: flex; flex-direction: column; } .tt small { color: var(--muted); font-weight: 500; font-size: var(--fs-xs); }
.tt.done { text-decoration: line-through; color: var(--muted); }
.tm { font-size: var(--fs-xs); color: var(--muted); white-space: nowrap; font-variant-numeric: tabular-nums; } .tm.late { color: var(--danger); font-weight: 700; }
.act li { display: flex; align-items: center; gap: 10px; padding: 7px 0; border-bottom: 1px solid var(--line-2); } .act li:last-child { border-bottom: 0; }
.at { flex: 1; min-width: 0; display: flex; flex-direction: column; } .at b { font-size: var(--fs-s); } .at small { color: var(--muted); font-size: var(--fs-xs); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }

@media (max-width: 1400px) { .kpis { grid-template-columns: repeat(3, minmax(0, 1fr)); } .r1 { grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); } .r1 > :first-child { grid-column: 1 / -1; } }
@media (max-width: 1100px) { .r0 { grid-template-columns: minmax(0, 1fr); } .r2, .r3 { grid-template-columns: 1fr 1fr; } .r2 > :first-child, .r3 > :first-child { grid-column: 1 / -1; } }
@media (max-width: 720px) {
  .hi h1 { font-size: 22px; } .ctl { width: 100%; } .seg { width: 100%; overflow-x: auto; } .seg button { flex: 1; padding: 0 8px; } .sel { width: 100%; }
  .kpis { grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; } .kv { font-size: 20px; } .kpi { padding: 12px; } .ki { width: 30px; height: 30px; } .sp { display: none; }
  .r1, .r2, .r3 { grid-template-columns: 1fr; } .r1 > :first-child { grid-column: auto; } .r2 > :first-child, .r3 > :first-child { grid-column: auto; }
  .chart svg { height: 200px; } .qa { grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 6px; } .qb { min-height: 76px; font-size: 11px; }
}
</style>
'@

Put 'frontend\apps\admin\src\views\SectionView.vue' @'
<script setup lang="ts">
/** Bo'lim sahifasi: tepada shu bo'limning paneli (jonli ko'rsatkichlar), keyin modullar katta kartalarda; pastida — asosiy sahifaga qaytish. */
import { computed, onBeforeUnmount, onMounted } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import { UiButton, UiEmpty, UiIcon, t } from '@restopos/ui'
import { useUi } from '@/stores/ui'
import { useNav, useSectionStats } from '@/nav/sections'

const route = useRoute(), router = useRouter(), ui = useUi()
const { sections, sectionLink } = useNav()
const S = computed(() => sections.value.find(s => s.code === route.params.code))
const others = computed(() => sections.value.filter(s => s.code !== route.params.code))
const { stats, load } = useSectionStats()
const kpis = computed(() => stats.value?.[String(route.params.code)] ?? [])
let timer: number | undefined
onMounted(() => { load(true); timer = window.setInterval(() => { if (!document.hidden) load(true) }, 60_000) })
onBeforeUnmount(() => clearInterval(timer))
</script>

<template>
  <div class="sv">
    <template v-if="S">
      <header class="hd" :style="{ '--sc': S.color }">
        <span class="em">{{ S.emoji }}</span>
        <div><h2>{{ S.title }}</h2><p>{{ S.desc }}</p></div>
      </header>
      <section v-if="kpis.length" class="kpis" :style="{ '--sc': S.color }" aria-label="Bo'lim ko'rsatkichlari">
        <RouterLink v-for="k in kpis" :key="k.label" :to="k.route || '/'" class="kpi" :class="k.tone">
          <span class="ki">{{ k.icon }}</span>
          <span class="kt"><small>{{ k.label }}</small><b>{{ k.value }}</b><em>{{ k.hint }}</em></span>
        </RouterLink>
      </section>
      <h3 class="mh">Bo'lim modullari</h3>
      <div class="grid">
        <RouterLink v-for="m in S.items" :key="m.route" :to="m.route" class="card" :style="{ '--sc': S.color }">
          <span class="ic"><UiIcon :name="m.icon" :size="24" /></span>
          <span class="tx"><b>{{ t(m.label, ui.lang) }}</b><small>{{ m.desc }}</small></span>
          <UiIcon name="chevron" :size="16" class="go" />
        </RouterLink>
      </div>
      <UiButton variant="ghost" class="home" @click="router.push('/')"><UiIcon name="home" :size="16" /> Asosiy sahifaga qaytish</UiButton>
      <div v-if="others.length" class="oth">
        <small>Boshqa bo'limlar</small>
        <div class="chips"><RouterLink v-for="o in others" :key="o.code" :to="sectionLink(o)" :style="{ '--sc': o.color }">{{ o.emoji }} {{ o.title }}</RouterLink></div>
      </div>
    </template>
    <UiEmpty v-else title="Bo'lim topilmadi" text="Bu bo'lim yoqilmagan yoki sizga ruxsat berilmagan.">
      <UiButton variant="brand" @click="router.push('/')">Asosiy sahifa</UiButton>
    </UiEmpty>
  </div>
</template>

<style scoped>
.sv { display: flex; flex-direction: column; gap: 18px; max-width: 1100px; }
.hd { display: flex; gap: 16px; align-items: center; padding: 18px 20px; border-radius: 18px; background: color-mix(in srgb, var(--sc) 9%, var(--surface)); border: 1px solid color-mix(in srgb, var(--sc) 25%, transparent); }
.em { width: 60px; height: 60px; border-radius: 16px; display: grid; place-items: center; font-size: 32px; background: var(--surface); flex-shrink: 0; }
h2 { margin: 0; font-family: var(--font-display); font-size: 24px; } p { margin: 4px 0 0; color: var(--ink-2); font-size: var(--fs-s); }
.kpis { display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 10px; }
.kpi { display: flex; gap: 12px; align-items: center; padding: 14px; border-radius: 14px; background: var(--surface); border: 1px solid var(--line); text-decoration: none; color: var(--ink); min-width: 0; }
.kpi:hover { border-color: var(--sc); }
.ki { width: 40px; height: 40px; border-radius: 12px; display: grid; place-items: center; font-size: 20px; flex-shrink: 0; background: color-mix(in srgb, var(--sc) 12%, transparent); }
.kt { display: flex; flex-direction: column; min-width: 0; } .kt small { font-size: var(--fs-xs); font-weight: 700; color: var(--muted); }
.kt b { font-family: var(--font-display); font-size: 20px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.kt em { font-style: normal; font-size: 11px; color: var(--muted); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.kpi.ok { border-left: 4px solid var(--ok); } .kpi.warn { border-left: 4px solid #F59E0B; } .kpi.bad { border-left: 4px solid var(--danger); } .kpi.bad b { color: var(--danger); }
.mh { margin: 4px 0 -6px; font-size: var(--fs-s); text-transform: uppercase; letter-spacing: .05em; color: var(--muted); }
.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 12px; }
.card { display: flex; align-items: center; gap: 14px; padding: 16px; background: var(--surface); border: 1px solid var(--line); border-radius: 16px; text-decoration: none; color: var(--ink); min-height: 88px; transition: border-color .15s, transform .15s; }
.card:hover { border-color: var(--sc); transform: translateY(-1px); box-shadow: 0 6px 18px rgba(0,0,0,.06); }
.ic { width: 52px; height: 52px; border-radius: 14px; display: grid; place-items: center; flex-shrink: 0; background: color-mix(in srgb, var(--sc) 14%, transparent); color: var(--sc); }
.tx { flex: 1; display: flex; flex-direction: column; gap: 3px; min-width: 0; } .tx b { font-size: var(--fs-m); } .tx small { color: var(--muted); font-size: var(--fs-s); line-height: 1.35; }
.go { transform: rotate(-90deg); color: var(--muted); flex-shrink: 0; }
.home { align-self: flex-start; }
.oth small { display: block; font-size: 11px; font-weight: 800; text-transform: uppercase; letter-spacing: .05em; color: var(--muted); margin-bottom: 8px; }
.chips { display: flex; flex-wrap: wrap; gap: 6px; }
.chips a { padding: 8px 12px; border-radius: 99px; border: 1px solid var(--line); background: var(--surface); color: var(--ink); text-decoration: none; font-size: var(--fs-s); font-weight: 700; }
.chips a:hover { border-color: var(--sc); color: var(--sc); }
@media (max-width: 640px) { .kpis { grid-template-columns: 1fr 1fr; gap: 8px; } .kpi { padding: 10px; gap: 8px; } .ki { width: 32px; height: 32px; font-size: 16px; } .kt b { font-size: 16px; } .grid { grid-template-columns: minmax(0, 1fr); } .hd { padding: 14px; } .em { width: 48px; height: 48px; font-size: 26px; } h2 { font-size: 20px; } .home { align-self: stretch; } }
</style>
'@

Put 'frontend\apps\admin\src\views\TrainingView.vue' @'
<script setup lang="ts">
/**
 * O'qitish va komplayens — bosh sahifa.
 * Har xodim: «Mening o'qishim». Egasi/menejer qo'shimcha: kurslar, topshiriqlar, standartlar, hisobot.
 */
import { onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api } from '@restopos/api'
import { UiIcon } from '@restopos/ui'
import TrMy from '@/components/training/TrMy.vue'
import TrCourses from '@/components/training/TrCourses.vue'
import TrAssignments from '@/components/training/TrAssignments.vue'
import TrStandards from '@/components/training/TrStandards.vue'
import TrReport from '@/components/training/TrReport.vue'
import '@/components/training/tr.css'

type Tab = 'my' | 'courses' | 'assignments' | 'standards' | 'report'
const route = useRoute(), router = useRouter()
const meta = ref<any>(null)
const courses = ref<any[]>([])
const tab = ref<Tab>((route.query.tab as Tab) || 'my')
watch(tab, (v) => router.replace({ query: { tab: v } }))
onMounted(async () => {
  meta.value = await api.get('/training/meta')
  if (meta.value.can.manage) courses.value = await api.get('/training/courses')
  if (tab.value !== 'my' && !meta.value.can.review) tab.value = 'my'
  // rahbar uchun ochilganda — jamoa hisobotidan boshlanadi (o'zining kursi bo'lmasa «Mening o'qishim» bo'sh ko'rinadi)
  else if (!route.query.tab && meta.value.can.review) tab.value = 'report'
})
</script>

<template>
  <div v-if="meta" class="tv">
    <nav v-if="meta.can.review" class="tr-seg top">
      <button :class="{ on: tab === 'my' }" @click="tab = 'my'"><UiIcon name="play" :size="15" /> Mening o'qishim</button>
      <button v-if="meta.can.manage" :class="{ on: tab === 'courses' }" @click="tab = 'courses'"><UiIcon name="book" :size="15" /> Kurslar</button>
      <button :class="{ on: tab === 'assignments' }" @click="tab = 'assignments'"><UiIcon name="camera" :size="15" /> Topshiriqlar</button>
      <button v-if="meta.can.manage" :class="{ on: tab === 'standards' }" @click="tab = 'standards'"><UiIcon name="shield" :size="15" /> Standartlar</button>
      <button :class="{ on: tab === 'report' }" @click="tab = 'report'"><UiIcon name="chart" :size="15" /> Hisobot</button>
    </nav>
    <TrMy v-if="tab === 'my'" />
    <TrCourses v-else-if="tab === 'courses'" :meta="meta" />
    <TrAssignments v-else-if="tab === 'assignments'" :meta="meta" :courses="courses" />
    <TrStandards v-else-if="tab === 'standards'" :meta="meta" />
    <TrReport v-else-if="tab === 'report'" />
  </div>
</template>

<style scoped>
.tv { display: flex; flex-direction: column; gap: 16px; }
.top { align-self: flex-start; max-width: 100%; }
@media (max-width: 600px) { .top { align-self: stretch; } .top button { flex: none; } }
</style>
'@

Write-Host ""
Write-Host "Tayyor: 13 ta fayl yangilandi." -ForegroundColor Green
Write-Host "Endi:" -ForegroundColor Yellow
Write-Host "  cd backend" -ForegroundColor Yellow
Write-Host "  ..\.venv\Scripts\python.exe manage.py demo_live --all --on" -ForegroundColor Yellow
Write-Host "  cd ..\frontend" -ForegroundColor Yellow
Write-Host "  pnpm --filter admin build" -ForegroundColor Yellow
Write-Host "  cd .." -ForegroundColor Yellow
Write-Host "  (serverni qayta ishga tushiring, brauzerda Ctrl+Shift+R)" -ForegroundColor Yellow
Write-Host "  git add -A" -ForegroundColor Yellow
Write-Host "  git commit -m 'v18 Jonli demo'" -ForegroundColor Yellow
Write-Host "  git push" -ForegroundColor Yellow
