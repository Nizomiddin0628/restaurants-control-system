# RestoPOS v12 — Bayram va ob-havo prognozi (ogohlantirish, xarid rejasi)
# Ishga tushirish (ildiz papkada!): PS C:\Users\xalil\Desktop\restaurants\restopos>
#   powershell -ExecutionPolicy Bypass -File .\restopos-v12-bayram-obhavo.ps1
$ErrorActionPreference = 'Stop'
if (-not (Test-Path "$PWD\backend\manage.py") -or -not (Test-Path "$PWD\frontend\apps\admin")) {
  Write-Host "XATO: skriptni restopos ildiz papkasida ishga tushiring (PS C:\Users\xalil\Desktop\restaurants\restopos>)." -ForegroundColor Red
  exit 1
}
if (-not (Test-Path "$PWD\backend\modules\hr\kpi.py")) {
  Write-Host "XATO: avval v11 (HR) kerak — git pull qiling." -ForegroundColor Red
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


@api.get("/me", auth=auth, tags=["auth"])
def me(request):
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
    return overview(request, period, branch_id)


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
from modules.payments.api import router as payments_router  # noqa: E402
from modules.pos.api import router as pos_router  # noqa: E402
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


@api.get("/health", tags=["system"])
def health(request):
    return {"ok": True, "tenant": request.tenant.schema_name, "modules": request.tenant.enabled_modules}
'@

Put 'backend\api\dashboard.py' @'
"""
Boshqaruv paneli (menejer ko'zi) — /api/v1/dashboard/overview?period=today|yesterday|week|month|year&branch_id=

Bir so'rovda hammasi: KPI (o'tgan davrga nisbatan), savdo dinamikasi, buyurtmalar holati, top taomlar,
filiallar, so'nggi buyurtmalar, ombor ogohlantirishlari, bugungi vazifalar, so'nggi faoliyat.
Modul o'chiq bo'lsa — o'sha blok bo'sh (None) qaytadi, sahifa uni ko'rsatmaydi.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Optional

from django.db.models import Count, F, Q, Sum
from django.db.models.functions import ExtractHour, TruncDate, TruncMonth
from django.utils import timezone

PERIODS = {"today": "Bugun", "yesterday": "Kecha", "week": "7 kun", "month": "Shu oy", "year": "Shu yil"}
TYPE_UZ = {"dine_in": "Zalda", "takeaway": "Olib ketish", "delivery": "Yetkazish"}
SOURCE_UZ = {"pos": "Kassa", "telegram": "Telegram", "site": "Sayt", "app": "Ilova"}


def _delta(cur, prev):
    return round(100 * (cur - prev) / prev, 1) if prev else None


def _range(period: str, today: date) -> tuple[date, date, date, date]:
    """(boshi, oxiri, oldingi boshi, oldingi oxiri) — adolatli taqqoslash uchun teng uzunlik."""
    if period == "yesterday":
        d = today - timedelta(days=1)
        return d, d, d - timedelta(days=1), d - timedelta(days=1)
    if period == "week":
        s = today - timedelta(days=6)
        return s, today, s - timedelta(days=7), s - timedelta(days=1)
    if period == "month":
        s = today.replace(day=1)
        ps = (s - timedelta(days=1)).replace(day=1)
        pe = min(ps + timedelta(days=(today - s).days), s - timedelta(days=1))
        return s, today, ps, pe
    if period == "year":
        s = today.replace(month=1, day=1)
        ps = s.replace(year=s.year - 1)
        return s, today, ps, today.replace(year=today.year - 1)
    return today, today, today - timedelta(days=1), today - timedelta(days=1)


def overview(request, period: str = "today", branch_id: Optional[int] = None) -> dict:
    t = request.tenant
    u = request.auth
    period = period if period in PERIODS else "today"
    today = timezone.localdate()
    now = timezone.now()
    start, end, pstart, pend = _range(period, today)
    out: dict = {
        "user": {"first_name": (u.full_name or "").split(" ")[0] or "", "full_name": u.full_name},
        "tenant": {"name": t.name},
        "period": {"code": period, "label": PERIODS[period], "start": start.isoformat(), "end": end.isoformat(),
                   "periods": [{"code": k, "label": v} for k, v in PERIODS.items()]},
        "branches_list": [], "kpis": [], "series": None, "status": None, "top": None, "branches": None,
        "recent": None, "stock": None, "tasks": None, "activity": [], "forecast": None,
    }
    from core.models import Branch
    out["branches_list"] = [{"id": b.pk, "name": b.name} for b in Branch.objects.filter(deleted_at__isnull=True, is_active=True)]

    if t.module_enabled("pos"):
        _sales(out, period, start, end, pstart, pend, today, now, branch_id)
    if t.module_enabled("inventory"):
        _stock(out)
    if t.module_enabled("tasks"):
        _tasks(out, now)
    if t.module_enabled("forecast"):
        _forecast(out, t)
    _activity(out, t, branch_id)
    return out


# ------------------------------------------------------------------ savdo
def _sales(out, period, start, end, pstart, pend, today, now, branch_id):
    from modules.finance.reports import pnl
    from modules.pos.models import Order, OrderItem, OrderStatus

    def paid(s, e):
        qs = Order.objects.filter(status=OrderStatus.PAID, paid_at__date__gte=s, paid_at__date__lte=e)
        return qs.filter(branch_id=branch_id) if branch_id else qs

    cur = paid(start, end)
    prev = paid(pstart, pend)
    if period == "today":                       # bugun hozirgacha ↔ kecha xuddi shu soatgacha
        prev = prev.filter(paid_at__lte=now - timedelta(days=1))
    a = cur.aggregate(r=Sum("total"), n=Count("id"), c=Sum("cost_total"))
    b = prev.aggregate(r=Sum("total"), n=Count("id"), c=Sum("cost_total"))
    rev, n, cogs = int(a["r"] or 0), a["n"] or 0, int(a["c"] or 0)
    prev_rev, prev_n, prev_cogs = int(b["r"] or 0), b["n"] or 0, int(b["c"] or 0)
    avg, prev_avg = (rev // n if n else 0), (prev_rev // prev_n if prev_n else 0)
    fc = round(100 * cogs / rev, 1) if rev else 0.0
    pfc = round(100 * prev_cogs / prev_rev, 1) if prev_rev else None
    # mehnat va sof foyda — kamida oylik kesimda ma'noli (bir kunlik oylik ulushi noto'g'ri tuyuladi)
    ms = start if period in ("month", "year") else today.replace(day=1)
    m = pnl(ms, end, branch_id)
    if period == "year":
        pm = pnl(pstart, pend, branch_id)
    else:
        _, _, mps, mpe = _range("month", end)
        pm = pnl(mps, mpe, branch_id)

    # 7 nuqtali sparkline (kunlik) — oxirgi nuqta = joriy kun
    spark_s = end - timedelta(days=6)
    daily = {r["d"]: r for r in paid(spark_s, end).annotate(d=TruncDate("paid_at")).values("d")
             .annotate(r=Sum("total"), n=Count("id"), c=Sum("cost_total"))}
    days = [spark_s + timedelta(days=i) for i in range(7)]
    sp_rev = [int((daily.get(d) or {}).get("r") or 0) for d in days]
    sp_n = [int((daily.get(d) or {}).get("n") or 0) for d in days]
    sp_avg = [(r // k if k else 0) for r, k in zip(sp_rev, sp_n, strict=True)]
    sp_fc = [round(100 * int((daily.get(d) or {}).get("c") or 0) / r, 1) if r else 0 for d, r in zip(days, sp_rev, strict=True)]
    label_prev = {"today": "Kecha shu vaqtgacha", "yesterday": "Avvalgi kun", "week": "Oldingi 7 kun", "month": "O'tgan oy shu kungacha", "year": "O'tgan yil"}[period]
    out["kpis"] = [
        {"key": "revenue", "label": "Savdo", "value": rev, "money": True, "delta": _delta(rev, prev_rev), "prev": prev_rev, "prev_label": label_prev, "spark": sp_rev, "icon": "receipt", "route": "/reports"},
        {"key": "orders", "label": "Buyurtmalar", "value": n, "delta": _delta(n, prev_n), "prev": prev_n, "prev_label": label_prev, "spark": sp_n, "icon": "list", "route": "/pos"},
        {"key": "avg_check", "label": "O'rtacha chek", "value": avg, "money": True, "delta": _delta(avg, prev_avg), "prev": prev_avg, "prev_label": label_prev, "spark": sp_avg, "icon": "chart"},
        {"key": "food_cost", "label": "Food cost", "value": fc, "percent": True, "delta": round(fc - pfc, 1) if pfc is not None else None,
         "lower_is_better": True, "norm": "Me'yor: 28–35%", "ok": 0 < fc <= 35, "spark": sp_fc, "icon": "box", "route": "/inventory"},
        {"key": "labor", "label": "Mehnat xarajati", "value": m["labor_percent"], "percent": True, "delta": round(m["labor_percent"] - pm["labor_percent"], 1) if pm["revenue"] and pm["labor"] else None,
         "lower_is_better": True, "norm": "Me'yor: ≤ 25% · " + ("oy" if period not in ("year",) else "yil"), "ok": m["labor_percent"] <= 25, "icon": "users", "route": "/hr"},
        {"key": "net", "label": "Sof foyda", "value": m["net_profit"], "money": True, "delta": _delta(m["net_profit"], pm["net_profit"]) if pm["net_profit"] > 0 and pm["labor"] else None,
         "norm": f"Marja: {m['net_margin_percent']}% · " + ("oy" if period != "year" else "yil"), "ok": m["net_margin_percent"] >= 10, "icon": "chart", "route": "/reports"},
    ]

    # savdo dinamikasi: kun ichida — soatlar, hafta/oy — kunlar, yil — oylar
    if period in ("today", "yesterday"):
        rows = {r["h"]: r for r in cur.annotate(h=ExtractHour("paid_at")).values("h").annotate(r=Sum("total"), n=Count("id"))}
        hours = [h for h in range(8, 24)] + [h for h in range(0, 3) if rows.get(h)]
        pts = [{"label": f"{h:02d}:00", "revenue": int((rows.get(h) or {}).get("r") or 0), "orders": (rows.get(h) or {}).get("n") or 0} for h in hours]
    elif period == "year":
        rows = {r["m"].date() if isinstance(r["m"], datetime) else r["m"]: r for r in cur.annotate(m=TruncMonth("paid_at")).values("m").annotate(r=Sum("total"), n=Count("id"))}
        mon = ["Yan", "Fev", "Mar", "Apr", "May", "Iyun", "Iyul", "Avg", "Sen", "Okt", "Noy", "Dek"]
        pts = []
        for i in range(1, today.month + 1):
            k = date(today.year, i, 1)
            r = next((v for kk, v in rows.items() if (kk.year, kk.month) == (k.year, k.month)), None)
            pts.append({"label": mon[i - 1], "revenue": int((r or {}).get("r") or 0), "orders": (r or {}).get("n") or 0})
    else:
        rows = {r["d"]: r for r in cur.annotate(d=TruncDate("paid_at")).values("d").annotate(r=Sum("total"), n=Count("id"))}
        pts = [{"label": f"{d:%d.%m}", "revenue": int((rows.get(d) or {}).get("r") or 0), "orders": (rows.get(d) or {}).get("n") or 0}
               for d in (start + timedelta(days=i) for i in range((end - start).days + 1))]
    best = max(pts, key=lambda p: p["revenue"]) if pts else None
    out["series"] = {"points": pts, "unit": "soat" if period in ("today", "yesterday") else "kun" if period != "year" else "oy",
                     "best": best["label"] if best and best["revenue"] else None}

    # buyurtmalar holati (davr ichida yaratilganlar)
    made = Order.objects.filter(created_at__date__gte=start, created_at__date__lte=end)
    if branch_id:
        made = made.filter(branch_id=branch_id)
    st = {"new": 0, "cooking": 0, "ready": 0, "done": 0, "cancelled": 0}
    st["done"] = made.filter(status=OrderStatus.PAID).count()
    st["cancelled"] = made.filter(status=OrderStatus.CANCELLED).count()
    open_ids = list(made.filter(status=OrderStatus.OPEN).values_list("id", flat=True))
    kds = {}
    if open_ids and out is not None:
        try:
            from modules.kds.models import Ticket
            for oid, s in Ticket.objects.filter(order_id__in=open_ids).values_list("order_id", "status"):
                rank = {"new": 0, "cooking": 1, "ready": 2, "served": 3, "cancelled": -1}.get(s, 0)
                kds[oid] = min(kds.get(oid, 9), rank)
        except Exception:
            pass
    for oid in open_ids:
        r = kds.get(oid, 0)
        st["ready" if r >= 2 else "cooking" if r == 1 else "new"] += 1
    total = sum(st.values())
    labels = {"done": "Yakunlangan", "cooking": "Tayyorlanmoqda", "new": "Yangi", "ready": "Tayyor", "cancelled": "Bekor qilingan"}
    out["status"] = {"total": total, "items": [{"key": k, "label": labels[k], "value": st[k],
                                                "share": round(100 * st[k] / total, 1) if total else 0} for k in ("done", "cooking", "new", "ready", "cancelled")]}

    # eng ko'p sotilganlar
    items = (OrderItem.objects.filter(order__in=cur).values("product_id", "name").annotate(q=Sum("qty"), s=Sum(F("price") * F("qty")))
             .order_by("-q")[:5])
    qty_total = OrderItem.objects.filter(order__in=cur).aggregate(q=Sum("qty"))["q"] or 0
    from modules.catalog.models import Product
    imgs = {p.pk: p.image_src for p in Product.objects.filter(pk__in=[i["product_id"] for i in items if i["product_id"]])}
    out["top"] = [{"name": i["name"], "qty": int(i["q"] or 0), "revenue": int(i["s"] or 0), "image": imgs.get(i["product_id"]),
                   "share": round(100 * int(i["q"] or 0) / qty_total, 1) if qty_total else 0} for i in items]

    # filiallar
    from core.models import Branch
    brs = []
    for br in Branch.objects.filter(deleted_at__isnull=True, is_active=True):
        x = paid(start, end).filter(branch=br).aggregate(r=Sum("total"), n=Count("id"), c=Sum("cost_total")) if not branch_id or branch_id == br.pk else None
        if x is None:
            continue
        r, k, c = int(x["r"] or 0), x["n"] or 0, int(x["c"] or 0)
        f = round(100 * c / r, 1) if r else 0.0
        brs.append({"id": br.pk, "name": br.name, "revenue": r, "orders": k, "food_cost": f,
                    "state": "ok" if r and f <= 35 else "warn" if r and f <= 38 else ("bad" if r else "idle")})
    out["branches"] = sorted(brs, key=lambda b: -b["revenue"])

    # so'nggi buyurtmalar
    rec = Order.objects.exclude(status=OrderStatus.CANCELLED).order_by("-created_at")
    if branch_id:
        rec = rec.filter(branch_id=branch_id)
    rec = list(rec[:6])
    rkds = {}
    try:
        from modules.kds.models import Ticket
        for oid, s in Ticket.objects.filter(order_id__in=[o.pk for o in rec]).values_list("order_id", "status"):
            rank = {"new": 0, "cooking": 1, "ready": 2, "served": 3}.get(s, 0)
            rkds[oid] = min(rkds.get(oid, 9), rank)
    except Exception:
        pass
    out["recent"] = []
    for o in rec:
        if o.status == OrderStatus.PAID:
            s, lab = ("delivered", "Yetkazildi") if o.type == "delivery" else ("done", "To'langan")
        else:
            r = rkds.get(o.pk, 0)
            s, lab = ("ready", "Tayyor") if r >= 2 else ("cooking", "Oshxonada") if r == 1 else ("new", "Yangi")
        where = f"Stol {o.table_no}" if o.type == "dine_in" and o.table_no else TYPE_UZ.get(o.type, o.type)
        if o.source != "pos":
            where += f" · {SOURCE_UZ.get(o.source, o.source)}"
        out["recent"].append({"id": o.pk, "number": o.number, "time": timezone.localtime(o.created_at).strftime("%H:%M"),
                              "where": where, "total": o.total, "status": s, "status_label": lab})


# ------------------------------------------------------------------ ombor
def _stock(out):
    from modules.inventory.models import Ingredient
    rows = []
    for i in Ingredient.objects.filter(deleted_at__isnull=True, is_active=True, min_stock__gt=0):
        ratio = float(i.stock) / float(i.min_stock) if i.min_stock else 9
        if ratio < 1.5:
            rows.append({"id": i.pk, "name": (i.name or {}).get("uz") or str(i), "stock": float(i.stock), "unit": i.unit,
                         "min": float(i.min_stock), "level": "critical" if ratio < 0.5 else "low" if ratio < 1 else "watch", "ratio": ratio})
    rows.sort(key=lambda r: r["ratio"])
    out["stock"] = {"count": sum(1 for r in rows if r["level"] != "watch"), "items": rows[:5]}


# ------------------------------------------------------------------ bayram va ob-havo
def _forecast(out, t):
    """Yaqin bayram ogohlantirishi (xarid rejasi qisqachasi) + 7 kunlik ob-havo. Xato bo'lsa — blok chiqmaydi."""
    import logging

    try:
        from modules.forecast import services, weather
        alerts = services.alerts(t)
        ids = {a["id"] for a in alerts}
        nxt = next((services.holiday_out(h) for h in services.upcoming(limit=4) if h.pk not in ids), None)
        weather.refresh(t)
        out["forecast"] = {"alerts": alerts[:2], "next": nxt, "weather": [weather.day_out(w, t) for w in weather.forecast_days(t)],
                           "location": weather.location(t)["name"]}
    except Exception:
        logging.getLogger("dashboard").exception("forecast bloki")
        out["forecast"] = None


# ------------------------------------------------------------------ vazifalar
def _tasks(out, now):
    from modules.tasks.models import ColumnKind, Task
    end_day = timezone.make_aware(datetime.combine(timezone.localdate(), time(23, 59)))
    qs = (Task.objects.live().filter(Q(due_at__lte=end_day) | Q(column__kind=ColumnKind.DONE, done_at__date=timezone.localdate()))
          .select_related("assignee", "column").order_by("due_at"))
    rows = []
    for tk in qs[:40]:
        done = tk.column.kind == ColumnKind.DONE
        if done and not (tk.done_at and tk.done_at.date() == timezone.localdate()):
            continue
        rows.append({"id": tk.pk, "title": tk.title, "done": done, "overdue": bool(not done and tk.due_at and tk.due_at < now),
                     "time": timezone.localtime(tk.due_at).strftime("%H:%M") if tk.due_at and tk.due_at.date() == timezone.localdate() else
                     (timezone.localtime(tk.due_at).strftime("%d.%m") if tk.due_at else ""),
                     "assignee": tk.assignee.full_name if tk.assignee_id else None})
    rows.sort(key=lambda r: (r["done"], not r["overdue"]))
    out["tasks"] = {"open": Task.objects.open().count(), "overdue": Task.objects.overdue().count(), "items": rows[:6]}


# ------------------------------------------------------------------ so'nggi faoliyat
def _activity(out, t, branch_id):
    ev = []
    if t.module_enabled("pos"):
        from modules.pos.models import Order, OrderStatus
        qs = Order.objects.filter(status=OrderStatus.PAID).select_related("cashier").order_by("-paid_at")
        if branch_id:
            qs = qs.filter(branch_id=branch_id)
        for o in qs[:4]:
            ev.append({"at": o.paid_at, "icon": "receipt", "who": o.cashier.full_name if o.cashier_id else "Kassa",
                       "text": f"#{o.number} buyurtmani qabul qildi · {o.total:,} so'm".replace(",", " ")})
    if t.module_enabled("kds"):
        try:
            from modules.kds.models import Ticket
            for tk in Ticket.objects.filter(ready_at__isnull=False).select_related("cook", "order").order_by("-ready_at")[:3]:
                ev.append({"at": tk.ready_at, "icon": "play", "who": tk.cook.full_name if tk.cook_id else "Oshxona",
                           "text": f"#{tk.order.number} tayyorladi"})
        except Exception:
            pass
    if t.module_enabled("tasks"):
        from modules.tasks.models import TaskActivity
        for a in TaskActivity.objects.select_related("actor", "task").order_by("-at")[:4]:
            ev.append({"at": a.at, "icon": "check", "who": a.actor.full_name if a.actor_id else "Tizim", "text": f"{a.detail or a.action}: «{a.task.title}»"})
    if t.module_enabled("inventory"):
        from modules.inventory.models import Purchase
        for p in Purchase.objects.select_related("supplier", "created_by").order_by("-created_at")[:2]:
            ev.append({"at": p.created_at, "icon": "box", "who": p.created_by.full_name if p.created_by_id else "Ombor",
                       "text": f"kirim: {p.supplier.name if p.supplier_id else 'bozorlik'}"})
    if t.module_enabled("training"):
        from modules.training.models import Enrollment
        for e in Enrollment.objects.filter(completed_at__isnull=False).select_related("user", "course").order_by("-completed_at")[:2]:
            ev.append({"at": e.completed_at, "icon": "book", "who": e.user.full_name or e.user.phone, "text": f"«{e.course.title}» kursini tugatdi"})
    from core.models import AuditLog
    for a in AuditLog.objects.select_related("actor").order_by("-at")[:3]:
        ev.append({"at": a.at, "icon": "edit", "who": str(a.actor) if a.actor else "Tizim", "text": f"{a.action} · {a.model}"})
    ev.sort(key=lambda x: x["at"] or timezone.now(), reverse=True)
    out["activity"] = [{**e, "at": e["at"].isoformat() if e["at"] else None} for e in ev[:7]]
'@

Put 'backend\config\settings\base.py' @'
"""
RestoPOS — asosiy sozlamalar (barcha muhitlar uchun umumiy).

Multi-tenant: django-tenants (har restoran = alohida PostgreSQL sxemasi, bitta kod).
"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent

# .env (repo ildizida yoki backend/ ichida) — bo'lsa o'qiladi, muhit o'zgaruvchilari ustun turadi
try:
    from dotenv import load_dotenv
    for _env in (BASE_DIR.parent / ".env", BASE_DIR / ".env"):
        if _env.exists():
            load_dotenv(_env, override=False)
except ImportError:  # pragma: no cover
    pass

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "dev-only-secret-change-me")
DEBUG = False
ALLOWED_HOSTS = ["*"]  # domenlar django-tenants Domain jadvalida tekshiriladi

# ------------------------------------------------------------------ apps
# public sxemada yashaydigan ilovalar (tenant ro'yxati, tariflar, platforma foydalanuvchilari)
SHARED_APPS = [
    "django_tenants",
    "public",
    "django.contrib.contenttypes",
    "django.contrib.auth",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.admin",
    "corsheaders",
    "simple_history",
    "core",
    "website",
]

# har tenant sxemasida yashaydigan ilovalar (restoran ma'lumotlari)
TENANT_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.auth",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.admin",
    "simple_history",
    "core",
    # modullar — har biri yoqiladigan/o'chiriladigan birlik (core/modules.py registri)
    "modules.catalog",
    "modules.cms",
    "modules.tasks",
    "modules.inventory",
    "modules.pos",
    "modules.payments",
    "modules.hr",
    "modules.finance",
    "modules.kds",
    "modules.tables",
    "modules.reservations",
    "modules.training",
    "modules.telegram",
    "modules.crm",
    "modules.forecast",
]

INSTALLED_APPS = SHARED_APPS + [a for a in TENANT_APPS if a not in SHARED_APPS]

TENANT_MODEL = "public.Tenant"
TENANT_DOMAIN_MODEL = "public.Domain"
PUBLIC_SCHEMA_URLCONF = "config.urls_public"
# noma'lum domen (IP, healthcheck) → 404 emas, platforma sayti (public sxema)
SHOW_PUBLIC_IF_NO_TENANT_FOUND = True
ROOT_URLCONF = "config.urls"

AUTH_USER_MODEL = "core.User"

MIDDLEWARE = [
    "django_tenants.middleware.main.TenantMainMiddleware",  # BIRINCHI: domen → tenant → search_path
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "core.middleware.IdempotencyMiddleware",
    "core.middleware.RequestIdMiddleware",
]

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "website" / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

# ------------------------------------------------------------------ database
DATABASES = {
    "default": {
        "ENGINE": "django_tenants.postgresql_backend",
        "NAME": os.environ.get("POSTGRES_DB", "restopos"),
        "USER": os.environ.get("POSTGRES_USER", "restopos"),
        "PASSWORD": os.environ.get("POSTGRES_PASSWORD", "restopos"),
        "HOST": os.environ.get("POSTGRES_HOST", "localhost"),
        "PORT": os.environ.get("POSTGRES_PORT", "5432"),
        "CONN_MAX_AGE": 60,
    }
}
DATABASE_ROUTERS = ("django_tenants.routers.TenantSyncRouter",)
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ------------------------------------------------------------------ cache / redis
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": REDIS_URL,
        "KEY_FUNCTION": "django_tenants.cache.make_key",
        "REVERSE_KEY_FUNCTION": "django_tenants.cache.reverse_key",
    }
}

# ------------------------------------------------------------------ celery
CELERY_BROKER_URL = os.environ.get("CELERY_BROKER_URL", REDIS_URL)
CELERY_RESULT_BACKEND = os.environ.get("CELERY_RESULT_BACKEND", REDIS_URL)
CELERY_TASK_DEFAULT_QUEUE = "default"
CELERY_TASK_QUEUES = {
    "critical": {"exchange": "critical"},  # fiskal chek, to'lov callback
    "default": {"exchange": "default"},    # push, SMS, import
    "bulk": {"exchange": "bulk"},          # hisobot, stat.uz, eksport
}
CELERY_TASK_ACKS_LATE = True
CELERY_WORKER_PREFETCH_MULTIPLIER = 1

# ------------------------------------------------------------------ i18n
LANGUAGE_CODE = "uz"
LANGUAGES = [("uz", "O'zbekcha"), ("ru", "Русский"), ("en", "English")]
TIME_ZONE = "Asia/Tashkent"
USE_I18N = True
USE_TZ = True

# ------------------------------------------------------------------ static / media
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "website" / "static"]
STORAGES = {
    "default": {"BACKEND": "django_tenants.files.storage.TenantFileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"
MULTITENANT_RELATIVE_MEDIA_ROOT = "%s"  # media/<schema>/...

# ------------------------------------------------------------------ auth / api
JWT_SECRET = os.environ.get("JWT_SECRET", SECRET_KEY)
JWT_ACCESS_MINUTES = int(os.environ.get("JWT_ACCESS_MINUTES", "720"))
OTP_TTL_SECONDS = 300
OTP_DEV_ECHO = False  # dev.py da True: OTP kodi javobda qaytariladi (SMS shart emas)

CORS_ALLOW_ALL_ORIGINS = False
CORS_ALLOWED_ORIGIN_REGEXES = [r"^https?://([a-z0-9-]+\.)?localhost(:\d+)?$"]
CORS_ALLOW_CREDENTIALS = True

NINJA_PAGINATION_PER_PAGE = 50

# ------------------------------------------------------------------ platform
PLATFORM_DOMAIN = os.environ.get("PLATFORM_DOMAIN", "localhost")
PLATFORM_NAME = "RestoPOS"
VITE_DEV = os.environ.get("VITE_DEV") == "1"      # 1 → /admin Vite dev-serverdan (HMR) yuklanadi
VITE_URL = os.environ.get("VITE_URL", "http://localhost:5173")

# ------------------------------------------------------------------ logging
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"std": {"format": "%(asctime)s %(levelname)s [%(name)s] %(message)s"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "std"}},
    "root": {"handlers": ["console"], "level": "INFO"},
}
'@

Put 'backend\core\presets.py' @'
"""
Preset'lar — yangi restoran 15 daqiqada ishga tushishi uchun tayyor konfiguratsiyalar.
Preset = yoqilgan modullar + sayt bo'limlari + tema + boshlang'ich sozlamalar. Kod emas, ma'lumot.
"""

DEFAULT_SETTINGS = {
    "languages": ["uz", "ru"],
    "default_language": "uz",
    "currency": "UZS",
    "timezone": "Asia/Tashkent",
    "tax_mode": "turnover",   # turnover | vat6 | vat12
    "receipt_footer": "Rahmat! Yana kutamiz.",
}

BASE_SECTIONS = [
    {"type": "hero", "props": {"title": "Issiq, tez va har buyurtmadan bonus", "subtitle": "Buyurtma bering — 25–35 daqiqada yetkazamiz", "cta": "Buyurtma berish"}},
    {"type": "menu", "props": {"title": "Taomnoma", "show_categories": True}},
    {"type": "bonus", "props": {"title": "Bonus tizimi", "percent": 5, "gift_visit": 4}},
    {"type": "branches", "props": {"title": "Filiallar"}},
    {"type": "delivery", "props": {"title": "Buyurtma qanday keladi"}},
    {"type": "contact", "props": {"title": "Aloqa"}},
]

PRESETS = {
    "fast_food": {
        "name": "Fast-food",
        "modules": ["catalog", "cms", "tasks", "pos", "payments", "inventory", "hr", "finance", "fiscal", "kds", "telegram", "crm", "forecast"],
        "sections": BASE_SECTIONS,
        "theme": {"primary": "#D9482B", "accent": "#0F6E63", "bg": "#FFF6EA", "ink": "#1C1512", "font": "Manrope", "dark_default": False},
    },
    "cafe": {
        "name": "Kafe",
        "modules": ["catalog", "cms", "tasks", "pos", "payments", "inventory", "hr", "finance", "fiscal", "kds", "tables", "reservations", "telegram", "crm", "forecast"],
        "sections": BASE_SECTIONS,
        "theme": {"primary": "#8A5A12", "accent": "#0F6E63", "bg": "#FAF6EF", "ink": "#1C1512", "font": "Manrope", "dark_default": False},
    },
    "restaurant": {
        "name": "Restoran",
        "modules": ["catalog", "cms", "tasks", "pos", "payments", "inventory", "hr", "finance", "fiscal", "kds", "tables", "reservations", "telegram", "crm", "forecast"],
        "sections": BASE_SECTIONS,
        "theme": {"primary": "#1C1512", "accent": "#B8321B", "bg": "#FFFFFF", "ink": "#1C1512", "font": "Manrope", "dark_default": False},
    },
    "cloud_kitchen": {
        "name": "Cloud kitchen",
        "modules": ["catalog", "cms", "tasks", "pos", "payments", "inventory", "hr", "finance", "fiscal", "kds", "delivery", "telegram", "crm", "forecast"],
        "sections": [s for s in BASE_SECTIONS if s["type"] != "branches"],
        "theme": {"primary": "#0F6E63", "accent": "#D9482B", "bg": "#F4F3EE", "ink": "#17171A", "font": "Manrope", "dark_default": True},
    },
}
'@

Put 'backend\modules\forecast\__init__.py' @'

'@

Put 'backend\modules\forecast\api.py' @'
"""Bayram va ob-havo prognozi API — /api/v1/forecast/..."""
from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

from django.shortcuts import get_object_or_404
from django.utils import timezone
from ninja import Router, Schema
from ninja.errors import HttpError

from core.audit import record, snapshot
from core.auth import auth, require_module, require_perm

from . import services, weather
from .models import Holiday, HolidayKind

router = Router(tags=["forecast"])


def _guard(request, perm: str):
    require_module(request, "forecast")
    require_perm(request, perm)


class I18n(Schema):
    uz: str = ""
    ru: str = ""
    en: str = ""


class HolidayIn(Schema):
    name: I18n
    date: date
    days: int = 1
    kind: str = HolidayKind.LOCAL
    uplift_percent: int = 20
    prep_days: int = 7
    is_approx: bool = False
    is_active: bool = True
    note: str = ""


def _validate(data: HolidayIn):
    if not data.name.uz.strip():
        raise HttpError(400, "Bayram nomini kiriting.")
    if not 1 <= data.days <= 40:
        raise HttpError(400, "Davomiylik 1 dan 40 kungacha bo'lishi kerak.")
    if not -90 <= data.uplift_percent <= 300:
        raise HttpError(400, "Savdo o'zgarishi −90% dan +300% gacha bo'lishi kerak.")
    if not 0 <= data.prep_days <= 60:
        raise HttpError(400, "Ogohlantirish 0–60 kun oldin bo'lishi mumkin.")
    if data.kind not in HolidayKind.values:
        raise HttpError(400, "Noma'lum bayram turi.")


def _weather(request) -> dict:
    t = request.tenant
    r = weather.refresh(t)
    days = [weather.day_out(w, t) for w in weather.forecast_days(t)]
    return {"location": weather.location(t), "days": days, "ok": r["ok"], "error": r.get("error"),
            "demo": bool(days) and all(d["source"] != "open-meteo" for d in days)}


# ------------------------------------------------------------------ umumiy ko'rinish
@router.get("/overview", auth=auth)
def overview(request):
    _guard(request, "forecast.view")
    services.ensure_holidays()
    t = request.tenant
    return {
        "alerts": services.alerts(t),
        "upcoming": [services.holiday_out(h, with_history=True) for h in services.upcoming(limit=6)],
        "weather": _weather(request),
        "kinds": [{"code": k.value, "label": k.label} for k in HolidayKind],
        "lead_days": int(weather.setting(t, "purchase_lead_days", 2)),
    }


# ------------------------------------------------------------------ bayramlar
@router.get("/holidays", auth=auth)
def list_holidays(request, year: Optional[int] = None):
    _guard(request, "forecast.view")
    services.ensure_holidays()
    y = year or timezone.localdate().year
    services.ensure_year(y)
    return [services.holiday_out(h, with_history=True) for h in Holiday.objects.filter(date__year=y)]


@router.post("/holidays", auth=auth)
def create_holiday(request, data: HolidayIn):
    _guard(request, "forecast.edit")
    _validate(data)
    d = data.dict()
    d["name"] = data.name.dict()
    h = Holiday.objects.create(**d)
    record(request, "create", h)
    return services.holiday_out(h, with_history=True)


@router.put("/holidays/{int:hid}", auth=auth)
def update_holiday(request, hid: int, data: HolidayIn):
    _guard(request, "forecast.edit")
    _validate(data)
    h = get_object_or_404(Holiday, pk=hid)
    before = snapshot(h)
    moved = h.date != data.date
    for k, v in data.dict().items():
        setattr(h, k, v.dict() if k == "name" else v)
    if moved:
        h.notified_at = None       # sana o'zgardi — ogohlantirish qaytadan
    h.save()
    record(request, "update", h, before=before)
    return services.holiday_out(h, with_history=True)


@router.delete("/holidays/{int:hid}", auth=auth)
def delete_holiday(request, hid: int):
    """Tizim bayrami o'chirilmaydi — o'chirib qo'yiladi (keyingi yil yana chiqadi); o'zimiznikisi o'chadi."""
    _guard(request, "forecast.edit")
    h = get_object_or_404(Holiday, pk=hid)
    record(request, "delete", h)
    if h.code:
        h.is_active = False
        h.save(update_fields=["is_active", "updated_at"])
        return {"ok": True, "disabled": True}
    h.delete()
    return {"ok": True, "disabled": False}


@router.post("/holidays/{int:hid}/learn", auth=auth)
def learn(request, hid: int):
    """O'tgan yilgi haqiqiy savdo o'sishini shu bayramga yozish."""
    _guard(request, "forecast.edit")
    h = get_object_or_404(Holiday, pk=hid)
    prev = services.previous_of(h)
    pct = services.history_uplift(prev) if prev else None
    if pct is None:
        raise HttpError(400, "O'tgan yilgi savdo ma'lumoti yo'q — foizni qo'lda kiriting.")
    h.uplift_percent = max(-90, min(300, pct))
    h.save(update_fields=["uplift_percent", "updated_at"])
    record(request, "update", h, after={"uplift_percent": h.uplift_percent})
    return services.holiday_out(h, with_history=True)


# ------------------------------------------------------------------ xarid rejasi
@router.get("/plan", auth=auth)
def purchase_plan(request, holiday_id: Optional[int] = None, days: int = 7):
    _guard(request, "forecast.view")
    services.ensure_holidays()
    weather.refresh(request.tenant)
    if holiday_id:
        h = get_object_or_404(Holiday, pk=holiday_id)
        if h.end < timezone.localdate():
            raise HttpError(400, "Bu bayram o'tib ketgan.")
        return services.plan(request.tenant, holiday=h)
    days = max(1, min(30, days))
    today = timezone.localdate()
    return services.plan(request.tenant, start=today, end=today + timedelta(days=days - 1))


# ------------------------------------------------------------------ ob-havo
@router.get("/weather", auth=auth)
def get_weather(request):
    _guard(request, "forecast.view")
    return _weather(request)


@router.post("/weather/refresh", auth=auth)
def refresh_weather(request):
    _guard(request, "forecast.edit")
    r = weather.refresh(request.tenant, force=True)
    if not r["ok"]:
        raise HttpError(503, r["error"])
    return _weather(request)
'@

Put 'backend\modules\forecast\apps.py' @'
from django.apps import AppConfig


class ForecastConfig(AppConfig):
    name = "modules.forecast"
    label = "forecast"
    verbose_name = "Bayram va ob-havo prognozi"
'@

Put 'backend\modules\forecast\demo.py' @'
"""Demo: bayramlar (joriy va keyingi yil) + ob-havo. Internet bo'lmasa — namunaviy 7 kunlik prognoz."""
from __future__ import annotations

from datetime import timedelta

from django.utils import timezone

from . import services, weather
from .models import WeatherDay


def seed_demo_forecast(tenant) -> dict:
    n = services.ensure_holidays()
    r = weather.refresh(tenant, force=True)
    demo = False
    if not r["ok"] and not WeatherDay.objects.filter(date__gte=timezone.localdate()).exists():
        today = timezone.localdate()
        # (kun, maks, min, yog'in %, yog'in mm, shamol, WMO kodi) — kuz boshi, Toshkent
        sample = [(0, 27, 14, 5, 0, 9, 0), (1, 29, 15, 0, 0, 7, 1), (2, 24, 13, 75, 6.2, 18, 63), (3, 21, 11, 40, 0.8, 24, 3),
                  (4, 25, 12, 10, 0, 11, 2), (5, 28, 14, 0, 0, 8, 0), (6, 30, 16, 0, 0, 12, 0)]
        weather.save_days([{"date": today + timedelta(days=d), "t_max": mx, "t_min": mn, "precip_prob": pp, "precip_mm": mm,
                            "wind": w, "code": c} for d, mx, mn, pp, mm, w, c in sample], source="demo")
        demo = True
    return {"holidays": n, "weather": "demo" if demo else ("ok" if r["ok"] else "eski")}
'@

Put 'backend\modules\forecast\management\__init__.py' @'

'@

Put 'backend\modules\forecast\management\commands\__init__.py' @'

'@

Put 'backend\modules\forecast\management\commands\seed_forecast.py' @'
"""
«Bayram va ob-havo prognozi» modulini yoqish + bayramlar va ob-havo:
    python manage.py seed_forecast                 (barcha restoranlar)
    python manage.py seed_forecast --slug namuna
"""
from django.core.management.base import BaseCommand
from django_tenants.utils import schema_context

from public.models import Tenant
from public.services import set_modules


class Command(BaseCommand):
    help = "Bayram va ob-havo prognozi modulini yoqadi, bayramlar va ob-havoni yuklaydi"

    def add_arguments(self, parser):
        parser.add_argument("--slug", default="")

    def handle(self, *args, **opts):
        qs = Tenant.objects.exclude(schema_name="public")
        if opts["slug"]:
            qs = qs.filter(slug=opts["slug"])
        if not qs.exists():
            self.stderr.write(f"Restoran topilmadi: {opts['slug']}")
            return
        for t in qs:
            if "forecast" not in t.enabled_modules:
                try:
                    set_modules(t, [*t.enabled_modules, "forecast"])
                except PermissionError as e:
                    self.stderr.write(f"{t.slug}: {e}")
                    continue
            with schema_context(t.schema_name):
                from modules.forecast.demo import seed_demo_forecast
                r = seed_demo_forecast(t)
            w = {"ok": "yangilandi", "demo": "namunaviy (internet yo'q)", "eski": "oxirgi saqlangan"}[r["weather"]]
            self.stdout.write(f"{t.slug}: modul yoqildi · yangi bayramlar: {r['holidays']} · ob-havo: {w}")
        self.stdout.write(self.style.SUCCESS("Tayyor."))
'@

Put 'backend\modules\forecast\migrations\0001_initial.py' @'
# Generated by Django 5.1.15 on 2026-09-26 23:42

import modules.forecast.models
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="Holiday",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "code",
                    models.CharField(
                        blank=True,
                        db_index=True,
                        help_text="tizim bayrami kodi (navruz, hayit…); qo'lda qo'shilganda bo'sh",
                        max_length=40,
                    ),
                ),
                ("name", models.JSONField(default=modules.forecast.models.empty_i18n)),
                ("date", models.DateField(db_index=True)),
                (
                    "days",
                    models.PositiveSmallIntegerField(
                        default=1, help_text="necha kun davom etadi"
                    ),
                ),
                (
                    "kind",
                    models.CharField(
                        choices=[
                            ("official", "Davlat bayrami"),
                            ("religious", "Diniy bayram"),
                            ("commercial", "Tijoriy kun"),
                            ("season", "Mavsum"),
                            ("local", "O'zimizniki"),
                        ],
                        default="official",
                        max_length=12,
                    ),
                ),
                (
                    "uplift_percent",
                    models.IntegerField(
                        default=20,
                        help_text="kutilayotgan savdo o'zgarishi, % (manfiy ham bo'lishi mumkin)",
                    ),
                ),
                (
                    "prep_days",
                    models.PositiveSmallIntegerField(
                        default=7, help_text="necha kun oldin ogohlantirish"
                    ),
                ),
                (
                    "is_approx",
                    models.BooleanField(
                        default=False,
                        help_text="sana taxminiy (hayitlar — Diniy idora e'lonidan keyin aniqlanadi)",
                    ),
                ),
                ("is_active", models.BooleanField(default=True)),
                ("note", models.CharField(blank=True, max_length=240)),
                (
                    "notified_at",
                    models.DateTimeField(
                        blank=True,
                        help_text="tayyorgarlik vazifasi ochilgan vaqt",
                        null=True,
                    ),
                ),
            ],
            options={
                "ordering": ["date", "id"],
            },
        ),
        migrations.CreateModel(
            name="WeatherDay",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("date", models.DateField(unique=True)),
                ("t_max", models.FloatField(default=0)),
                ("t_min", models.FloatField(default=0)),
                ("precip_mm", models.FloatField(default=0)),
                ("precip_prob", models.PositiveSmallIntegerField(default=0)),
                ("wind", models.FloatField(default=0, help_text="km/soat")),
                (
                    "code",
                    models.PositiveSmallIntegerField(
                        default=0, help_text="WMO ob-havo kodi"
                    ),
                ),
                ("source", models.CharField(default="open-meteo", max_length=20)),
                ("fetched_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "ordering": ["date"],
            },
        ),
    ]
