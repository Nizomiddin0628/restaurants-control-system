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
        "branches": _my_branches(user),
    }


def _my_branches(user: User) -> list[dict]:
    """Foydalanuvchi ko'ra oladigan filiallar: egasi / filial boshqaruvchisi yoki cheklanmagan a'zolik — hammasi."""
    qs = Branch.objects.filter(deleted_at__isnull=True, is_active=True).order_by("id")
    ms = list(user.memberships.filter(is_active=True).prefetch_related("branches"))
    if not user.is_superuser and not user.has_perm_code("core.branches.manage") and ms and all(m.branches.exists() for m in ms):
        ids = {b.pk for m in ms for b in m.branches.all()}
        qs = qs.filter(pk__in=ids)
    return [{"id": b.pk, "name": b.name, "address": b.address} for b in qs]


# ------------------------------------------------------------------ restoranlar orasida o'tish (Telegram akkauntlari kabi)
SWITCH_SALT = "restopos.switch"


def _admin_url(request, tenant) -> str | None:
    from public.models import Domain
    d = Domain.objects.filter(tenant=tenant).order_by("-is_primary", "id").first()
    if d is None:
        return None
    port = request.get_port()
    host = d.domain + (f":{port}" if port and str(port) not in ("80", "443") else "")
    return f"{request.scheme}://{host}/admin/"


def _my_restaurants(phone: str) -> list:
    """Shu telefon raqami a'zo bo'lgan barcha faol restoranlar (5 daqiqa keshlanadi)."""
    from django.core.cache import cache
    from django_tenants.utils import schema_context

    from public.models import Tenant
    key = f"myrest:{phone}"
    hit = cache.get(key)
    if hit is not None:
        return hit
    out = []
    for t in Tenant.objects.filter(is_active=True).exclude(schema_name="public").order_by("name"):
        with schema_context(t.schema_name):
            ok = User.objects.filter(phone=phone, is_active=True, memberships__is_active=True).exists()
        if ok:
            out.append(t.pk)
    cache.set(key, out, 300)
    return out


@api.get("/me/restaurants", auth=auth, tags=["auth"])
def my_restaurants(request):
    from public.models import Tenant
    ids = _my_restaurants(request.auth.phone)
    cur = request.tenant
    rows = []
    for t in Tenant.objects.filter(pk__in=ids).order_by("name"):
        rows.append({"slug": t.slug, "name": t.name, "current": t.pk == cur.pk, "url": _admin_url(request, t)})
    if not any(r["current"] for r in rows):
        rows.append({"slug": cur.slug, "name": cur.name, "current": True, "url": _admin_url(request, cur)})
    return sorted(rows, key=lambda r: not r["current"])     # joriy restoran — birinchi


class SwitchIn(Schema):
    slug: str


@api.post("/me/switch", auth=auth, tags=["auth"])
def switch_restaurant(request, data: SwitchIn):
    """Boshqa restoranga qayta kod so'ramasdan o'tish: 2 daqiqalik bir martalik imzolangan havola."""
    import secrets

    from django.core import signing

    from public.models import Tenant
    t = Tenant.objects.filter(slug=data.slug, is_active=True).first()
    if t is None or t.pk not in _my_restaurants(request.auth.phone):
        raise HttpError(404, "Bu restoranda sizning hisobingiz yo'q")
    url = _admin_url(request, t)
    if not url:
        raise HttpError(400, "Restoran domeni sozlanmagan")
    code = signing.dumps({"s": t.slug, "p": request.auth.phone, "n": secrets.token_hex(6)}, salt=SWITCH_SALT, compress=True)
    return {"url": f"{url}login?switch={code}", "name": t.name}


class SwitchCode(Schema):
    code: str


@api.post("/auth/switch", response=TokenOut, tags=["auth"])
def auth_switch(request, data: SwitchCode):
    from django.core import signing
    from django.core.cache import cache
    try:
        p = signing.loads(data.code, salt=SWITCH_SALT, max_age=120)
    except signing.BadSignature:
        raise HttpError(400, "Havola eskirgan — qaytadan urinib ko'ring") from None
    if p.get("s") != request.tenant.slug or not cache.add(f"switch:{p.get('n')}", 1, 300):
        raise HttpError(400, "Havola yaroqsiz")
    user = User.objects.filter(phone=p.get("p"), is_active=True, memberships__is_active=True).distinct().first()
    if user is None:
        raise HttpError(404, "Bu restoranda sizning hisobingiz yo'q")
    user.last_seen_at = timezone.now()
    user.save(update_fields=["last_seen_at"])
    return {"token": issue_token(user, request.tenant.schema_name), "user": _me(request, user)}


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


@api.get("/dashboard/sections", auth=auth, tags=["dashboard"])
def dashboard_sections(request, branch_id: Optional[int] = None):
    """Har bo'lim uchun 3–5 ta asosiy ko'rsatkich (bo'lim sahifasi va asosiy sahifa plitkalari uchun)."""
    from .sections import sections
    return sections(request, branch_id)


@api.get("/dashboard/section/{code}", auth=auth, tags=["dashboard"])
def dashboard_section(request, code: str, days: int = 7, branch_id: Optional[int] = None):
    """Bo'lim dashboardi: shu bo'limning grafiklari va ro'yxatlari (vidjetlar)."""
    from .section_dash import section_dashboard
    return section_dashboard(request, code, days, branch_id)


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