'@

Put 'backend\modules\forecast\migrations\__init__.py' @'

'@

Put 'backend\modules\forecast\models.py' @'
"""
Bayram va ob-havo prognozi.

  Holiday     — bayram / muhim kun: sana, necha kun davom etadi, kutilayotgan savdo o'sishi (%),
                necha kun oldin ogohlantirish. O'zbekiston bayramlari har yil uchun avtomatik qo'shiladi
                (services.ensure_holidays), egasi tahrirlaydi yoki o'zinikini qo'shadi.
  WeatherDay  — kunlik ob-havo prognozi (Open-Meteo, kalit shart emas), 3 soatda bir yangilanadi.
"""
from __future__ import annotations

from datetime import timedelta

from django.db import models

from core.models import TimeStamped


def empty_i18n() -> dict:
    return {"uz": "", "ru": "", "en": ""}


class HolidayKind(models.TextChoices):
    OFFICIAL = "official", "Davlat bayrami"
    RELIGIOUS = "religious", "Diniy bayram"
    COMMERCIAL = "commercial", "Tijoriy kun"
    SEASON = "season", "Mavsum"
    LOCAL = "local", "O'zimizniki"


class Holiday(TimeStamped):
    code = models.CharField(max_length=40, blank=True, db_index=True, help_text="tizim bayrami kodi (navruz, hayit…); qo'lda qo'shilganda bo'sh")
    name = models.JSONField(default=empty_i18n)
    date = models.DateField(db_index=True)
    days = models.PositiveSmallIntegerField(default=1, help_text="necha kun davom etadi")
    kind = models.CharField(max_length=12, choices=HolidayKind.choices, default=HolidayKind.OFFICIAL)
    uplift_percent = models.IntegerField(default=20, help_text="kutilayotgan savdo o'zgarishi, % (manfiy ham bo'lishi mumkin)")
    prep_days = models.PositiveSmallIntegerField(default=7, help_text="necha kun oldin ogohlantirish")
    is_approx = models.BooleanField(default=False, help_text="sana taxminiy (hayitlar — Diniy idora e'lonidan keyin aniqlanadi)")
    is_active = models.BooleanField(default=True)
    note = models.CharField(max_length=240, blank=True)
    notified_at = models.DateTimeField(null=True, blank=True, help_text="tayyorgarlik vazifasi ochilgan vaqt")

    class Meta:
        ordering = ["date", "id"]

    def __str__(self) -> str:
        return (self.name or {}).get("uz") or self.code or f"#{self.pk}"

    @property
    def end(self):
        return self.date + timedelta(days=max(1, self.days) - 1)

    def covers(self, d) -> bool:
        return self.date <= d <= self.end


class WeatherDay(models.Model):
    date = models.DateField(unique=True)
    t_max = models.FloatField(default=0)
    t_min = models.FloatField(default=0)
    precip_mm = models.FloatField(default=0)
    precip_prob = models.PositiveSmallIntegerField(default=0)
    wind = models.FloatField(default=0, help_text="km/soat")
    code = models.PositiveSmallIntegerField(default=0, help_text="WMO ob-havo kodi")
    source = models.CharField(max_length=20, default="open-meteo")
    fetched_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["date"]
'@

Put 'backend\modules\forecast\module.json' @'
{
  "code": "forecast",
  "name": {"uz": "Bayram va ob-havo prognozi", "ru": "Прогноз: праздники и погода", "en": "Holidays & weather forecast"},
  "version": "1.0.0", "phase": 10, "implemented": true, "order": 62,
  "depends": ["inventory", "pos"],
  "permissions": ["forecast.view", "forecast.edit", "forecast.*"],
  "nav": [
    {"route": "/forecast", "label": {"uz": "Bayram va ob-havo", "ru": "Праздники и погода", "en": "Holidays & weather"}, "icon": "sun", "order": 62, "perm": "forecast.view"}
  ],
  "settings_schema": {
    "type": "object",
    "properties": {
      "city": {"type": "string", "title": "Shahar (ob-havo uchun)", "enum": ["Toshkent", "Samarqand", "Buxoro", "Andijon", "Farg'ona", "Namangan", "Qarshi", "Nukus", "Urganch", "Jizzax", "Navoiy", "Termiz", "Guliston"], "default": "Toshkent", "description": "Filialda koordinata kiritilgan bo'lsa — o'sha ishlatiladi"},
      "purchase_lead_days": {"type": "integer", "title": "Xaridni bayramdan necha kun oldin qilish", "default": 2},
      "history_days": {"type": "integer", "title": "Sotuv tezligini necha kunlik savdodan hisoblash", "default": 28},
      "hot_threshold": {"type": "integer", "title": "Issiq kun chegarasi (°C)", "default": 35},
      "cold_threshold": {"type": "integer", "title": "Sovuq kun chegarasi (°C)", "default": 0},
      "rain_probability": {"type": "integer", "title": "Yomg'ir ehtimoli chegarasi (%)", "default": 60},
      "rain_effect": {"type": "integer", "title": "Yomg'irli kunda savdo o'zgarishi (%)", "default": -10},
      "hot_effect": {"type": "integer", "title": "Issiq kunda savdo o'zgarishi (%)", "default": -5},
      "cold_effect": {"type": "integer", "title": "Sovuq kunda savdo o'zgarishi (%)", "default": 0},
      "create_task": {"type": "boolean", "title": "Bayramga tayyorgarlik vazifasini avtomatik ochish", "default": true}
    }
  }
}
'@

Put 'backend\modules\forecast\services.py' @'
"""
Bayram va ob-havo prognozi — hisob-kitob.

Qanday hisoblanadi (oddiy va tushunarli):
  1) Oxirgi N kun (standart 28) savdosidan har taomning kunlik o'rtacha sotuvi olinadi.
  2) Har kun uchun ko'paytuvchi: hafta kuni (juma-shanba odatda yuqori) × bayram (+uplift%) × ob-havo.
  3) Taom sotuvi × tex-karta = xomashyo ehtiyoji. Ehtiyoj + minimal qoldiq − hozirgi qoldiq = xarid qilish kerak.
Bayramdan `prep_days` kun oldin ombor va boshqaruv panelida ogohlantirish chiqadi, xohlasa — vazifa ochiladi.
"""
from __future__ import annotations

import math
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from django.db.models import Count, Sum
from django.db.models.functions import TruncDate
from django.utils import timezone

from core.events import emit

from . import weather
from .models import Holiday, HolidayKind

# ------------------------------------------------------------------ O'zbekiston bayramlari
# (kod, {uz, ru, en}, (oy, kun) yoki None — ko'chib yuruvchi, necha kun, tur, savdo o'sishi %, necha kun oldin, izoh)
BUILTIN = [
    ("new_year", {"uz": "Yangi yil", "ru": "Новый год", "en": "New Year"}, (1, 1), 2, HolidayKind.OFFICIAL, 20, 7, ""),
    ("defenders", {"uz": "Vatan himoyachilari kuni", "ru": "День защитников Родины", "en": "Defenders' Day"}, (1, 14), 1, HolidayKind.COMMERCIAL, 10, 5, ""),
    ("valentine", {"uz": "Sevishganlar kuni", "ru": "День святого Валентина", "en": "Valentine's Day"}, (2, 14), 1, HolidayKind.COMMERCIAL, 15, 5, "Juftliklar uchun set va desertlar."),
    ("women", {"uz": "Xotin-qizlar kuni", "ru": "Международный женский день", "en": "Women's Day"}, (3, 8), 1, HolidayKind.OFFICIAL, 40, 7, "Stol bronlari ko'payadi, desert va gullar."),
    ("navruz", {"uz": "Navro'z", "ru": "Навруз", "en": "Navruz"}, (3, 21), 2, HolidayKind.OFFICIAL, 35, 10, "Sumalak, halim, ko'k somsa — mavsumiy menyu."),
    ("memory", {"uz": "Xotira va qadrlash kuni", "ru": "День памяти и почестей", "en": "Remembrance Day"}, (5, 9), 1, HolidayKind.OFFICIAL, 10, 5, ""),
    ("children", {"uz": "Bolalarni himoya qilish kuni", "ru": "День защиты детей", "en": "Children's Day"}, (6, 1), 1, HolidayKind.COMMERCIAL, 15, 5, "Oilaviy tashriflar — bolalar menyusi."),
    ("independence", {"uz": "Mustaqillik kuni", "ru": "День независимости", "en": "Independence Day"}, (9, 1), 1, HolidayKind.OFFICIAL, 30, 7, ""),
    ("teachers", {"uz": "O'qituvchi va murabbiylar kuni", "ru": "День учителя", "en": "Teachers' Day"}, (10, 1), 1, HolidayKind.OFFICIAL, 15, 5, ""),
    ("constitution", {"uz": "Konstitutsiya kuni", "ru": "День Конституции", "en": "Constitution Day"}, (12, 8), 1, HolidayKind.OFFICIAL, 10, 5, ""),
    ("new_year_eve", {"uz": "Yangi yil kechasi", "ru": "Новогодняя ночь", "en": "New Year's Eve"}, (12, 31), 1, HolidayKind.COMMERCIAL, 60, 10, "Korporativlar va oilaviy bronlar — oldindan zakaz qabul qiling."),
    ("ramadan", {"uz": "Ramazon oyi (iftorlik)", "ru": "Рамадан (ифтар)", "en": "Ramadan (iftar)"}, None, 30, HolidayKind.SEASON, 10, 10, "Kunduzi savdo kamayadi, kechki iftorlik ko'payadi — iftorlik setlarini tayyorlang."),
    ("ramadan_eid", {"uz": "Ramazon hayiti", "ru": "Рамазан хайит", "en": "Eid al-Fitr"}, None, 1, HolidayKind.RELIGIOUS, 20, 10, "Sana taxminiy — Diniy idora e'lonidan keyin aniqlang."),
    ("kurban_eid", {"uz": "Qurbon hayiti", "ru": "Курбан хайит", "en": "Eid al-Adha"}, None, 1, HolidayKind.RELIGIOUS, 15, 10, "Go'sht narxi oshadi — go'shtni oldindan xarid qiling. Sana taxminiy."),
]
# ko'chib yuruvchi sanalar (taxminiy, oy kalendari bo'yicha)
MOVABLE = {
    2026: {"ramadan": date(2026, 2, 18), "ramadan_eid": date(2026, 3, 20), "kurban_eid": date(2026, 5, 27)},
    2027: {"ramadan": date(2027, 2, 8), "ramadan_eid": date(2027, 3, 10), "kurban_eid": date(2027, 5, 16)},
    2028: {"ramadan": date(2028, 1, 28), "ramadan_eid": date(2028, 2, 27), "kurban_eid": date(2028, 5, 5)},
    2029: {"ramadan": date(2029, 1, 16), "ramadan_eid": date(2029, 2, 14), "kurban_eid": date(2029, 4, 24)},
    2030: {"ramadan": date(2030, 1, 5), "ramadan_eid": date(2030, 2, 4), "kurban_eid": date(2030, 4, 13)},
}
BUILTIN_CODES = [b[0] for b in BUILTIN]


def ensure_year(year: int) -> int:
    """Shu yil uchun tizim bayramlarini qo'shadi (bir marta — egasi o'chirgani qayta paydo bo'lmaydi)."""
    if Holiday.objects.filter(code__in=BUILTIN_CODES, date__year=year).exists():
        return 0
    n = 0
    for code, name, md, days, kind, uplift, prep, note in BUILTIN:
        if md:
            d, approx = date(year, *md), False
        else:
            d, approx = MOVABLE.get(year, {}).get(code), True
            if d is None:
                continue
        Holiday.objects.create(code=code, name=name, date=d, days=days, kind=kind, uplift_percent=uplift,
                               prep_days=prep, is_approx=approx, note=note)
        n += 1
    return n


def ensure_holidays() -> int:
    y = timezone.localdate().year
    return ensure_year(y) + ensure_year(y + 1)


# ------------------------------------------------------------------ savdo tarixi
def _paid_orders():
    from modules.pos.models import Order, OrderStatus
    return Order.objects.filter(status=OrderStatus.PAID)


def daily_revenue(start: date, end: date) -> dict[date, int]:
    rows = (_paid_orders().filter(paid_at__date__gte=start, paid_at__date__lte=end)
            .annotate(d=TruncDate("paid_at")).values("d").annotate(r=Sum("total"), n=Count("id")))
    return {r["d"]: int(r["r"] or 0) for r in rows}


def history_window(tenant) -> tuple[date, date, int]:
    """(boshi, oxiri, kunlar soni) — kechagacha, oxirgi N kun, lekin birinchi sotuvdan oldin emas."""
    n = max(7, int(weather.setting(tenant, "history_days", 28)))
    end = timezone.localdate() - timedelta(days=1)
    start = end - timedelta(days=n - 1)
    first = _paid_orders().order_by("paid_at").values_list("paid_at", flat=True).first()
    if first:
        fd = timezone.localtime(first).date()
        if fd > start:
            start = fd
    days = max(1, (end - start).days + 1)
    return start, end, days


def weekday_factors(rev: dict[date, int], start: date, end: date) -> list[float]:
    """Hafta kunlari ko'paytuvchisi (Du=0 … Ya=6). 14 kundan kam tarix bo'lsa — hammasi 1."""
    days = [start + timedelta(days=i) for i in range((end - start).days + 1)]
    if len(days) < 14:
        return [1.0] * 7
    total = sum(rev.get(d, 0) for d in days) / len(days)
    if not total:
        return [1.0] * 7
    out = []
    for wd in range(7):
        ds = [d for d in days if d.weekday() == wd]
        avg = sum(rev.get(d, 0) for d in ds) / len(ds) if ds else total
        out.append(round(max(0.3, min(2.5, avg / total)), 3))
    return out


def history_uplift(h: Holiday) -> int | None:
    """Bayram kunlaridagi haqiqiy savdo ↔ undan oldingi 4 haftaning xuddi shu hafta kunlari. Ma'lumot yo'q → None."""
    yesterday = timezone.localdate() - timedelta(days=1)
    days = [h.date + timedelta(days=i) for i in range(max(1, h.days)) if h.date + timedelta(days=i) <= yesterday]
    if not days:
        return None
    rev = daily_revenue(days[0] - timedelta(days=28), days[-1])
    if not any(rev.get(d) for d in days):
        return None
    cur = sum(rev.get(d, 0) for d in days) / len(days)
    base_vals = [rev.get(d - timedelta(days=7 * k), 0) for d in days for k in range(1, 5)]
    base_vals = [v for v in base_vals if v]
    if not base_vals:
        return None
    base = sum(base_vals) / len(base_vals)
    return round(100 * (cur - base) / base)


def previous_of(h: Holiday) -> Holiday | None:
    if not h.code:
        return None
    return Holiday.objects.filter(code=h.code, date__lt=h.date).order_by("-date").first()


# ------------------------------------------------------------------ prognoz va xarid rejasi
def _holiday_factor(d: date, holidays: list[Holiday]) -> tuple[float, Holiday | None]:
    best, hh = 0, None
    for h in holidays:
        if h.is_active and h.covers(d) and (hh is None or abs(h.uplift_percent) > abs(best)):
            best, hh = h.uplift_percent, h
    return 1 + best / 100, hh


def _round_up(qty: float, unit: str) -> float:
    if qty <= 0:
        return 0.0
    if unit == "dona":
        return float(math.ceil(qty - 1e-9))
    return math.ceil(qty * 2 - 1e-9) / 2          # kg / l — 0,5 ga yaxlitlanadi


def plan(tenant, *, start: date | None = None, end: date | None = None, holiday: Holiday | None = None) -> dict:
    """[start, end] oralig'i uchun sotuv prognozi va xomashyo xarid rejasi."""
    from modules.catalog.models import Product
    from modules.inventory.models import SUB_UNIT, Ingredient, Recipe, Unit
    from modules.pos.models import OrderItem

    today = timezone.localdate()
    start = start or today
    if holiday is not None:   # uzun mavsum (Ramazon) — faqat birinchi haftasi uchun xarid
        end = min(holiday.end, max(start, holiday.date) + timedelta(days=6))
    end = end or start + timedelta(days=6)
    if end < start:
        end = start
    hs, he, hdays = history_window(tenant)
    rev = daily_revenue(hs, he)
    avg_rev = sum(rev.values()) / hdays if hdays else 0
    wf = weekday_factors(rev, hs, he)
    holidays = list(Holiday.objects.filter(is_active=True, date__lte=end, date__gte=start - timedelta(days=40)))
    wx = {w.date: w for w in weather.forecast_days(tenant, days=16)}

    # kunlar bo'yicha ko'paytuvchi
    days_out, total_factor, holiday_factor_sum = [], 0.0, 0.0
    for i in range((end - start).days + 1):
        d = start + timedelta(days=i)
        hf, hh = _holiday_factor(d, holidays)
        wfac = weather.factor(wx.get(d), tenant)
        f = wf[d.weekday()] * hf * wfac
        total_factor += f
        if hh is not None:
            holiday_factor_sum += f
        days_out.append({"date": d.isoformat(), "factor": round(f, 2), "holiday": str(hh) if hh else None,
                         "weather": weather.describe(wx[d].code)[0] if d in wx else None,
                         "revenue": int(avg_rev * f)})

    # taomlar kunlik sotuvi
    rates: dict[int, float] = {}
    for r in (OrderItem.objects.filter(order__in=_paid_orders().filter(paid_at__date__gte=hs, paid_at__date__lte=he),
                                       product_id__isnull=False)
              .values("product_id").annotate(q=Sum("qty"))):
        rates[r["product_id"]] = float(r["q"] or 0) / hdays

    # xomashyo ehtiyoji
    need: dict[int, float] = defaultdict(float)
    for rc in Recipe.objects.filter(product_id__in=rates.keys()).prefetch_related("lines__ingredient"):
        portions = rates[rc.product_id] * total_factor / float(rc.yield_qty or 1)
        for ln in rc.lines.all():
            per = float(ln.qty * SUB_UNIT[Unit(ln.ingredient.unit)][1] * (1 + ln.waste_percent / 100))
            need[ln.ingredient_id] += per * portions

    lines, total_cost = [], 0
    for ing in Ingredient.objects.filter(deleted_at__isnull=True, is_active=True).select_related("supplier"):
        n = need.get(ing.pk, 0.0)
        if n <= 0 and not ing.is_low:
            continue
        stock, mn = float(ing.stock), float(ing.min_stock)
        buy = _round_up(n + mn - stock, ing.unit)
        cost = int(Decimal(str(buy)) * ing.price)
        total_cost += cost
        lines.append({"ingredient_id": ing.pk, "name": ing.name, "category": ing.category, "unit": ing.unit,
                      "stock": round(stock, 3), "min_stock": round(mn, 3), "need": round(n, 3), "buy": buy,
                      "price": float(ing.price), "cost": cost, "supplier_id": ing.supplier_id,
                      "supplier": ing.supplier.name if ing.supplier_id else None,
                      "days_left": round(stock / (n / len(days_out)), 1) if n > 0 else None})
    lines.sort(key=lambda x: (-(x["buy"] > 0), -x["cost"]))
    sup: dict[str, dict] = {}
    for ln in lines:
        if ln["buy"] > 0:
            k = ln["supplier"] or "Bozor / boshqa"
            s = sup.setdefault(k, {"name": k, "supplier_id": ln["supplier_id"], "count": 0, "total": 0})
            s["count"] += 1
            s["total"] += ln["cost"]

    # eng ko'p ketadigan taomlar (bayram kunlarida yoki butun davrda)
    pf = holiday_factor_sum if holiday is not None and holiday_factor_sum else total_factor
    names = {p.pk: p.name for p in Product.objects.filter(pk__in=rates.keys())}
    products = sorted(({"product_id": pid, "name": names.get(pid, {}), "qty": round(r * pf)} for pid, r in rates.items()),
                      key=lambda x: -x["qty"])[:8]

    lead = int(weather.setting(tenant, "purchase_lead_days", 2))
    return {
        "start": start.isoformat(), "end": end.isoformat(), "days": len(days_out),
        "holiday": holiday_out(holiday) if holiday else None,
        "history": {"start": hs.isoformat(), "end": he.isoformat(), "days": hdays, "avg_revenue": int(avg_rev),
                    "enough": bool(rates) and hdays >= 7},
        "weekday_factors": wf,
        "daily": days_out,
        "revenue_forecast": int(avg_rev * total_factor),
        "revenue_normal": int(avg_rev * len(days_out)),
        "lines": lines,
        "short_count": sum(1 for ln in lines if ln["buy"] > 0),
        "total_cost": total_cost,
        "suppliers": sorted(sup.values(), key=lambda s: -s["total"]),
        "products": products,
        "buy_by": (max(today, (holiday.date if holiday else start) - timedelta(days=lead))).isoformat(),
    }


# ------------------------------------------------------------------ yaqin bayramlar va ogohlantirishlar
def holiday_out(h: Holiday, *, with_history: bool = False) -> dict:
    today = timezone.localdate()
    d = {"id": h.pk, "code": h.code, "name": h.name, "date": h.date.isoformat(), "end": h.end.isoformat(), "days": h.days,
         "kind": h.kind, "kind_label": HolidayKind(h.kind).label, "uplift_percent": h.uplift_percent, "prep_days": h.prep_days,
         "is_approx": h.is_approx, "is_active": h.is_active, "note": h.note, "builtin": bool(h.code),
         "days_left": (h.date - today).days, "is_now": h.covers(today), "is_past": h.end < today}
    if with_history:
        d["actual_percent"] = history_uplift(h) if h.date < today else None
        prev = previous_of(h)
        d["last_year_percent"] = history_uplift(prev) if prev else None
    return d


def upcoming(limit: int = 6, horizon_days: int = 120) -> list[Holiday]:
    today = timezone.localdate()
    qs = Holiday.objects.filter(is_active=True, date__lte=today + timedelta(days=horizon_days),
                                date__gte=today - timedelta(days=40)).order_by("date")
    return [h for h in qs if h.end >= today][:limit]


def alerts(tenant, *, notify: bool = True) -> list[dict]:
    """Tayyorgarlik oynasidagi bayramlar (≤ prep_days kun qoldi yoki bugun bayram) + xarid rejasining qisqachasi."""
    ensure_holidays()
    today = timezone.localdate()
    out = []
    for h in upcoming(limit=10, horizon_days=45):
        left = (h.date - today).days
        if left > h.prep_days:
            continue
        p = plan(tenant, holiday=h)
        hol_rev = sum(x["revenue"] for x in p["daily"] if x["holiday"])
        a = {**holiday_out(h), "short_count": p["short_count"], "total_cost": p["total_cost"], "buy_by": p["buy_by"],
             "revenue_holiday": hol_rev, "top_short": [ln["name"].get("uz") for ln in p["lines"] if ln["buy"] > 0][:4],
             "message": _message(h, left, p)}
        out.append(a)
        if notify and h.notified_at is None and left >= 0:
            h.notified_at = timezone.now()
            h.save(update_fields=["notified_at", "updated_at"])
            if weather.setting(tenant, "create_task", True):
                emit("forecast.holiday_soon", {"holiday_id": h.pk, "name": str(h), "date": h.date.strftime("%d.%m.%Y"),
                                               "buy_by": date.fromisoformat(p["buy_by"]).strftime("%d.%m.%Y"),
                                               "short_count": p["short_count"], "total_cost": p["total_cost"],
                                               "items": a["top_short"]}, tenant=tenant)
    return out


def _message(h: Holiday, left: int, p: dict) -> str:
    when = "bugun" if left <= 0 else "ertaga" if left == 1 else f"{left} kundan keyin"
    s = f"{h} — {when}. Kutilayotgan savdo {'+' if h.uplift_percent >= 0 else ''}{h.uplift_percent}%."
    if p["short_count"]:
        s += f" {p['short_count']} ta xomashyo yetmaydi — xarid taxminan {p['total_cost']:,} so'm.".replace(",", " ")
    else:
        s += " Ombor yetarli."
    return s
'@

Put 'backend\modules\forecast\weather.py' @'
"""
Ob-havo — Open-Meteo (bepul, kalit shart emas). 7 kunlik prognoz bazaga yoziladi va 3 soatda bir yangilanadi
(«lazy»: sahifa ochilganda). Internet bo'lmasa — oxirgi saqlangan prognoz ko'rsatiladi, xato chiqmaydi.
"""
from __future__ import annotations

import json
import logging
import urllib.request
from datetime import date, timedelta

from django.core.cache import cache
from django.db import connection
from django.utils import timezone

from .models import WeatherDay

log = logging.getLogger("forecast.weather")

CITIES = {
    "Toshkent": (41.3111, 69.2797), "Samarqand": (39.6542, 66.9597), "Buxoro": (39.7747, 64.4286),
    "Andijon": (40.7821, 72.3442), "Farg'ona": (40.3864, 71.7864), "Namangan": (40.9983, 71.6726),
    "Qarshi": (38.8606, 65.7891), "Nukus": (42.4600, 59.6166), "Urganch": (41.5500, 60.6333),
    "Jizzax": (40.1158, 67.8422), "Navoiy": (40.0844, 65.3792), "Termiz": (37.2242, 67.2783),
    "Guliston": (40.4897, 68.7842),
}
API_URL = ("https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lng}"
           "&daily=weather_code,temperature_2m_max,temperature_2m_min,precipitation_sum,"
           "precipitation_probability_max,wind_speed_10m_max&timezone=Asia%2FTashkent&forecast_days=7")
REFRESH_HOURS = 3
FAIL_TEXT = "Ob-havo serveriga ulanib bo'lmadi — oxirgi saqlangan prognoz ko'rsatilmoqda."


def setting(tenant, key, default):
    try:
        return (tenant.settings.get("modules", {}).get("forecast", {}) or {}).get(key, default)
    except Exception:
        return default


def location(tenant) -> dict:
    """Filial koordinatasi bo'lsa — o'sha, bo'lmasa sozlamadagi shahar (standart: Toshkent)."""
    from core.models import Branch
    b = Branch.objects.filter(deleted_at__isnull=True, is_active=True, lat__isnull=False, lng__isnull=False).first()
    if b:
        return {"name": b.name, "lat": float(b.lat), "lng": float(b.lng)}
    city = setting(tenant, "city", "Toshkent")
    lat, lng = CITIES.get(city, CITIES["Toshkent"])
    return {"name": city if city in CITIES else "Toshkent", "lat": lat, "lng": lng}


def _http_get(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=6) as r:
        return json.loads(r.read().decode())


def fetch(lat: float, lng: float) -> list[dict]:
    data = _http_get(API_URL.format(lat=lat, lng=lng))["daily"]
    out = []
    for i, d in enumerate(data["time"]):
        def v(key, _i=i):
            arr = data.get(key) or []
            return arr[_i] if _i < len(arr) and arr[_i] is not None else 0
        out.append({"date": date.fromisoformat(d), "t_max": float(v("temperature_2m_max")), "t_min": float(v("temperature_2m_min")),
                    "precip_mm": float(v("precipitation_sum")), "precip_prob": int(v("precipitation_probability_max")),
                    "wind": float(v("wind_speed_10m_max")), "code": int(v("weather_code"))})
    return out


def save_days(rows: list[dict], source: str = "open-meteo") -> int:
    for r in rows:
        WeatherDay.objects.update_or_create(date=r["date"], defaults={**{k: v for k, v in r.items() if k != "date"}, "source": source})
    return len(rows)


def refresh(tenant, force: bool = False) -> dict:
    """Prognoz eskirgan bo'lsa (3 soat) — yangilaydi. Natija: {"ok", "updated", "error"}."""
    today = timezone.localdate()
    last = WeatherDay.objects.filter(date__gte=today, source="open-meteo").order_by("-fetched_at").first()
    fresh = last and last.fetched_at > timezone.now() - timedelta(hours=REFRESH_HOURS)
    if fresh and not force:
        return {"ok": True, "updated": False}
    fail_key = f"forecast_wx_fail:{connection.schema_name}"
    if not force and cache.get(fail_key):          # yaqinda ulanib bo'lmagan — sahifani 6 soniya kutdirmaymiz
        return {"ok": False, "updated": False, "error": FAIL_TEXT}
    loc = location(tenant)
    try:
        n = save_days(fetch(loc["lat"], loc["lng"]))
        WeatherDay.objects.filter(date__lt=today - timedelta(days=30)).delete()
        cache.delete(fail_key)
        return {"ok": True, "updated": bool(n)}
    except Exception as e:  # tarmoq yo'q — eski prognoz qoladi
        log.warning("Ob-havoni olib bo'lmadi: %s", e)
        cache.set(fail_key, 1, 30 * 60)
        return {"ok": False, "updated": False, "error": FAIL_TEXT}


# ------------------------------------------------------------------ talqin
WMO = [
    ((0,), "☀️", "Ochiq"), ((1, 2), "🌤️", "Qisman bulutli"), ((3,), "☁️", "Bulutli"), ((45, 48), "🌫️", "Tuman"),
    ((51, 53, 55, 56, 57), "🌦️", "Mayda yomg'ir"), ((61, 63, 65, 66, 67), "🌧️", "Yomg'ir"), ((71, 73, 75, 77), "❄️", "Qor"),
    ((80, 81, 82), "🌧️", "Jala"), ((85, 86), "🌨️", "Qor yog'adi"), ((95, 96, 99), "⛈️", "Momaqaldiroq"),
]


def describe(code: int) -> tuple[str, str]:
    for codes, icon, label in WMO:
        if code in codes:
            return icon, label
    return "🌡️", "—"


def is_rainy(w: WeatherDay, tenant) -> bool:
    return w.precip_prob >= int(setting(tenant, "rain_probability", 60)) or w.precip_mm >= 5 or w.code in (61, 63, 65, 80, 81, 82, 95, 96, 99)


def is_snowy(w: WeatherDay) -> bool:
    return w.code in (71, 73, 75, 77, 85, 86)


def factor(w: WeatherDay | None, tenant) -> float:
    """Ob-havoning savdoga ta'siri (ko'paytuvchi). Sozlamada egasi foizlarni o'zgartiradi."""
    if w is None:
        return 1.0
    pct = 0
    if is_rainy(w, tenant) or is_snowy(w):
        pct += int(setting(tenant, "rain_effect", -10))
    if w.t_max >= int(setting(tenant, "hot_threshold", 35)):
        pct += int(setting(tenant, "hot_effect", -5))
    if w.t_max <= int(setting(tenant, "cold_threshold", 0)):
        pct += int(setting(tenant, "cold_effect", 0))
    return max(0.3, 1 + pct / 100)


def hints(w: WeatherDay, tenant) -> list[dict]:
    """Oddiy tilda maslahat: nima ko'proq/kamroq sotiladi, nimaga tayyorlanish kerak."""
    out = []
    hot, cold = int(setting(tenant, "hot_threshold", 35)), int(setting(tenant, "cold_threshold", 0))
    if w.t_max >= hot:
        out.append({"tone": "warn", "text": f"Issiq {round(w.t_max)}° — sovuq ichimlik, muz, salat va muzqaymoq zaxirasini oshiring. Issiq taomlar kamroq ketadi."})
    if w.t_max <= cold:
        out.append({"tone": "info", "text": f"Sovuq {round(w.t_max)}° — sho'rva, choy va issiq taomlar ko'proq ketadi."})
    if is_snowy(w):
        out.append({"tone": "warn", "text": "Qor — yo'llar sirpanchiq, ta'minotchi kechikishi mumkin. Xaridni bir kun oldin qiling."})
    elif is_rainy(w, tenant):
        out.append({"tone": "info", "text": f"Yomg'ir ({w.precip_prob}%) — zalga kamroq odam keladi, yetkazib berish va olib ketish ko'payadi."})
    if w.wind >= 40:
        out.append({"tone": "warn", "text": f"Kuchli shamol ({round(w.wind)} km/soat) — ochiq ayvon va terrasani yoping."})
    return out


def day_out(w: WeatherDay, tenant) -> dict:
    icon, label = describe(w.code)
    f = factor(w, tenant)
    return {"date": w.date.isoformat(), "t_max": round(w.t_max), "t_min": round(w.t_min), "precip_prob": w.precip_prob,
            "precip_mm": round(w.precip_mm, 1), "wind": round(w.wind), "code": w.code, "icon": icon, "label": label,
            "effect": round((f - 1) * 100), "hints": hints(w, tenant), "source": w.source}


def forecast_days(tenant, days: int = 7) -> list[WeatherDay]:
    today = timezone.localdate()
    return list(WeatherDay.objects.filter(date__gte=today, date__lt=today + timedelta(days=days)))
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

    name = payload.get("product_name") or "Mahsulot"
    create_task(_Req(), title=f"Ta'minot: {name} tugayapti",
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
            from public.services import set_modules
            set_modules(t, [*t.enabled_modules, "training", "crm", "forecast"])
            self.stdout.write(self.style.SUCCESS("Demo tenant: http://lazzat.localhost:8000  (egasi: +998901234567, OTP dev rejimida javobda qaytadi)"))
        self.stdout.write(self.style.SUCCESS("Tayyor."))
'@

Put 'backend\public\services.py' @'
"""
Tenant yaratish xizmati — "15 daqiqada ishga tushirish" ning backend qismi.

create_tenant(): sxema + migratsiyalar → owner foydalanuvchi → tizim rollari → preset modullar →
sayt temasi va bo'limlari → birinchi filial. Hammasi bitta funksiya, sehrgar va CLI shu funksiyani chaqiradi.
"""
from __future__ import annotations

import re
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from django_tenants.utils import schema_context

from core.models import Branch, Membership, Role, User
from core.modules import resolve_dependencies
from core.presets import DEFAULT_SETTINGS, PRESETS

from .models import Domain, Plan, Tenant

SYSTEM_ROLES = [
    ("owner", "Egasi", ["*"]),
    ("manager", "Filial menejeri", ["catalog.*", "cms.view", "core.branches.manage", "core.settings.view", "finance.*", "pos.*", "kds.*", "inventory.*", "hr.*", "tasks.*", "tables.*", "reservations.*", "payments.view", "training.*", "telegram.*", "crm.*", "forecast.*"]),
    ("cashier", "Kassir", ["crm.view", "pos.sell", "pos.shift", "catalog.view", "tasks.view", "tasks.create", "hr.view", "tables.view", "tables.serve", "reservations.view", "reservations.manage"]),
    ("waiter", "Ofitsiant", ["crm.view", "tables.view", "tables.serve", "reservations.view", "reservations.manage", "pos.sell", "catalog.view", "kds.view", "tasks.view", "tasks.create", "hr.view"]),
    ("cook", "Oshpaz", ["kds.view", "kds.cook", "catalog.view", "inventory.view", "forecast.view", "tasks.view", "tasks.create", "hr.view"]),
    ("courier", "Kuryer", ["delivery.courier", "tasks.view", "tasks.create", "hr.view"]),
    ("accountant", "Buxgalter", ["finance.*", "inventory.*", "forecast.view", "hr.payroll", "hr.view", "core.settings.view", "tasks.view", "tasks.create", "payments.view"]),
    ("marketer", "Marketolog", ["crm.*", "cms.*", "catalog.view", "tasks.view", "tasks.create", "tasks.edit", "telegram.view", "telegram.broadcast"]),
]
# O'qitish: har bir xodim o'z kurslari, topshiriqlari va standartlarini ko'radi
for _code, _name, _perms in SYSTEM_ROLES:
    if _code not in ("owner", "manager"):
        _perms.append("training.view")


def slugify_schema(slug: str) -> str:
    s = re.sub(r"[^a-z0-9_]", "_", slug.lower())
    if not re.match(r"^[a-z]", s):
        s = "t_" + s
    return s[:40]


@transaction.atomic
def create_tenant(*, name: str, slug: str, owner_phone: str, preset: str = "fast_food",
                  owner_name: str = "", plan_code: str | None = None, domain: str | None = None,
                  branch_name: str = "Asosiy filial", trial_days: int = 15) -> Tenant:
    if preset not in PRESETS:
        raise ValueError(f"Noma'lum preset: {preset}")
    cfg = PRESETS[preset]
    plan = Plan.objects.filter(code=plan_code).first() if plan_code else Plan.objects.filter(is_active=True).order_by("price_per_branch").first()

    tenant = Tenant(
        schema_name=slugify_schema(slug), name=name, slug=slug, preset=preset, plan=plan,
        enabled_modules=resolve_dependencies(list(cfg["modules"])),
        settings={**DEFAULT_SETTINGS},
        owner_phone=User.objects.normalize_phone(owner_phone),
        trial_ends_at=timezone.now() + timedelta(days=trial_days),
    )
    tenant.save()  # sxema yaratiladi + TENANT_APPS migratsiyalari qo'llanadi

    Domain.objects.create(tenant=tenant, domain=domain or f"{slug}.{settings.PLATFORM_DOMAIN}", is_primary=True)

    with schema_context(tenant.schema_name):
        roles = {}
        for code, rname, perms in SYSTEM_ROLES:
            roles[code], _ = Role.objects.get_or_create(code=code, defaults={"name": rname, "permissions": perms, "is_system": True})
        owner = User.objects.create_user(owner_phone, full_name=owner_name or "Egasi")
        Membership.objects.create(user=owner, role=roles["owner"])
        Branch.objects.create(name=branch_name, sort_order=0)

        # CMS moduli: tema + bo'limlar (modul o'zi `tenant.created` hodisasini tinglaydi)
        from core.events import emit
        emit("tenant.created", {"tenant_id": tenant.pk, "preset": preset, "name": name, "theme": cfg["theme"], "sections": cfg["sections"]}, tenant=tenant)

    return tenant


def set_modules(tenant: Tenant, codes: list[str]) -> list[str]:
    """Egasi modullarni yoqadi/o'chiradi. Tarif ruxsat bermasa — xato."""
    resolved = resolve_dependencies(codes)
    for c in resolved:
        if not tenant.can_enable(c):
            raise PermissionError(f"Tarif ushbu modulga ruxsat bermaydi: {c}")
    tenant.enabled_modules = resolved
    tenant.save(update_fields=["enabled_modules"])
    return resolved
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
    set_modules(t, [*t.enabled_modules, "training", "crm", "forecast"])
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

Put 'backend\tests\test_forecast.py' @'
"""
Bayram va ob-havo prognozi: tizim bayramlari (bir marta, o'chirilgani qaytmaydi), xarid rejasi (tarix × hafta kuni ×
bayram), ogohlantirish → bitta vazifa, o'tgan bayramning haqiqiy o'sishi, ob-havo (Open-Meteo, internet yo'q — xato
emas), boshqaruv paneli bloki, validatsiya, modul o'chsa 404.
"""
from datetime import date, datetime, time, timedelta

import pytest
from django.utils import timezone
from django_tenants.utils import schema_context

H = {"HTTP_HOST": "lazzat.testserver"}


def _offline(url):
    raise OSError("testda internet yo'q")


@pytest.fixture
def fc(tenant, monkeypatch):
    from modules.forecast import weather
    from public.services import set_modules
    monkeypatch.setattr(weather, "_http_get", _offline)                          # testlar internetga chiqmaydi
    with schema_context("public"):
        set_modules(tenant, sorted({*tenant.enabled_modules, "forecast", "inventory", "pos", "tasks"}))
        mods = dict(tenant.settings.get("modules") or {})
        mods["forecast"] = {"history_days": 28, "purchase_lead_days": 2, "create_task": True}
        tenant.settings = {**tenant.settings, "modules": mods}
        tenant.save()
    with schema_context("lazzat"):
        from django.core.cache import cache

        from modules.catalog.models import Category, Product
        from modules.forecast.models import Holiday, WeatherDay
        from modules.inventory.models import Ingredient, Recipe, RecipeLine
        from modules.pos.models import Order, OrderItem, OrderStatus
        cache.clear()
        from modules.forecast import services
        Holiday.objects.all().delete()
        services.ensure_holidays()
        Holiday.objects.update(is_active=False)                                   # tizim bayramlari sanaga bog'liq — o'chiramiz
        WeatherDay.objects.all().delete()
        Order.objects.all().delete()
        Ingredient.objects.update(is_active=False)
        cat, _ = Category.objects.get_or_create(name={"uz": "FC test", "ru": "", "en": ""})
        p = Product.objects.create(category=cat, name={"uz": "FC osh", "ru": "", "en": ""}, price=10000)
        ing = Ingredient.objects.create(name={"uz": "FC go'sht", "ru": "", "en": ""}, unit="kg", price=50000, stock=5, min_stock=2)
        rc = Recipe.objects.create(product=p, yield_qty=1)
        RecipeLine.objects.create(recipe=rc, ingredient=ing, qty=200)            # 200 g / porsiya
        today = timezone.localdate()
        for k in range(1, 15):                                                    # 14 kun: har kuni 10 porsiya
            d = today - timedelta(days=k)
            o = Order.objects.create(status=OrderStatus.PAID, total=100000, subtotal=100000,
                                     paid_at=timezone.make_aware(datetime.combine(d, time(13, 0))))
            OrderItem.objects.create(order=o, product=p, name="FC osh", qty=10, price=10000)
        yield {"product": p, "ing": ing, "today": today}


def _holiday(days_ahead, uplift=50, prep=7, code="", days=1):
    from modules.forecast.models import Holiday
    return Holiday.objects.create(code=code, name={"uz": "Test bayram", "ru": "", "en": ""},
                                  date=timezone.localdate() + timedelta(days=days_ahead), days=days,
                                  uplift_percent=uplift, prep_days=prep)


@pytest.mark.django_db
def test_builtin_holidays_once_and_disable_not_recreated(api, fc):
    with schema_context("lazzat"):
        from modules.forecast import services
        from modules.forecast.models import Holiday
        Holiday.objects.filter(date__year=2027).delete()
        assert services.ensure_year(2027) > 10
        assert services.ensure_year(2027) == 0                                   # ikkinchi marta — qo'shilmaydi
        nav = Holiday.objects.get(code="navruz", date__year=2027)
        assert nav.date == date(2027, 3, 21) and not nav.is_approx
        eid = Holiday.objects.get(code="kurban_eid", date__year=2027)
        assert eid.is_approx and eid.date == date(2027, 5, 16)
    r = api.delete(f"/api/v1/forecast/holidays/{nav.pk}")
    assert r.json() == {"ok": True, "disabled": True}
    with schema_context("lazzat"):
        services.ensure_year(2027)
        assert Holiday.objects.filter(code="navruz", date__year=2027).count() == 1
        assert not Holiday.objects.get(code="navruz", date__year=2027).is_active


@pytest.mark.django_db
def test_plan_math_history_weekday_holiday(api, fc):
    with schema_context("lazzat"):
        h = _holiday(3, uplift=50)
    p = api.get(f"/api/v1/forecast/plan?holiday_id={h.pk}").json()
    assert p["days"] == 4 and p["history"]["days"] == 14
    assert p["weekday_factors"] == [1.0] * 7                                      # bir xil savdo — hafta kuni ta'siri yo'q
    ln = next(x for x in p["lines"] if x["ingredient_id"] == fc["ing"].pk)
    # 4 kun: 1+1+1+1,5 = 4,5 × 10 porsiya × 0,2 kg = 9 kg; + min 2 − qoldiq 5 = 6 kg
    assert ln["need"] == pytest.approx(9.0) and ln["buy"] == 6.0 and ln["cost"] == 300000
    assert p["revenue_forecast"] == 450000 and p["revenue_normal"] == 400000
    assert p["short_count"] == 1 and p["total_cost"] == 300000
    assert p["products"][0]["qty"] == 15                                         # bayram kuni: 10 × 1,5
    assert p["buy_by"] == (fc["today"] + timedelta(days=1)).isoformat()           # 2 kun oldin
    r = api.get("/api/v1/forecast/plan?days=7").json()
    assert r["days"] == 7 and r["holiday"] is None


@pytest.mark.django_db
def test_alert_creates_single_task(api, fc):
    with schema_context("lazzat"):
        h = _holiday(3)
        _holiday(30)                                                              # hali uzoq — ogohlantirish yo'q
    ov = api.get("/api/v1/forecast/overview").json()
    assert [a["id"] for a in ov["alerts"]] == [h.pk]
    a = ov["alerts"][0]
    assert a["short_count"] == 1 and "3 kundan keyin" in a["message"] and a["top_short"] == ["FC go'sht"]
    api.get("/api/v1/forecast/overview")
    with schema_context("lazzat"):
        from modules.tasks.models import Task
        t = Task.objects.filter(title__startswith="Bayramga tayyorgarlik")
        assert t.count() == 1
        assert "300 000" in t.first().description and t.first().due_at is not None


@pytest.mark.django_db
def test_history_uplift_and_learn(api, fc):
    with schema_context("lazzat"):
        from modules.forecast import services
        from modules.pos.models import Order, OrderStatus
        today = fc["today"]
        past = _holiday(-3, code="xtest")
        Order.objects.create(status=OrderStatus.PAID, total=50000, subtotal=50000,          # o'sha kuni 150 000
                             paid_at=timezone.make_aware(datetime.combine(today - timedelta(days=3), time(19, 0))))
        assert services.history_uplift(past) == 50
        nxt = _holiday(40, uplift=5, code="xtest")
    r = api.post(f"/api/v1/forecast/holidays/{nxt.pk}/learn")
    assert r.status_code == 200 and r.json()["uplift_percent"] == 50
    with schema_context("lazzat"):
        lone = _holiday(20, code="")
    assert api.post(f"/api/v1/forecast/holidays/{lone.pk}/learn").status_code == 400


@pytest.mark.django_db
def test_weather_fetch_hints_factor_and_offline(api, fc, monkeypatch):
    from modules.forecast import weather
    today = fc["today"]
    fake = {"daily": {"time": [(today + timedelta(days=i)).isoformat() for i in range(3)],
                      "weather_code": [0, 63, 3], "temperature_2m_max": [38.2, 22, 18], "temperature_2m_min": [24, 14, 9],
                      "precipitation_sum": [0, 8.5, 0], "precipitation_probability_max": [0, 90, 10], "wind_speed_10m_max": [10, 45, 12]}}
    monkeypatch.setattr(weather, "_http_get", lambda url: fake)
    w = api.get("/api/v1/forecast/weather").json()
    assert w["ok"] and len(w["days"]) == 3 and w["location"]["name"] == "Toshkent"
    hot, rain = w["days"][0], w["days"][1]
    assert hot["icon"] == "☀️" and hot["effect"] == -5 and "Issiq 38°" in hot["hints"][0]["text"]
    assert rain["effect"] == -10 and any("Yomg'ir" in x["text"] for x in rain["hints"]) and any("shamol" in x["text"] for x in rain["hints"])
    p = api.get("/api/v1/forecast/plan?days=3").json()
    assert [d["factor"] for d in p["daily"]] == [0.95, 0.9, 1.0]

    monkeypatch.setattr(weather, "_http_get", _offline)
    r = api.post("/api/v1/forecast/weather/refresh")
    assert r.status_code == 503 and "ulanib bo'lmadi" in r.json()["detail"]
    assert len(api.get("/api/v1/forecast/weather").json()["days"]) == 3         # eski prognoz qoladi


@pytest.mark.django_db
def test_dashboard_block_validation_and_module_off(api, fc, tenant):
    with schema_context("lazzat"):
        _holiday(2)
    d = api.get("/api/v1/dashboard/overview").json()
    assert d["forecast"]["alerts"][0]["name"]["uz"] == "Test bayram"
    assert api.post("/api/v1/forecast/holidays", {"name": {"uz": " "}, "date": "2026-12-01"}).status_code == 400
    assert api.post("/api/v1/forecast/holidays", {"name": {"uz": "Ok"}, "date": "2026-12-01", "uplift_percent": 500}).status_code == 400
    r = api.post("/api/v1/forecast/holidays", {"name": {"uz": "Filial yubileyi"}, "date": "2026-12-01", "uplift_percent": 25})
    assert r.status_code == 200 and not r.json()["builtin"]
    assert api.delete(f"/api/v1/forecast/holidays/{r.json()['id']}").json()["disabled"] is False
    from public.services import set_modules
    with schema_context("public"):
        set_modules(tenant, [m for m in tenant.enabled_modules if m != "forecast"])
    assert api.get("/api/v1/forecast/overview").status_code == 404
    assert api.get("/api/v1/dashboard/overview").json()["forecast"] is None
'@

Put 'frontend\apps\admin\src\components\forecast\HolidayAlert.vue' @'
<script setup lang="ts">
/**
 * Bayram ogohlantirishi: nomi, necha kun qoldi, kutilayotgan savdo, xarid summasi va «qachongacha».
 * Boshqaruv paneli, Ombor va «Bayram va ob-havo» sahifasida bir xil ko'rinadi.
 */
import { computed } from 'vue'
import { RouterLink } from 'vue-router'
import { UiIcon, money } from '@restopos/ui'

const props = defineProps<{ a: any; compact?: boolean; showLink?: boolean }>()
const emit = defineEmits<{ (e: 'plan', id: number): void }>()
const when = computed(() => props.a.is_now ? 'Bugun bayram' : props.a.days_left === 1 ? 'Ertaga' : `${props.a.days_left} kun qoldi`)
const fmt = (s: string) => s.split('-').reverse().join('.')
const up = computed(() => `${props.a.uplift_percent >= 0 ? '+' : ''}${props.a.uplift_percent}%`)
</script>

<template>
  <div class="ha" :class="{ now: a.is_now, compact }">
    <div class="ic">🎉</div>
    <div class="bd">
      <div class="t">
        <b>{{ a.name.uz }}</b>
        <span class="pill">{{ when }}</span>
        <span v-if="a.is_approx" class="pill mute" title="Sana Diniy idora e'lonidan keyin aniqlanadi">taxminiy sana</span>
      </div>
      <p class="d">{{ fmt(a.date) }}<template v-if="a.days > 1"> – {{ fmt(a.end) }}</template> · kutilayotgan savdo <b>{{ up }}</b><template v-if="a.note"> · {{ a.note }}</template></p>
      <div class="st">
        <div><span>Xarid kerak</span><b :class="{ bad: a.short_count }">{{ a.short_count ? `${a.short_count} ta xomashyo` : 'Ombor yetarli' }}</b></div>
        <div v-if="a.short_count"><span>Taxminiy summa</span><b>{{ money(a.total_cost) }} so'm</b></div>
        <div v-if="a.short_count"><span>Qachongacha</span><b>{{ fmt(a.buy_by) }}</b></div>
        <div v-if="!compact && a.revenue_holiday"><span>Bayram savdosi (prognoz)</span><b>{{ money(a.revenue_holiday) }} so'm</b></div>
      </div>
      <p v-if="a.top_short?.length && !compact" class="ts">Birinchi navbatda: {{ a.top_short.join(', ') }}</p>
    </div>
    <div class="ac">
      <RouterLink v-if="showLink" :to="`/inventory?tab=plan&holiday=${a.id}`" class="btn">Xarid rejasi <UiIcon name="chevron" :size="14" style="transform: rotate(-90deg)" /></RouterLink>
      <button v-else type="button" class="btn" @click="emit('plan', a.id)">Xarid rejasi <UiIcon name="chevron" :size="14" style="transform: rotate(-90deg)" /></button>
    </div>
  </div>
</template>

<style scoped>
.ha { display: grid; grid-template-columns: 44px minmax(0, 1fr) auto; gap: 14px; align-items: center; padding: 14px 16px; border-radius: 16px;
  background: var(--warn-tint); border: 1px solid color-mix(in srgb, var(--warn) 40%, var(--line)); color: var(--ink); }
.ha.now { background: var(--ok-tint); border-color: color-mix(in srgb, var(--ok) 40%, var(--line)); }
.ic { width: 44px; height: 44px; border-radius: 12px; background: var(--surface); display: grid; place-items: center; font-size: 22px; }
.bd { min-width: 0; display: flex; flex-direction: column; gap: 4px; }
.t { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; } .t b { font-family: var(--font-display); font-size: var(--fs-l); font-weight: 800; }
.pill { font-size: var(--fs-xs); font-weight: 800; padding: 2px 8px; border-radius: 99px; background: var(--warn); color: #fff; white-space: nowrap; }
.now .pill { background: var(--ok); } .pill.mute { background: var(--surface); color: var(--muted); border: 1px solid var(--line); }
.d { margin: 0; font-size: var(--fs-s); color: var(--ink-2); }
.st { display: flex; gap: 18px; flex-wrap: wrap; margin-top: 4px; }
.st div { display: flex; flex-direction: column; } .st span { font-size: var(--fs-xs); color: var(--muted); } .st b { font-size: var(--fs-s); font-variant-numeric: tabular-nums; } .st b.bad { color: var(--danger); }
.ts { margin: 2px 0 0; font-size: var(--fs-xs); color: var(--ink-2); }
.btn { display: inline-flex; align-items: center; gap: 4px; min-height: var(--touch); padding: 0 14px; border-radius: 10px; border: 0; background: var(--ink); color: var(--surface);
  font: inherit; font-weight: 800; font-size: var(--fs-s); text-decoration: none; cursor: pointer; white-space: nowrap; }
.compact { padding: 12px 14px; }
@media (max-width: 720px) {
  .ha { grid-template-columns: 40px minmax(0, 1fr); } .ic { width: 40px; height: 40px; }
  .ac { grid-column: 1 / -1; } .btn { width: 100%; justify-content: center; }
  .st { gap: 12px; }
}
</style>
'@

Put 'frontend\apps\admin\src\components\forecast\WeatherStrip.vue' @'
<script setup lang="ts">
/** 7 kunlik ob-havo: ikonka, harorat, yog'in ehtimoli, savdoga ta'siri (%) va maslahatlar. */
import { computed } from 'vue'

const props = defineProps<{ days: any[]; hints?: number }>()
const WD = ['Ya', 'Du', 'Se', 'Ch', 'Pa', 'Ju', 'Sh']
const n = new Date()
const today = `${n.getFullYear()}-${String(n.getMonth() + 1).padStart(2, '0')}-${String(n.getDate()).padStart(2, '0')}`
function dayLabel(s: string, i: number) {
  if (i === 0 && s === today) return 'Bugun'
  const d = new Date(s + 'T00:00:00')
  return i === 1 && props.days[0]?.date === today ? 'Ertaga' : `${WD[d.getDay()]} ${String(d.getDate()).padStart(2, '0')}`
}
const shown = computed(() => {
  const out: { date: string; tone: string; text: string }[] = []
  for (const [i, d] of props.days.entries()) for (const h of d.hints ?? []) out.push({ date: dayLabel(d.date, i), ...h })
  return out.slice(0, props.hints ?? 3)
})
</script>

<template>
  <div class="ws">
    <ul class="days">
      <li v-for="(d, i) in days" :key="d.date" :class="{ on: i === 0 }" :title="`${d.label} · yog'in ${d.precip_prob}% · shamol ${d.wind} km/soat`">
        <small>{{ dayLabel(d.date, i) }}</small>
        <span class="e">{{ d.icon }}</span>
        <b>{{ d.t_max }}°</b><span class="mn">{{ d.t_min }}°</span>
        <span class="pp" :class="{ hi: d.precip_prob >= 50 }">💧{{ d.precip_prob }}%</span>
        <span v-if="d.effect" class="ef" :class="d.effect > 0 ? 'up' : 'dn'">{{ d.effect > 0 ? '+' : '' }}{{ d.effect }}%</span>
      </li>
    </ul>
    <ul v-if="shown.length" class="hints">
      <li v-for="(h, i) in shown" :key="i" :class="h.tone"><b>{{ h.date }}:</b> {{ h.text }}</li>
    </ul>
  </div>
</template>

<style scoped>
.ws { display: flex; flex-direction: column; gap: 12px; }
.days { list-style: none; margin: 0; padding: 0; display: grid; grid-template-columns: repeat(7, minmax(0, 1fr)); gap: 6px; }
.days li { display: flex; flex-direction: column; align-items: center; gap: 2px; padding: 8px 2px; border-radius: 12px; background: var(--surface-2); border: 1px solid var(--line-2); min-width: 0; }
.days li.on { background: var(--accent-tint); border-color: color-mix(in srgb, var(--accent) 35%, var(--line)); }
.days small { font-size: 11px; font-weight: 700; color: var(--muted); white-space: nowrap; }
.e { font-size: 22px; line-height: 1.2; }
.days b { font-family: var(--font-display); font-size: var(--fs-m); font-weight: 800; }
.mn { font-size: var(--fs-xs); color: var(--muted); }
.pp { font-size: 11px; color: var(--muted); white-space: nowrap; } .pp.hi { color: var(--info); font-weight: 700; }
.ef { font-size: 11px; font-weight: 800; padding: 0 6px; border-radius: 99px; } .ef.dn { background: var(--danger-tint); color: var(--danger); } .ef.up { background: var(--ok-tint); color: var(--ok); }
.hints { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 6px; }
.hints li { font-size: var(--fs-s); padding: 8px 10px; border-radius: 10px; background: var(--info-tint); color: var(--ink); line-height: 1.35; }
.hints li.warn { background: var(--warn-tint); }
@media (max-width: 720px) {
  .days { gap: 3px; } .days li { padding: 6px 0; border-radius: 9px; } .e { font-size: 18px; } .days b { font-size: var(--fs-s); }
  .days small, .pp, .ef { font-size: 10px; } .ef { padding: 0 3px; }
}
</style>
'@

Put 'frontend\apps\admin\src\router\index.ts' @'
import { createRouter, createWebHistory } from 'vue-router'
import { useAuth } from '@/stores/auth'

export const router = createRouter({
  history: createWebHistory('/admin/'),
  routes: [
    { path: '/login', component: () => import('@/views/LoginView.vue'), meta: { public: true } },
    {
      path: '/', component: () => import('@/layouts/AppShell.vue'),
      children: [
        { path: '', name: 'dashboard', component: () => import('@/views/DashboardView.vue') },
        { path: 'catalog', name: 'catalog', component: () => import('@/views/CatalogView.vue'), meta: { module: 'catalog' } },
        { path: 'tasks', name: 'tasks', component: () => import('@/views/TasksView.vue'), meta: { module: 'tasks' } },
        { path: 'pos', name: 'pos', component: () => import('@/views/PosView.vue'), meta: { module: 'pos' } },
        { path: 'kds', name: 'kds', component: () => import('@/views/KdsView.vue'), meta: { module: 'kds' } },
        { path: 'tables', name: 'tables', component: () => import('@/views/TablesView.vue'), meta: { module: 'tables' } },
        { path: 'reservations', name: 'reservations', component: () => import('@/views/ReservationsView.vue'), meta: { module: 'reservations' } },
        { path: 'inventory', name: 'inventory', component: () => import('@/views/InventoryView.vue'), meta: { module: 'inventory' } },
        { path: 'forecast', name: 'forecast', component: () => import('@/views/ForecastView.vue'), meta: { module: 'forecast', title: 'Bayram va ob-havo' } },
        { path: 'hr', name: 'hr', component: () => import('@/views/HrView.vue'), meta: { module: 'hr' } },
        { path: 'hr/employee/:id', name: 'hr-employee', component: () => import('@/views/EmployeeProfileView.vue'), meta: { module: 'hr', title: 'Xodim profili' } },
        { path: 'recruiting', name: 'recruiting', component: () => import('@/views/RecruitView.vue'), meta: { module: 'hr', title: 'Ishga olish' } },
        { path: 'kpi', name: 'kpi', component: () => import('@/views/KpiView.vue'), meta: { module: 'hr', title: 'Baholash va KPI' } },
        { path: 'reports', name: 'reports', component: () => import('@/views/ReportsView.vue'), meta: { module: 'finance' } },
        { path: 'training', name: 'training', component: () => import('@/views/TrainingView.vue'), meta: { module: 'training' } },
        { path: 'training/course/:id', name: 'training-course', component: () => import('@/views/TrainingCourseView.vue'), meta: { module: 'training' } },
        { path: 'training/lesson/:id', name: 'training-lesson', component: () => import('@/views/TrainingLessonView.vue'), meta: { module: 'training' } },
        { path: 'training/quiz/:id', name: 'training-quiz', component: () => import('@/views/TrainingQuizView.vue'), meta: { module: 'training' } },
        { path: 'training/certificate/:id', name: 'training-cert', component: () => import('@/views/TrainingCertView.vue'), meta: { module: 'training' } },
        { path: 'crm', name: 'crm', component: () => import('@/views/CrmView.vue'), meta: { module: 'crm', title: 'Mijozlar va bonus' } },
        { path: 'telegram', name: 'telegram', component: () => import('@/views/TelegramView.vue'), meta: { module: 'telegram' } },
        { path: 'site', name: 'site', component: () => import('@/views/SiteView.vue'), meta: { module: 'cms' } },
        { path: 'branches', name: 'branches', component: () => import('@/views/BranchesView.vue') },
        { path: 'users', name: 'users', component: () => import('@/views/UsersView.vue') },
        { path: 'modules', name: 'modules', component: () => import('@/views/ModulesView.vue') },
        { path: 'settings', name: 'settings', component: () => import('@/views/SettingsView.vue') },
        { path: 'audit', name: 'audit', component: () => import('@/views/AuditView.vue'), meta: { title: "O'zgarishlar tarixi" } },
        { path: ':pathMatch(.*)*', redirect: '/' },
      ],
    },
  ],
})

router.beforeEach(async (to) => {
  const a = useAuth()
  if (to.meta.public) return true
  if (!a.me) { try { await a.load() } catch { return '/login' } }
  if (to.meta.module && !a.me!.tenant.enabled_modules.includes(to.meta.module as string)) return '/modules'
  return true
})
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

const a = useAuth(), router = useRouter()
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
  timer = window.setInterval(() => { if (period.value === 'today' && !document.hidden) load() }, 60000)
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

Put 'frontend\apps\admin\src\views\ForecastView.vue' @'
<script setup lang="ts">
/**
 * Bayram va ob-havo: yaqin bayram ogohlantirishlari · 7 kunlik ob-havo va maslahatlar · yil bo'yicha bayramlar
 * (tizim bayramlari avtomatik, egasi foiz/sana/ogohlantirishni o'zgartiradi yoki o'z bayramini qo'shadi).
 */
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '@restopos/api'
import { UiButton, UiCard, UiChip, UiDrawer, UiEmpty, UiIcon, UiInput, UiSelect, UiToggle, toast } from '@restopos/ui'
import { useAuth } from '@/stores/auth'
import HolidayAlert from '@/components/forecast/HolidayAlert.vue'
import WeatherStrip from '@/components/forecast/WeatherStrip.vue'

const a = useAuth(), router = useRouter()
const O = ref<any>(null)
const year = ref(new Date().getFullYear())
const list = ref<any[]>([])
const showOff = ref(false)
const canEdit = computed(() => a.can('forecast.edit'))
const refreshing = ref(false)

async function load() {
  O.value = await api.get('/forecast/overview')
  await loadList()
}
async function loadList() { list.value = await api.get('/forecast/holidays', { year: year.value }) }
onMounted(load)
watch(year, loadList)

const rows = computed(() => list.value.filter(h => showOff.value || h.is_active))
const KIND_TONE: Record<string, any> = { official: 'info', religious: 'ok', commercial: 'accent', season: 'warn', local: 'neutral' }
const WD = ['Yakshanba', 'Dushanba', 'Seshanba', 'Chorshanba', 'Payshanba', 'Juma', 'Shanba']
const fmtD = (x: string) => x.split('-').reverse().join('.')
const wd = (x: string) => WD[new Date(x + 'T00:00:00').getDay()]
const pct = (v: number | null | undefined) => v == null ? '—' : `${v > 0 ? '+' : ''}${v}%`
function leftLabel(h: any): [string, any] {
  if (h.is_now) return ['Bugun', 'ok']
  if (h.is_past) return ["O'tdi", 'neutral']
  if (h.days_left <= h.prep_days) return [`${h.days_left} kun`, 'warn']
  return [`${h.days_left} kun`, 'neutral']
}

async function refreshWeather() {
  refreshing.value = true
  try { O.value.weather = await api.post('/forecast/weather/refresh'); toast('Ob-havo yangilandi') }
  catch (e: any) { toast(e.detail ?? 'Xato', 'danger') } finally { refreshing.value = false }
}

// ---- tahrirlash
const ed = ref<any>(null)
function openEd(h?: any) {
  ed.value = h ? { ...h, name: { ...h.name } }
    : { name: { uz: '', ru: '', en: '' }, date: `${year.value}-${String(new Date().getMonth() + 1).padStart(2, '0')}-${String(new Date().getDate()).padStart(2, '0')}`, days: 1, kind: 'local', uplift_percent: 20, prep_days: 7, is_approx: false, is_active: true, note: '' }
}
async function save() {
  const body = { name: ed.value.name, date: ed.value.date, days: Number(ed.value.days), kind: ed.value.kind, uplift_percent: Number(ed.value.uplift_percent),
    prep_days: Number(ed.value.prep_days), is_approx: !!ed.value.is_approx, is_active: !!ed.value.is_active, note: ed.value.note ?? '' }
  try {
    ed.value.id ? await api.put(`/forecast/holidays/${ed.value.id}`, body) : await api.post('/forecast/holidays', body)
    ed.value = null; toast('Saqlandi'); await load()
  } catch (e: any) { toast(e.detail ?? 'Xato', 'danger') }
}
async function learn() {
  try { const r = await api.post(`/forecast/holidays/${ed.value.id}/learn`); ed.value.uplift_percent = r.uplift_percent; toast(`O'tgan yilgi natija: ${pct(r.uplift_percent)}`); await loadList() }
  catch (e: any) { toast(e.detail ?? 'Xato', 'danger') }
}
async function remove() {
  if (!confirm(ed.value.builtin ? "Bu bayram o'chirib qo'yiladi (ogohlantirish chiqmaydi). Davom etilsinmi?" : "Bayram o'chirilsinmi?")) return
  try { await api.del(`/forecast/holidays/${ed.value.id}`); ed.value = null; await load() } catch (e: any) { toast(e.detail ?? 'Xato', 'danger') }
}
</script>

<template>
  <div v-if="O" class="fc">
    <div v-if="O.alerts.length" class="alerts">
      <HolidayAlert v-for="al in O.alerts" :key="al.id" :a="al" @plan="id => router.push(`/inventory?tab=plan&holiday=${id}`)" />
    </div>

    <div class="grid">
      <UiCard :title="`Ob-havo — 7 kun · ${O.weather.location.name}`" subtitle="Yomg'ir, jazirama va sovuq savdoga ta'sir qiladi — xarid rejasida hisobga olinadi">
        <template #actions>
          <UiButton v-if="canEdit" size="s" variant="ghost" :loading="refreshing" @click="refreshWeather()"><UiIcon name="repeat" :size="14" /> Yangilash</UiButton>
        </template>
        <p v-if="O.weather.demo" class="note">Namunaviy prognoz — internetga ulanganda haqiqiy ob-havo (Open-Meteo) o'zi yuklanadi.</p>
        <p v-else-if="O.weather.error" class="note">{{ O.weather.error }}</p>
        <WeatherStrip v-if="O.weather.days.length" :days="O.weather.days" :hints="6" />
        <UiEmpty v-else title="Ob-havo ma'lumoti yo'q" text="Internet ulanganda «Yangilash» tugmasini bosing. Shaharni Modullar → Sozlamalar'da tanlang." />
      </UiCard>

      <UiCard title="Qanday hisoblanadi">
        <ol class="how">
          <li><b>Odatiy savdo.</b> Oxirgi 4 hafta sotuvidan har taomning kunlik o'rtachasi olinadi.</li>
          <li><b>Kun ko'paytuvchisi.</b> Hafta kuni (juma-shanba yuqori) × bayram (+%) × ob-havo.</li>
          <li><b>Xomashyo.</b> Taom × tex-karta = ehtiyoj. Ehtiyoj + minimal qoldiq − ombordagi qoldiq = xarid.</li>
          <li><b>Ogohlantirish.</b> Bayramdan N kun oldin panelda chiqadi va ta'minot vazifasi ochiladi.</li>
        </ol>
        <p class="note">Bayram foizini o'tgan yilgi haqiqiy savdodan olish mumkin — bayramni oching va «O'tgan yildan olish»ni bosing.</p>
      </UiCard>
    </div>

    <UiCard :padded="false" title="Bayramlar va muhim kunlar" subtitle="Kutilgan — prognozda ishlatiladigan foiz · Haqiqiy — savdo tarixidan">
      <template #actions>
        <div class="yr">
          <button type="button" aria-label="Oldingi yil" @click="year--"><UiIcon name="chevron" :size="16" style="transform: rotate(90deg)" /></button>
          <b>{{ year }}</b>
          <button type="button" aria-label="Keyingi yil" @click="year++"><UiIcon name="chevron" :size="16" style="transform: rotate(-90deg)" /></button>
        </div>
        <button class="chip-btn" :class="{ on: showOff }" @click="showOff = !showOff">O'chirilganlar</button>
        <UiButton v-if="canEdit" variant="brand" size="s" @click="openEd()"><UiIcon name="plus" :size="14" /> Bayram</UiButton>
      </template>
      <div class="lst">
        <div class="l-h"><span>Sana</span><span>Bayram</span><span>Qoldi</span><span>Kutilgan</span><span>Haqiqiy</span><span>Ogohlantirish</span></div>
        <button v-for="h in rows" :key="h.id" type="button" class="l-r" :class="{ off: !h.is_active, past: h.is_past }" @click="canEdit && openEd(h)">
          <span class="dt"><b>{{ fmtD(h.date) }}</b><small>{{ wd(h.date) }}{{ h.days > 1 ? ` · ${h.days} kun` : '' }}</small></span>
          <span class="nm"><b>{{ h.name.uz }}</b><small><UiChip :tone="KIND_TONE[h.kind]">{{ h.kind_label }}</UiChip><UiChip v-if="h.is_approx" tone="neutral">taxminiy</UiChip><UiChip v-if="!h.is_active" tone="danger">o'chiq</UiChip></small></span>
          <span><UiChip :tone="leftLabel(h)[1]">{{ leftLabel(h)[0] }}</UiChip></span>
          <span class="n" :class="h.uplift_percent >= 0 ? 'up' : 'dn'">{{ pct(h.uplift_percent) }}</span>
          <span class="n mut" :title="h.is_past ? 'Shu bayramdagi haqiqiy o\'sish' : 'O\'tgan yilgi haqiqiy o\'sish'">{{ pct(h.is_past ? h.actual_percent : h.last_year_percent) }}<small v-if="!h.is_past && h.last_year_percent != null"> o'tgan yil</small></span>
          <span class="mut">{{ h.prep_days }} kun oldin</span>
        </button>
        <UiEmpty v-if="!rows.length" title="Bu yil uchun bayram yo'q" text="«Bayram» tugmasi bilan qo'shing." />
      </div>
    </UiCard>

    <UiDrawer :open="!!ed" :title="ed?.id ? ed.name.uz : 'Yangi bayram'" width="480px" @close="ed = null">
      <template v-if="ed">
        <UiInput v-model="ed.name.uz" label="Nomi" placeholder="Masalan: Filial yubileyi" />
        <UiInput v-model="ed.name.ru" label="Nomi (ru)" />
        <div class="g2">
          <UiInput v-model="ed.date" type="date" label="Sana" />
          <UiInput v-model="ed.days" type="number" label="Necha kun" />
          <UiInput v-model="ed.uplift_percent" type="number" label="Savdo o'zgarishi" suffix="%" />
          <UiInput v-model="ed.prep_days" type="number" label="Necha kun oldin ogohlantirish" />
        </div>
        <UiSelect v-model="ed.kind" label="Turi" :options="O.kinds.map((k: any) => ({ value: k.code, label: k.label }))" />
        <UiInput v-model="ed.note" label="Izoh (tayyorgarlik)" placeholder="Maxsus menyu, bron, qo'shimcha xodim…" />
        <div class="tg">
          <UiToggle v-model="ed.is_approx" label="Sana taxminiy" />
          <UiToggle v-model="ed.is_active" label="Ogohlantirish yoqilgan" />
        </div>
        <div v-if="ed.id && ed.builtin" class="lrn">
          <span>O'tgan yilgi haqiqiy o'sish: <b>{{ pct(ed.last_year_percent) }}</b></span>
          <UiButton size="s" variant="ghost" :disabled="ed.last_year_percent == null" @click="learn()">O'tgan yildan olish</UiButton>
        </div>
        <p class="note">Masalan, +40% — bayram kuni odatdagidan 40% ko'p sotuv kutiladi, xomashyo shunga qarab ko'proq xarid qilinadi.</p>
      </template>
      <template #footer>
        <UiButton v-if="ed?.id" variant="danger" @click="remove()">{{ ed.builtin ? "O'chirib qo'yish" : "O'chirish" }}</UiButton>
        <div style="flex: 1"></div>
        <UiButton variant="ghost" @click="ed = null">Bekor</UiButton><UiButton variant="brand" @click="save()">Saqlash</UiButton>
      </template>
    </UiDrawer>
  </div>
</template>

<style scoped>
.fc { display: flex; flex-direction: column; gap: 14px; }
.alerts { display: flex; flex-direction: column; gap: 10px; }
.grid { display: grid; grid-template-columns: minmax(0, 1.6fr) minmax(0, 1fr); gap: 14px; align-items: start; }
.grid > :deep(.ui-card) { min-width: 0; }
.note { margin: 0 0 10px; font-size: var(--fs-xs); color: var(--muted); background: var(--surface-2); border-radius: 10px; padding: 8px 10px; }
.how { margin: 0 0 10px; padding-left: 18px; display: flex; flex-direction: column; gap: 8px; font-size: var(--fs-s); color: var(--ink-2); }
.yr { display: inline-flex; align-items: center; gap: 4px; border: 1px solid var(--line); border-radius: 10px; padding: 2px; }
.yr button { border: 0; background: transparent; width: 32px; height: 32px; border-radius: 8px; cursor: pointer; color: var(--ink); display: grid; place-items: center; }
.yr button:hover { background: var(--surface-2); } .yr b { font-variant-numeric: tabular-nums; padding: 0 4px; }
.chip-btn { display: inline-flex; align-items: center; min-height: 36px; padding: 0 12px; border-radius: 10px; border: 1px solid var(--line); background: var(--surface); font: inherit; font-weight: 700; font-size: var(--fs-s); cursor: pointer; }
.chip-btn.on { background: var(--accent-tint); border-color: var(--accent); color: var(--accent); }
.lst { display: flex; flex-direction: column; }
.l-h, .l-r { display: grid; grid-template-columns: 120px minmax(0, 2fr) 90px 90px 110px 120px; gap: 10px; align-items: center; padding: 9px 14px; text-align: left; font-size: var(--fs-s); }
.l-h { font-size: var(--fs-xs); font-weight: 700; color: var(--muted); background: var(--surface-2); }
.l-r { border: 0; border-top: 1px solid var(--line-2); background: transparent; font: inherit; color: var(--ink); cursor: pointer; }
.l-r:hover { background: var(--accent-tint); } .l-r.off { opacity: .5; } .l-r.past .dt b { color: var(--muted); }
.dt, .nm { display: flex; flex-direction: column; gap: 3px; min-width: 0; } .dt small { color: var(--muted); font-size: var(--fs-xs); }
.nm b { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; } .nm small { display: flex; gap: 4px; flex-wrap: wrap; }
.n { font-weight: 800; font-variant-numeric: tabular-nums; } .n small { font-weight: 500; font-size: 11px; } .up { color: var(--ok); } .dn { color: var(--danger); } .mut { color: var(--muted); }
.g2 { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
.tg { display: flex; gap: 18px; flex-wrap: wrap; margin: 6px 0; }
.lrn { display: flex; align-items: center; justify-content: space-between; gap: 10px; padding: 10px 12px; border-radius: 10px; background: var(--surface-2); font-size: var(--fs-s); margin: 8px 0; flex-wrap: wrap; }
@media (max-width: 1100px) { .grid { grid-template-columns: minmax(0, 1fr); } }
@media (max-width: 720px) {
  .l-h { display: none; }
  .l-r { grid-template-columns: 1fr 1fr 1fr; gap: 6px 10px; }
  .l-r > .nm { grid-column: 1 / -1; order: -1; }
  .l-r > span:last-child { display: none; }
  .g2 { grid-template-columns: 1fr; }
}
</style>
'@

Put 'frontend\apps\admin\src\views\InventoryView.vue' @'
<script setup lang="ts">
/**
 * Ombor va tannarx: Xomashyo (narx/qoldiq) · Kirim (bozorlik) · Tex-karta (taom → xomashyo → tannarx jonli) · Harakatlar.
 * Bozor narxi o'zgardi → kirim kiritiladi → barcha taomlar tannarxi o'zi yangilanadi (backend).
 * «Xarid rejasi» (forecast moduli): bayram/ob-havo/hafta kuni hisobga olingan ehtiyoj → bir bosishda kirimga.
 */
import { computed, onMounted, ref, watch } from 'vue'
import { api } from '@restopos/api'
import { UiButton, UiCard, UiChip, UiDrawer, UiEmpty, UiIcon, UiInput, UiSelect, money, t, toast } from '@restopos/ui'
import { useAuth } from '@/stores/auth'
import { useUi } from '@/stores/ui'
import { useRoute } from 'vue-router'
import HolidayAlert from '@/components/forecast/HolidayAlert.vue'

const a = useAuth(), ui = useUi(), route = useRoute()
type Tab = 'ingredients' | 'purchase' | 'recipes' | 'movements' | 'plan'
const TAB_Q: Record<string, Tab> = { plan: 'plan', purchase: 'purchase', purchases: 'purchase', stock: 'ingredients', ingredients: 'ingredients', recipes: 'recipes', movements: 'movements' }
const hasFc = computed(() => a.hasModule('forecast') && a.can('forecast.view'))
const tab = ref<Tab>(TAB_Q[String(route.query.tab ?? '')] ?? 'recipes')
if (tab.value === 'plan' && !hasFc.value) tab.value = 'recipes'
const summary = ref<any>(null)
const ingredients = ref<any[]>([])
const recipes = ref<any[]>([])
const purchases = ref<any[]>([])
const movements = ref<any[]>([])
const suppliers = ref<any[]>([])
const q = ref('')
const onlyLow = ref(false)
const canEdit = computed(() => a.can('inventory.edit'))

const UNIT: Record<string, string> = { kg: 'kg', l: 'l', dona: 'dona' }
const SUB: Record<string, string> = { kg: 'g', l: 'ml', dona: 'dona' }

async function load() {
  summary.value = await api.get('/inventory/summary')
  ingredients.value = await api.get('/inventory/ingredients', { q: q.value || undefined, low: onlyLow.value || undefined })
  if (tab.value === 'recipes') recipes.value = await api.get('/inventory/recipes')
  if (tab.value === 'purchase') { purchases.value = await api.get('/inventory/purchases'); suppliers.value = await api.get('/inventory/suppliers') }
  if (tab.value === 'movements') movements.value = await api.get('/inventory/movements')
  if (tab.value === 'plan') await loadPlan()
}
onMounted(async () => {
  if (hasFc.value) fc.value = await api.get('/forecast/overview').catch(() => null)
  await load()
})
watch([tab, onlyLow], load)

// ---- xarid rejasi (bayram / ob-havo prognozi)
const fc = ref<any>(null)
const planSel = ref<string>(route.query.holiday ? `h${route.query.holiday}` : '7')
const plan = ref<any>(null)
const planLoading = ref(false)
const onlyBuy = ref(true)
const planOpts = computed(() => [
  { value: '7', label: 'Keyingi 7 kun' }, { value: '14', label: 'Keyingi 14 kun' },
  ...(fc.value?.upcoming ?? []).filter((h: any) => !h.is_past).map((h: any) => ({ value: `h${h.id}`, label: `🎉 ${h.name.uz} — ${h.date.split('-').reverse().join('.')}` })),
])
async function loadPlan() {
  planLoading.value = true
  try {
    const v = planSel.value
    plan.value = await api.get('/forecast/plan', v.startsWith('h') ? { holiday_id: Number(v.slice(1)) } : { days: Number(v) })
  } catch (e: any) { toast(e.detail ?? 'Xato', 'danger'); plan.value = null } finally { planLoading.value = false }
}
watch(planSel, () => { if (tab.value === 'plan') loadPlan() })
function openPlan(id: number) { planSel.value = `h${id}`; if (tab.value !== 'plan') tab.value = 'plan'; else loadPlan() }
const planLines = computed(() => (plan.value?.lines ?? []).filter((l: any) => !onlyBuy.value || l.buy > 0))
const fmtD = (x: string) => x.split('-').reverse().join('.')
const WD = ['Ya', 'Du', 'Se', 'Ch', 'Pa', 'Ju', 'Sh']
const wd = (x: string) => WD[new Date(x + 'T00:00:00').getDay()]
const num = (v: number) => String(+v.toFixed(2)).replace('.', ',')
function toPurchase(supplierId?: number | null, all = true) {
  const src = (plan.value?.lines ?? []).filter((l: any) => l.buy > 0 && (all || (l.supplier_id ?? null) === (supplierId ?? null)))
  if (!src.length) return
  pur.value = {
    supplier_id: !all && supplierId ? String(supplierId) : '',
    note: plan.value.holiday ? `${plan.value.holiday.name.uz} uchun xarid` : `Xarid rejasi ${fmtD(plan.value.start)}–${fmtD(plan.value.end)}`,
    lines: src.map((l: any) => ({ ingredient_id: String(l.ingredient_id), qty: l.buy, unit_price: l.price })),
  }
  tab.value = 'purchase'
  toast('Qatorlar kirim formasiga qo\'yildi — narxni tekshirib, «Kirimni o\'tkazish»ni bosing')
}
async function copyList() {
  const lines = (plan.value?.lines ?? []).filter((l: any) => l.buy > 0)
  const txt = [`🛒 Xarid ro'yxati${plan.value.holiday ? ` — ${plan.value.holiday.name.uz}` : ''} (${fmtD(plan.value.buy_by)} gacha)`,
    ...lines.map((l: any) => `• ${t(l.name, ui.lang)} — ${num(l.buy)} ${UNIT[l.unit]}`)].join('\n')
  try { await navigator.clipboard.writeText(txt); toast('Ro\'yxat nusxalandi — Telegram\'da ta\'minotchiga yuboring') } catch { toast('Nusxalab bo\'lmadi', 'danger') }
}

// ---- xomashyo
const ingDrawer = ref(false)
const ing = ref<any>(null)
function openIng(i?: any) {
  ing.value = i ? { ...i, name: { ...i.name } } : { name: { uz: '', ru: '', en: '' }, category: '', unit: 'kg', price: 0, min_stock: 0, is_active: true }
  ingDrawer.value = true
}
async function saveIng() {
  const body = { ...ing.value, price: Number(ing.value.price), min_stock: Number(ing.value.min_stock) }
  try {
    ing.value.id ? await api.put(`/inventory/ingredients/${ing.value.id}`, body) : await api.post('/inventory/ingredients', body)
    ingDrawer.value = false; await load(); toast('Saqlandi')
  } catch (e: any) { toast(e.detail ?? 'Xato', 'danger') }
}
async function removeIng(i: any) {
  if (!confirm(`«${t(i.name, ui.lang)}» o'chirilsinmi?`)) return
  try { await api.del(`/inventory/ingredients/${i.id}`); await load() } catch (e: any) { toast(e.detail ?? 'Xato', 'danger') }
}
const adj = ref<any>(null)
async function saveAdjust() {
  try { await api.post(`/inventory/ingredients/${adj.value.id}/adjust`, { qty: Number(adj.value.qty), kind: adj.value.kind, note: adj.value.note }); adj.value = null; await load(); toast('Qoldiq yangilandi') }
  catch (e: any) { toast(e.detail ?? 'Xato', 'danger') }
}

// ---- kirim
const pur = ref<{ supplier_id: string; note: string; lines: { ingredient_id: string; qty: number; unit_price: number }[] }>({ supplier_id: '', note: '', lines: [{ ingredient_id: '', qty: 0, unit_price: 0 }] })
const purTotal = computed(() => pur.value.lines.reduce((s, l) => s + Number(l.qty) * Number(l.unit_price), 0))
function onLineIng(l: any) { const i = ingredients.value.find(x => String(x.id) === String(l.ingredient_id)); if (i && !l.unit_price) l.unit_price = i.price }
async function savePurchase() {
  const lines = pur.value.lines.filter(l => l.ingredient_id && Number(l.qty) > 0).map(l => ({ ingredient_id: Number(l.ingredient_id), qty: Number(l.qty), unit_price: Number(l.unit_price) }))
  if (!lines.length) { toast('Kamida bitta qator kiriting', 'danger'); return }
  try {
    await api.post('/inventory/purchases', { lines, supplier_id: pur.value.supplier_id ? Number(pur.value.supplier_id) : null, note: pur.value.note })
    pur.value = { supplier_id: '', note: '', lines: [{ ingredient_id: '', qty: 0, unit_price: 0 }] }
    await load(); toast('Kirim o\'tkazildi — tannarxlar yangilandi')
  } catch (e: any) { toast(e.detail ?? 'Xato', 'danger') }
}

// ---- tex-karta
const recipe = ref<any>(null)
const recipeSaving = ref(false)
async function openRecipe(productId: number) { recipe.value = await api.get(`/inventory/recipes/${productId}`) }
const liveCost = computed(() => {
  if (!recipe.value) return 0
  const total = recipe.value.lines.reduce((s: number, l: any) => {
    const i = ingredients.value.find(x => x.id === Number(l.ingredient_id)); if (!i) return s
    const base = i.unit === 'dona' ? Number(l.qty) : Number(l.qty) / 1000
    return s + base * Number(i.price) * (1 + Number(l.waste_percent || 0) / 100)
  }, 0)
  return Math.round(total / (Number(recipe.value.yield_qty) || 1))
})
const liveFc = computed(() => recipe.value?.price ? Math.round(1000 * liveCost.value / recipe.value.price) / 10 : null)
function addLine() { recipe.value.lines.push({ ingredient_id: ingredients.value[0]?.id ?? '', qty: 0, waste_percent: 0 }) }
async function saveRecipe() {
  recipeSaving.value = true
  try {
    const lines = recipe.value.lines.filter((l: any) => l.ingredient_id && Number(l.qty) > 0).map((l: any) => ({ ingredient_id: Number(l.ingredient_id), qty: Number(l.qty), waste_percent: Number(l.waste_percent || 0) }))
    recipe.value = await api.put(`/inventory/recipes/${recipe.value.product_id}`, { yield_qty: Number(recipe.value.yield_qty) || 1, note: recipe.value.note, lines })
    recipes.value = await api.get('/inventory/recipes'); toast(`Tannarx: ${money(recipe.value.cost)}`)
  } catch (e: any) { toast(e.detail ?? 'Xato', 'danger') } finally { recipeSaving.value = false }
}
const fcTone = (v: number | null) => v == null ? 'neutral' : v <= 32 ? 'ok' : v <= 40 ? 'warn' : 'danger'
const fmtDT = (s: string) => new Date(s).toLocaleString('uz-UZ', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' })
</script>

<template>
  <div class="inv">
    <div v-if="summary" class="kpis">
      <div class="kpi"><b>{{ summary.ingredients }}</b><span>Xomashyo turi</span></div>
      <div class="kpi" :class="{ warn: summary.low }"><b>{{ summary.low }}</b><span>Tugayapti</span></div>
      <div class="kpi"><b>{{ money(summary.stock_value) }}</b><span>Ombor qiymati</span></div>
      <div class="kpi"><b>{{ summary.recipes }}</b><span>Tex-karta</span></div>
      <div class="kpi" :class="{ warn: summary.products_without_recipe }"><b>{{ summary.products_without_recipe }}</b><span>Tex-kartasiz taom</span></div>
    </div>

    <HolidayAlert v-for="al in (fc?.alerts ?? [])" :key="al.id" :a="al" @plan="openPlan" />

    <nav class="tabs">
      <button v-if="hasFc" :class="{ on: tab === 'plan' }" @click="tab = 'plan'"><UiIcon name="calendar" :size="15" /> Xarid rejasi</button>
      <button :class="{ on: tab === 'recipes' }" @click="tab = 'recipes'"><UiIcon name="book" :size="15" /> Tex-karta va tannarx</button>
      <button :class="{ on: tab === 'ingredients' }" @click="tab = 'ingredients'"><UiIcon name="box" :size="15" /> Xomashyo va qoldiq</button>
      <button :class="{ on: tab === 'purchase' }" @click="tab = 'purchase'"><UiIcon name="truck" :size="15" /> Kirim (bozorlik)</button>
      <button :class="{ on: tab === 'movements' }" @click="tab = 'movements'"><UiIcon name="list" :size="15" /> Harakatlar</button>
    </nav>

    <!-- XARID REJASI -->
    <div v-if="tab === 'plan'" class="plan">
      <div class="p-top">
        <div class="seg-sel"><UiSelect v-model="planSel" :options="planOpts" /></div>
        <p class="p-how">Prognoz: oxirgi {{ plan?.history.days ?? '…' }} kunlik savdo × hafta kuni × bayram × ob-havo → tex-karta bo'yicha xomashyo.</p>
      </div>
      <UiEmpty v-if="plan && !plan.history.enough" title="Savdo tarixi yetarli emas" text="Prognoz uchun kamida 7 kunlik savdo va tex-kartalar kerak. Hozircha faqat minimal qoldiqdan kam xomashyolar ko'rsatiladi." />
      <template v-if="plan">
        <div class="kpis p-k">
          <div class="kpi"><b>{{ fmtD(plan.start) }} – {{ fmtD(plan.end) }}</b><span>{{ plan.days }} kun{{ plan.holiday ? ' · ' + plan.holiday.name.uz : '' }}</span></div>
          <div class="kpi"><b>{{ money(plan.revenue_forecast) }}</b><span>Kutilayotgan savdo · odatdagidan {{ plan.revenue_normal ? ((plan.revenue_forecast >= plan.revenue_normal ? '+' : '') + Math.round(100 * (plan.revenue_forecast - plan.revenue_normal) / plan.revenue_normal)) : 0 }}%</span></div>
          <div class="kpi" :class="{ warn: plan.short_count }"><b>{{ plan.short_count }}</b><span>Xomashyo xarid qilinadi</span></div>
          <div class="kpi"><b>{{ money(plan.total_cost) }}</b><span>Taxminiy xarid summasi</span></div>
          <div class="kpi"><b>{{ fmtD(plan.buy_by) }}</b><span>Qachongacha xarid qilish</span></div>
        </div>
        <div class="days">
          <div v-for="d in plan.daily" :key="d.date" class="day" :class="{ hol: d.holiday }" :title="d.holiday ?? ''">
            <small>{{ wd(d.date) }} {{ d.date.slice(8) }}</small>
            <span class="e">{{ d.holiday ? '🎉' : (d.weather ?? '·') }}</span>
            <b :class="d.factor > 1.05 ? 'up' : d.factor < 0.95 ? 'dn' : ''">{{ d.factor > 1 ? '+' : '' }}{{ Math.round((d.factor - 1) * 100) }}%</b>
          </div>
        </div>
        <div class="split">
          <UiCard title="Nima xarid qilish kerak" :subtitle="`Kerak = prognoz sarfi + minimal qoldiq − hozirgi qoldiq`" :padded="false">
            <template #actions>
              <button class="chip-btn" :class="{ on: onlyBuy }" @click="onlyBuy = !onlyBuy">Faqat xarid kerak</button>
            </template>
            <div class="lst">
              <div class="l-h pl"><span>Xomashyo</span><span>Qoldiq</span><span>Kerak bo'ladi</span><span>Yetadi</span><span>Xarid</span><span>Summa</span></div>
              <div v-for="l in planLines" :key="l.ingredient_id" class="l-r pl" :class="{ buy: l.buy > 0 }">
                <span class="nm"><b>{{ t(l.name, ui.lang) }}</b><small>{{ l.supplier ?? 'bozor' }}{{ l.category ? ' · ' + l.category : '' }}</small></span>
                <span>{{ num(l.stock) }} {{ UNIT[l.unit] }}</span>
                <span class="mut">{{ num(l.need) }} {{ UNIT[l.unit] }}</span>
                <span :class="{ danger: l.days_left != null && l.days_left < plan.days }">{{ l.days_left != null ? `${num(l.days_left)} kun` : '—' }}</span>
                <span><b v-if="l.buy > 0" class="acc">{{ num(l.buy) }} {{ UNIT[l.unit] }}</b><span v-else class="ok">✓ yetarli</span></span>
                <span>{{ l.cost ? money(l.cost) : '' }}</span>
              </div>
              <UiEmpty v-if="!planLines.length" title="Hammasi yetarli" text="Bu davr uchun ombordagi qoldiq yetadi." />
            </div>
          </UiCard>
          <div class="side">
            <UiCard title="Ta'minotchilar bo'yicha" subtitle="Har biriga alohida kirim ochish mumkin">
              <ul class="sup">
                <li v-for="sp in plan.suppliers" :key="sp.name">
                  <span class="nm"><b>{{ sp.name }}</b><small>{{ sp.count }} ta xomashyo</small></span>
                  <b>{{ money(sp.total) }}</b>
                  <UiButton v-if="a.can('inventory.purchase')" size="s" variant="ghost" @click="toPurchase(sp.supplier_id, false)">Kirim</UiButton>
                </li>
              </ul>
              <p v-if="!plan.suppliers.length" class="mut">Xarid kerak emas.</p>
              <div v-if="plan.short_count" class="r-foot">
                <UiButton variant="ghost" size="s" @click="copyList()">📋 Ro'yxatni nusxalash</UiButton>
                <div class="sp"></div>
                <UiButton v-if="a.can('inventory.purchase')" variant="brand" @click="toPurchase(null, true)">Hammasini kirimga</UiButton>
              </div>
            </UiCard>
            <UiCard v-if="plan.products.length" :title="plan.holiday ? 'Bayram kunlari ko\'p ketadi' : 'Ko\'p ketadigan taomlar'" subtitle="Prognoz, porsiya">
              <ul class="sup">
                <li v-for="p in plan.products" :key="p.product_id"><span class="nm"><b>{{ t(p.name, ui.lang) }}</b></span><b>{{ p.qty }}</b><span class="mut">porsiya</span></li>
              </ul>
            </UiCard>
          </div>
        </div>
      </template>
      <p v-else-if="planLoading" class="mut">Hisoblanmoqda…</p>
    </div>

    <!-- TEX-KARTA -->
    <div v-else-if="tab === 'recipes'" class="split">
      <UiCard title="Taomlar" subtitle="Bosing — tex-kartani oching. Food cost: ≤32% yaxshi · 33–40% e'tibor · >40% narx yoki retseptni ko'ring" :padded="false">
        <div class="lst">
          <div class="l-h"><span>Taom</span><span>Narx</span><span>Tannarx</span><span>Food cost</span><span>Marja</span></div>
          <button v-for="r in recipes" :key="r.product_id" class="l-r" :class="{ sel: recipe?.product_id === r.product_id }" @click="openRecipe(r.product_id)">
            <span class="nm"><b>{{ t(r.name, ui.lang) }}</b><small>{{ t(r.category, ui.lang) }}{{ r.has_recipe ? ` · ${r.lines} xomashyo` : ' · tex-karta yo\'q' }}</small></span>
            <span>{{ money(r.price) }}</span>
            <span>{{ money(r.cost) }}</span>
            <span><UiChip :tone="fcTone(r.food_cost_percent)">{{ r.food_cost_percent ?? '—' }}%</UiChip></span>
            <span>{{ r.margin_percent ?? '—' }}%</span>
          </button>
        </div>
      </UiCard>

      <UiCard v-if="recipe" :title="t(recipe.product_name, ui.lang)" subtitle="Bir porsiyaga ketadigan xomashyo — g / ml / dona">
        <template #actions><UiChip :tone="fcTone(liveFc)">Food cost {{ liveFc ?? '—' }}%</UiChip></template>
        <div class="cost-row">
          <div><span>Sotuv narxi</span><b>{{ money(recipe.price) }}</b></div>
          <div><span>Tannarx (jonli)</span><b class="acc">{{ money(liveCost) }}</b></div>
          <div><span>Marja</span><b>{{ money(recipe.price - liveCost) }}</b></div>
          <div><span>Tavsiya narx (FC 32%)</span><b>{{ money(Math.ceil(liveCost / 0.32 / 500) * 500) }}</b></div>
        </div>
        <table class="rl">
          <thead><tr><th>Xomashyo</th><th>Miqdor</th><th>Chiqindi %</th><th>Narx</th><th>Summa</th><th></th></tr></thead>
          <tbody>
            <tr v-for="(l, i) in recipe.lines" :key="i">
              <td><select v-model="l.ingredient_id"><option v-for="ig in ingredients" :key="ig.id" :value="ig.id">{{ t(ig.name, ui.lang) }} ({{ SUB[ig.unit] }})</option></select></td>
              <td><input v-model="l.qty" type="number" min="0" step="1" /> <small>{{ SUB[ingredients.find(x => x.id === Number(l.ingredient_id))?.unit ?? 'kg'] }}</small></td>
              <td><input v-model="l.waste_percent" type="number" min="0" max="90" /></td>
              <td class="mut">{{ money(ingredients.find(x => x.id === Number(l.ingredient_id))?.price ?? 0) }}/{{ UNIT[ingredients.find(x => x.id === Number(l.ingredient_id))?.unit ?? 'kg'] }}</td>
              <td><b>{{ money(Math.round(((ingredients.find(x => x.id === Number(l.ingredient_id))?.unit === 'dona' ? Number(l.qty) : Number(l.qty) / 1000) * (ingredients.find(x => x.id === Number(l.ingredient_id))?.price ?? 0)) * (1 + Number(l.waste_percent || 0) / 100))) }}</b></td>
              <td><button class="x" @click="recipe.lines.splice(i, 1)"><UiIcon name="x" :size="13" /></button></td>
            </tr>
          </tbody>
        </table>
        <div class="r-foot">
          <UiButton variant="ghost" size="s" @click="addLine()"><UiIcon name="plus" :size="14" /> Xomashyo qo'shish</UiButton>
          <label class="yld">Chiqadi: <input v-model="recipe.yield_qty" type="number" min="0.5" step="0.5" /> porsiya</label>
          <div class="sp"></div>
          <UiButton v-if="a.can('inventory.recipe')" variant="brand" :loading="recipeSaving" @click="saveRecipe()">Saqlash va tannarxni yozish</UiButton>
        </div>
        <label class="fl"><span>Tayyorlash tartibi (oshpaz uchun)</span><textarea v-model="recipe.note" rows="3" placeholder="1. Go'shtni 180° da 4 daqiqa… 2. Nonni qizdiring…"></textarea></label>
      </UiCard>
      <UiEmpty v-else title="Taomni tanlang" text="Chapdagi ro'yxatdan taomni bosing — tex-kartani kiriting, tannarx o'zi hisoblanadi." />
    </div>

    <!-- XOMASHYO -->
    <UiCard v-else-if="tab === 'ingredients'" :padded="false">
      <template #actions>
        <UiInput v-model="q" placeholder="Qidirish" @keydown.enter="load()" />
        <button class="chip-btn" :class="{ on: onlyLow }" @click="onlyLow = !onlyLow"><UiIcon name="alert" :size="14" /> Tugayotganlar</button>
        <UiButton v-if="canEdit" variant="brand" size="s" @click="openIng()"><UiIcon name="plus" :size="14" /> Xomashyo</UiButton>
      </template>
      <div class="lst">
        <div class="l-h ing"><span>Nomi</span><span>Narx</span><span>Qoldiq</span><span>Min</span><span>Qiymat</span><span>Tex-karta</span><span></span></div>
        <div v-for="i in ingredients" :key="i.id" class="l-r ing" :class="{ low: i.is_low }">
          <span class="nm"><b>{{ t(i.name, ui.lang) }}</b><small>{{ i.category }}</small></span>
          <span>{{ money(i.price) }}<small>/{{ UNIT[i.unit] }}</small></span>
          <span :class="{ danger: i.is_low }"><b>{{ i.stock }}</b> {{ UNIT[i.unit] }}</span>
          <span class="mut">{{ i.min_stock }} {{ UNIT[i.unit] }}</span>
          <span>{{ money(i.stock_value) }}</span>
          <span class="mut">{{ i.used_in }} taomda</span>
          <span class="acts">
            <UiButton size="s" variant="ghost" @click="adj = { id: i.id, name: t(i.name, ui.lang), qty: i.stock, unit: UNIT[i.unit], kind: 'adjust', note: '' }" title="Inventarizatsiya"><UiIcon name="edit" :size="14" /></UiButton>
            <UiButton v-if="canEdit" size="s" variant="ghost" @click="openIng(i)"><UiIcon name="sliders" :size="14" /></UiButton>
            <UiButton v-if="canEdit" size="s" variant="ghost" @click="removeIng(i)"><UiIcon name="trash" :size="14" /></UiButton>
          </span>
        </div>
        <UiEmpty v-if="!ingredients.length" title="Xomashyo yo'q" text="«Xomashyo» tugmasi bilan qo'shing yoki kirim kiriting." />
      </div>
    </UiCard>

    <!-- KIRIM -->
    <div v-else-if="tab === 'purchase'" class="split">
      <UiCard title="Yangi kirim (bozorlik)" subtitle="Narx bazaviy birlik uchun: so'm/kg, so'm/l, so'm/dona. Saqlangach — qoldiq oshadi, tannarxlar yangilanadi">
        <div class="grid2">
          <UiSelect v-model="pur.supplier_id" label="Yetkazib beruvchi" :options="[{ value: '', label: '— bozor / boshqa —' }, ...suppliers.map(s => ({ value: String(s.id), label: s.name }))]" />
          <UiInput v-model="pur.note" label="Izoh" placeholder="Chorsu, ertalab" />
        </div>
        <table class="rl">
          <thead><tr><th>Xomashyo</th><th>Miqdor</th><th>Narx / birlik</th><th>Summa</th><th></th></tr></thead>
          <tbody>
            <tr v-for="(l, i) in pur.lines" :key="i">
              <td><select v-model="l.ingredient_id" @change="onLineIng(l)"><option value="">— tanlang —</option><option v-for="ig in ingredients" :key="ig.id" :value="String(ig.id)">{{ t(ig.name, ui.lang) }} ({{ UNIT[ig.unit] }})</option></select></td>
              <td><input v-model="l.qty" type="number" min="0" step="0.1" /></td>
              <td><input v-model="l.unit_price" type="number" min="0" step="100" /></td>
              <td><b>{{ money(Number(l.qty) * Number(l.unit_price)) }}</b></td>
              <td><button class="x" @click="pur.lines.splice(i, 1)"><UiIcon name="x" :size="13" /></button></td>
            </tr>
          </tbody>
        </table>
        <div class="r-foot">
          <UiButton variant="ghost" size="s" @click="pur.lines.push({ ingredient_id: '', qty: 0, unit_price: 0 })"><UiIcon name="plus" :size="14" /> Qator</UiButton>
          <div class="sp"></div>
          <b class="tot">Jami: {{ money(purTotal) }}</b>
          <UiButton v-if="a.can('inventory.purchase')" variant="brand" @click="savePurchase()">Kirimni o'tkazish</UiButton>
        </div>
      </UiCard>
      <UiCard title="So'nggi kirimlar" :padded="false">
        <div class="lst">
          <div v-for="p in purchases" :key="p.id" class="l-r pur">
            <span class="nm"><b>Kirim #{{ p.number }}</b><small>{{ p.date }} · {{ p.supplier ?? 'bozor' }} · {{ p.lines.length }} qator</small></span>
            <span><b>{{ money(p.total) }}</b></span>
          </div>
          <UiEmpty v-if="!purchases.length" title="Hali kirim yo'q" />
        </div>
      </UiCard>
    </div>

    <!-- HARAKATLAR -->
    <UiCard v-else :padded="false" title="Ombor harakatlari" subtitle="Kirim +, savdo −, chiqindi, inventarizatsiya — kim, qachon">
      <div class="lst">
        <div v-for="m in movements" :key="m.id" class="l-r mv">
          <span class="mut">{{ fmtDT(m.at) }}</span>
          <span><b>{{ t(m.ingredient.name, ui.lang) }}</b></span>
          <span><UiChip :tone="m.kind === 'purchase' ? 'ok' : m.kind === 'sale' ? 'info' : m.kind === 'waste' ? 'danger' : 'neutral'">{{ ({ purchase: 'Kirim', sale: 'Savdo', waste: 'Chiqindi', adjust: 'Inventarizatsiya', transfer: 'O\'tkazish' } as Record<string, string>)[m.kind] ?? m.kind }}</UiChip></span>
          <span :class="m.qty >= 0 ? 'ok' : 'danger'"><b>{{ m.qty > 0 ? '+' : '' }}{{ m.qty }}</b> {{ UNIT[m.ingredient.unit] }}</span>
          <span class="mut">{{ m.ref || m.note }}</span>
          <span class="mut">{{ m.actor ?? '' }}</span>
        </div>
        <UiEmpty v-if="!movements.length" title="Harakat yo'q" />
      </div>
    </UiCard>

    <!-- xomashyo formasi -->
    <UiDrawer :open="ingDrawer" :title="ing?.id ? 'Xomashyo' : 'Yangi xomashyo'" @close="ingDrawer = false">
      <template v-if="ing">
        <UiInput v-model="ing.name.uz" label="Nomi (uz)" />
        <div class="grid2">
          <UiInput v-model="ing.name.ru" label="Nomi (ru)" /><UiInput v-model="ing.name.en" label="Nomi (en)" />
          <UiInput v-model="ing.category" label="Kategoriya" placeholder="Go'sht, Sabzavot…" />
          <UiSelect v-model="ing.unit" label="Birlik" :options="[{ value: 'kg', label: 'kg (retseptda gramm)' }, { value: 'l', label: 'litr (retseptda ml)' }, { value: 'dona', label: 'dona' }]" />
          <UiInput v-model="ing.price" type="number" label="Narx (so'm / birlik)" suffix="so'm" />
          <UiInput v-model="ing.min_stock" type="number" label="Minimal qoldiq (ogohlantirish)" />
        </div>
        <p class="tip"><UiIcon name="alert" :size="14" /> Narxni bu yerda o'zgartirsangiz — shu xomashyo bor barcha taomlar tannarxi darhol qayta hisoblanadi.</p>
      </template>
      <template #footer><UiButton variant="ghost" @click="ingDrawer = false">Bekor</UiButton><UiButton variant="brand" @click="saveIng()">Saqlash</UiButton></template>
    </UiDrawer>

    <UiDrawer :open="!!adj" title="Qoldiqni yangilash" width="420px" @close="adj = null">
      <template v-if="adj">
        <p><b>{{ adj.name }}</b></p>
        <UiInput v-model="adj.qty" type="number" :label="`Haqiqiy qoldiq (${adj.unit})`" />
        <UiSelect v-model="adj.kind" label="Sabab" :options="[{ value: 'adjust', label: 'Inventarizatsiya' }, { value: 'waste', label: 'Chiqindi / yaroqsiz' }, { value: 'transfer', label: 'Boshqa filialga' }]" />
        <UiInput v-model="adj.note" label="Izoh" />
      </template>
      <template #footer><UiButton variant="ghost" @click="adj = null">Bekor</UiButton><UiButton variant="brand" @click="saveAdjust()">Saqlash</UiButton></template>
    </UiDrawer>
  </div>
</template>

<style scoped>
.inv { display: flex; flex-direction: column; gap: 14px; }
.kpis { display: grid; grid-template-columns: repeat(5, 1fr); gap: 10px; }
.kpi { background: var(--surface); border: 1px solid var(--line); border-radius: var(--radius-l); padding: 12px 14px; display: flex; flex-direction: column; }
.kpi b { font-family: var(--font-display); font-size: var(--fs-xl); font-weight: 800; } .kpi span { font-size: var(--fs-xs); color: var(--muted); }
.kpi.warn { border-color: color-mix(in srgb, var(--danger) 45%, var(--line)); }
.tabs { display: flex; gap: 4px; border-bottom: 1px solid var(--line); overflow-x: auto; }
.tabs button { display: inline-flex; align-items: center; gap: 6px; border: 0; background: transparent; padding: 9px 12px; font-weight: 700; font-size: var(--fs-s); color: var(--muted); cursor: pointer; border-bottom: 2px solid transparent; white-space: nowrap; }
.tabs button.on { color: var(--accent); border-bottom-color: var(--accent); }
.split { display: grid; grid-template-columns: 1fr 1.2fr; gap: 14px; align-items: start; }
.lst { display: flex; flex-direction: column; }
.l-h, .l-r { display: grid; grid-template-columns: 2fr 1fr 1fr 1fr 1fr; gap: 10px; align-items: center; padding: 9px 14px; text-align: left; font-size: var(--fs-s); }
.l-h { font-size: var(--fs-xs); font-weight: 700; color: var(--muted); background: var(--surface-2); }
.l-r { border: 0; border-top: 1px solid var(--line-2); background: transparent; font: inherit; }
button.l-r { cursor: pointer; } button.l-r:hover, .l-r.sel { background: var(--accent-tint); }
.l-r.ing, .l-h.ing { grid-template-columns: 2fr 1fr 1fr .8fr 1fr 1fr 130px; }
.l-r.low { background: var(--danger-tint); }
.l-r.pur { grid-template-columns: 1fr auto; } .l-r.mv { grid-template-columns: 110px 1.5fr 1fr 1fr 1fr 1fr; }
.nm { display: flex; flex-direction: column; min-width: 0; } .nm b { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; } .nm small { color: var(--muted); font-size: var(--fs-xs); }
.mut { color: var(--muted); } .danger { color: var(--danger); } .ok { color: var(--ok); }
.acts { display: flex; gap: 2px; justify-content: flex-end; }
.cost-row { display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; margin-bottom: 12px; }
.cost-row div { background: var(--surface-2); border-radius: var(--radius); padding: 10px 12px; display: flex; flex-direction: column; }
.cost-row span { font-size: var(--fs-xs); color: var(--muted); } .cost-row b { font-family: var(--font-display); font-size: var(--fs-l); } .cost-row .acc { color: var(--accent); }
.rl { width: 100%; border-collapse: collapse; font-size: var(--fs-s); }
.rl th { text-align: left; font-size: var(--fs-xs); color: var(--muted); padding: 6px 4px; border-bottom: 1px solid var(--line); }
.rl td { padding: 5px 4px; border-bottom: 1px solid var(--line-2); }
.rl select, .rl input { width: 100%; min-width: 60px; border: 1px solid var(--line); border-radius: var(--radius-s); padding: 6px 8px; background: var(--surface); font-size: var(--fs-s); }
.rl input[type=number] { max-width: 90px; }
.x { border: 0; background: transparent; cursor: pointer; color: var(--muted); }
.r-foot { display: flex; align-items: center; gap: 10px; margin-top: 10px; flex-wrap: wrap; } .sp { flex: 1; }
.yld { font-size: var(--fs-s); color: var(--muted); } .yld input { width: 60px; border: 1px solid var(--line); border-radius: var(--radius-s); padding: 4px 6px; }
.tot { font-family: var(--font-display); font-size: var(--fs-l); }
.fl { display: flex; flex-direction: column; gap: 4px; margin-top: 12px; } .fl span { font-size: var(--fs-xs); color: var(--muted); font-weight: 700; }
.fl textarea { border: 1px solid var(--line); border-radius: var(--radius); padding: 8px 10px; background: var(--surface); font: inherit; }
.grid2 { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
.chip-btn { display: inline-flex; align-items: center; gap: 6px; min-height: var(--touch); padding: 0 12px; border-radius: var(--radius); border: 1px solid var(--line); background: var(--surface); font-weight: 700; font-size: var(--fs-s); cursor: pointer; }
.chip-btn.on { background: var(--danger-tint); color: var(--danger); border-color: var(--danger); }
.tip { display: flex; gap: 6px; font-size: var(--fs-xs); color: var(--muted); background: var(--surface-2); border-radius: var(--radius); padding: 8px 10px; margin: 0; }
.plan { display: flex; flex-direction: column; gap: 14px; }
.p-top { display: flex; align-items: center; gap: 14px; flex-wrap: wrap; } .seg-sel { min-width: 260px; } .p-how { margin: 0; font-size: var(--fs-xs); color: var(--muted); flex: 1; min-width: 200px; }
.p-k .kpi b { font-size: var(--fs-l); }
.days { display: grid; grid-template-columns: repeat(auto-fit, minmax(62px, 1fr)); gap: 6px; }
.day { display: flex; flex-direction: column; align-items: center; gap: 2px; padding: 8px 4px; border-radius: 12px; background: var(--surface); border: 1px solid var(--line); }
.day.hol { background: var(--warn-tint); border-color: color-mix(in srgb, var(--warn) 45%, var(--line)); }
.day small { font-size: 11px; color: var(--muted); font-weight: 700; } .day .e { font-size: 20px; } .day b { font-size: var(--fs-xs); }
.day b.up { color: var(--ok); } .day b.dn { color: var(--danger); }
.plan .split { grid-template-columns: minmax(0, 1.7fr) minmax(0, 1fr); }
.l-r.pl, .l-h.pl { grid-template-columns: minmax(0, 2fr) 1fr 1fr .8fr 1fr 1fr; } .l-r.pl > span:not(.nm) { white-space: nowrap; }
.chip-btn { white-space: nowrap; } .l-r.buy { background: color-mix(in srgb, var(--warn-tint) 60%, transparent); }
.acc { color: var(--accent); }
.side { display: flex; flex-direction: column; gap: 14px; min-width: 0; }
.sup { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; }
.sup li { display: grid; grid-template-columns: minmax(0, 1fr) auto auto; gap: 10px; align-items: center; padding: 8px 0; border-bottom: 1px solid var(--line-2); font-size: var(--fs-s); } .sup li:last-child { border-bottom: 0; }
@media (max-width: 1100px) { .plan .split { grid-template-columns: minmax(0, 1fr); } .split { grid-template-columns: 1fr; } .kpis { grid-template-columns: repeat(3, 1fr); } .cost-row { grid-template-columns: 1fr 1fr; } }
@media (max-width: 600px) {
  .kpis { grid-template-columns: 1fr 1fr; } .grid2 { grid-template-columns: 1fr; }
  /* telefon: har qator — nomi (to'liq kenglik) + qolgan qiymatlar ixcham qatorda, sarlavha yashirin */
  .l-h { display: none; }
  .l-r { grid-template-columns: repeat(4, minmax(0, 1fr)) !important; gap: 4px 8px; padding: 10px 14px; }
  .l-r > .nm { grid-column: 1 / -1; }
  .l-r > span:not(.nm):not(.acts) { font-size: var(--fs-xs); color: var(--ink-2); }
  .l-r > .acts { grid-column: 1 / -1; justify-content: flex-start; }
  .l-r.pur { grid-template-columns: 1fr auto !important; }
  .l-r.pl { grid-template-columns: repeat(3, minmax(0, 1fr)) !important; }
  .seg-sel { min-width: 0; width: 100%; } .days { grid-template-columns: repeat(auto-fit, minmax(44px, 1fr)); gap: 4px; }
  .cost-row { grid-template-columns: 1fr 1fr; }
}
</style>
'@

Write-Host ""
Write-Host "Tayyor: 28 ta fayl yangilandi." -ForegroundColor Green
Write-Host "Endi:" -ForegroundColor Yellow
Write-Host "  cd backend" -ForegroundColor Yellow
Write-Host "  ..\.venv\Scripts\python.exe manage.py migrate_schemas" -ForegroundColor Yellow
Write-Host "  ..\.venv\Scripts\python.exe manage.py seed_forecast" -ForegroundColor Yellow
Write-Host "  cd ..\frontend; pnpm build   (keyin brauzerda Ctrl+Shift+R)" -ForegroundColor Yellow
