"""
Kirish va rollar — /api/v1/access/...  (oddiy «Xodimlar kirishi» sahifasi uchun)

GET  /access/meta              — bo'limlar matritsasi, rollar, filiallar, AI Kotib o'rinlari
GET  /access/users             — men boshqara oladigan (va ko'radigan) xodimlar
POST /access/users             — yangi xodim: telefon, ism, bir nechta rol, filiallar, shaxsiy ruxsatlar
PUT  /access/users/{uid}       — tahrirlash (rollar, filiallar, ruxsatlar, ism, telefon, faol/nofaol)
POST /access/roles, PUT/DELETE /access/roles/{id} — rol shablonlari (Bosh menejer va yuqori)
"""
from __future__ import annotations

import re
from datetime import timedelta
from typing import Optional

from django.db import transaction
from django.shortcuts import get_object_or_404
from ninja import Router, Schema
from ninja.errors import HttpError

from core import access as acc
from core.audit import record
from core.auth import auth, require_perm
from core.models import Branch, Membership, Role, User

router = Router(tags=["access"])


def _levels(a: dict) -> list[dict]:
    out = [{"key": "none", "label": acc.LEVEL_LABELS["none"]}]
    seen: list[set] = []
    for k in ("view", "edit", "full"):
        if a[k] and set(a[k]) not in seen:
            seen.append(set(a[k]))
            out.append({"key": k, "label": acc.LEVEL_LABELS[k]})
    if len(out) == 2 and out[1]["key"] == "full":
        out[1]["label"] = "Ha"
    return out


def _areas(tenant) -> list[dict]:
    on = set(tenant.enabled_modules or [])
    return [{**a, "levels": _levels(a), "perms": [{"code": p, "label": acc.PERM_LABELS.get(p, p)} for p in acc.area_perms(a)]}
            for a in acc.AREAS if not a["module"] or a["module"] in on]


def _role_out(r: Role, actor: User | None = None, counts: dict | None = None) -> dict:
    return {"id": r.pk, "code": r.code, "name": r.name, "description": r.description, "level": r.level, "is_system": r.is_system,
            "permissions": r.permissions, "members": (counts or {}).get(r.pk, 0),
            "grantable": acc.can_grant_role(actor, r) if actor else False,
            "editable": bool(actor) and actor.access_level() >= 80 and "*" not in (r.permissions or []) and r.level < actor.access_level()}


def _visible_roles():
    return Role.objects.exclude(code="platform_support").order_by("-level", "name")


def _user_out(u: User, actor: User, areas: list[dict]) -> dict:
    ms = [m for m in u.memberships.all() if m.is_active]
    roles = [m.role for m in ms]
    perms = set(u.extra_permissions or [])
    for r in roles:
        perms |= set(r.permissions or [])
    role_perms = set().union(*[set(r.permissions or []) for r in roles]) if roles else set()
    bids: set[int] = set()
    all_b = not ms
    for m in ms:
        b = {x.pk for x in m.branches.all()}
        if not b or m.role.level >= 80:
            all_b = True
        bids |= b
    level = max([r.level for r in roles] or [0])
    return {
        "id": str(u.pk), "phone": u.phone, "full_name": u.full_name, "avatar": u.avatar.url if u.avatar else None,
        "is_active": u.is_active, "roles": [{"code": r.code, "name": r.name, "level": r.level} for r in sorted(roles, key=lambda r: -r.level)],
        "branch_ids": [] if all_b else sorted(bids), "all_branches": all_b,
        "extra_permissions": list(u.extra_permissions or []), "level": level,
        "areas": {a["code"]: acc.area_level(perms, a) for a in areas},
        "role_areas": {a["code"]: acc.area_level(role_perms, a) for a in areas},
        "ai": acc.covers(perms, "ai.use"), "ai_by_role": acc.covers(role_perms, "ai.use"),
        "editable": acc.can_manage_user(actor, u),
        "is_me": u.pk == actor.pk,
        "has_password": bool(u.password) and u.has_usable_password(), "telegram_linked": bool(u.telegram_id),
        "last_seen_at": u.last_seen_at.isoformat() if u.last_seen_at else None,
    }


def _ai_seats(tenant) -> dict | None:
    if not tenant.module_enabled("ai"):
        return None
    from modules.ai import limits
    return limits.seats_info(tenant)


@router.get("/meta", auth=auth)
def meta(request):
    require_perm(request, "core.users.manage")
    me = request.auth
    scope = me.branch_scope()
    bqs = Branch.objects.filter(deleted_at__isnull=True, is_active=True).order_by("id")
    if scope is not None:
        bqs = bqs.filter(pk__in=scope)
    counts: dict[int, int] = {}
    for m in Membership.objects.filter(is_active=True, user__is_active=True).values("role_id"):
        counts[m["role_id"]] = counts.get(m["role_id"], 0) + 1
    return {
        "sections": [{"code": c, "title": t} for c, t in acc.SECTIONS],
        "areas": _areas(request.tenant),
        "roles": [_role_out(r, me, counts) for r in _visible_roles()],
        "branches": [{"id": b.pk, "name": b.name} for b in bqs],
        "me": {"level": me.access_level(), "all_branches": scope is None, "can_roles": me.access_level() >= 80},
        "ai": _ai_seats(request.tenant),
    }


def _visible_users(actor: User):
    qs = User.objects.prefetch_related("memberships__role", "memberships__branches").exclude(memberships__role__code="platform_support").order_by("-is_active", "full_name")
    scope = actor.branch_scope()
    if scope is not None:
        qs = qs.filter(memberships__branches__in=scope).distinct()
    return qs


@router.get("/users", auth=auth)
def users(request):
    require_perm(request, "core.users.manage")
    areas = _areas(request.tenant)
    return [_user_out(u, request.auth, areas) for u in _visible_users(request.auth)]


class AccessIn(Schema):
    phone: Optional[str] = None
    full_name: Optional[str] = None
    role_codes: list[str] = []
    branch_ids: list[int] = []
    extra_permissions: list[str] = []
    is_active: Optional[bool] = None


def _apply(request, u: User, data: AccessIn, *, new: bool) -> None:
    actor = request.auth
    t = request.tenant
    before_ai = u.has_perm_code("ai.use") if not new else False
    roles = list(Role.objects.filter(code__in=data.role_codes))
    if not roles:
        raise HttpError(400, "Kamida bitta rol tanlang (masalan: Kassir)")
    cur = {m.role.code: m for m in u.memberships.select_related("role")}
    for r in roles:
        if r.code not in cur and not acc.can_grant_role(actor, r):
            raise HttpError(403, f"«{r.name}» rolini bera olmaysiz — bu sizdan yuqori yoki teng daraja")
    # olib tashlanayotgan rollar
    keep = {r.code for r in roles}
    for code, m in cur.items():
        if code in keep:
            continue
        if not acc.can_grant_role(actor, m.role):
            raise HttpError(403, f"«{m.role.name}» rolini olib tashlay olmaysiz")
        if code == "owner" and Membership.objects.filter(role__code="owner", is_active=True, user__is_active=True).exclude(user=u).count() == 0:
            raise HttpError(400, "Restoranda kamida bitta Superadmin (egasi) qolishi kerak")
        m.delete()
    branch_ids = acc.check_branches(actor, data.branch_ids)
    valid_b = set(Branch.objects.filter(pk__in=branch_ids, deleted_at__isnull=True).values_list("pk", flat=True))
    for r in roles:
        m, _ = Membership.objects.get_or_create(user=u, role=r)
        if not m.is_active:
            m.is_active = True
            m.save(update_fields=["is_active"])
        m.branches.set([] if r.level >= 80 else sorted(valid_b))
    old_extra = set(u.extra_permissions or [])
    keep_old = [p for p in data.extra_permissions if p in old_extra]
    u.extra_permissions = sorted(set(keep_old) | set(acc.check_perms(actor, [p for p in data.extra_permissions if p not in old_extra])))
    u.save(update_fields=["extra_permissions"])
    # AI Kotib o'rinlari (platforma tarifi)
    if t.module_enabled("ai") and not before_ai and u.has_perm_code("ai.use"):
        from modules.ai import limits
        if limits.over_seats(t):
            raise HttpError(400, f"AI Kotib o'rinlari tugagan (tarif bo'yicha {limits.platform(t)['seats']} kishi). Avval boshqa xodimdan oling yoki tarifni oshiring.")


@router.post("/users", auth=auth)
def create(request, data: AccessIn):
    require_perm(request, "core.users.manage")
    if not data.phone or len(re.sub(r"\D", "", data.phone)) < 9:
        raise HttpError(400, "Telefon raqamni to'liq yozing: +998 90 123 45 67")
    phone = User.objects.normalize_phone(data.phone)
    with transaction.atomic():
        u = User.objects.filter(phone=phone).first()
        created = u is None
        if u is None:
            u = User.objects.create_user(phone, full_name=(data.full_name or "").strip())
        else:
            if u.is_active and u.memberships.filter(is_active=True).exists():
                raise HttpError(400, "Bu raqam allaqachon ro'yxatda — ro'yxatdan topib tahrirlang")
            if u.memberships.exists() and not acc.can_manage_user(request.auth, u):
                raise HttpError(403, "Bu raqam sizdan yuqori darajadagi xodimga tegishli")
            if not u.is_active:
                u.is_active = True
            if data.full_name:
                u.full_name = data.full_name.strip()
            u.save()
        _apply(request, u, data, new=True)
    record(request, "create" if created else "update", u, after={"roles": data.role_codes, "branches": data.branch_ids, "extra": data.extra_permissions})
    return _user_out(User.objects.prefetch_related("memberships__role", "memberships__branches").get(pk=u.pk), request.auth, _areas(request.tenant))


@router.put("/users/{uid}", auth=auth)
def update(request, uid: str, data: AccessIn):
    require_perm(request, "core.users.manage")
    u = get_object_or_404(User, pk=uid)
    actor = request.auth
    if u.pk == actor.pk:
        raise HttpError(400, "O'z kirishingizni o'zingiz o'zgartira olmaysiz — yuqori rahbardan so'rang")
    if not acc.can_manage_user(actor, u):
        raise HttpError(403, "Bu xodimni tahrirlay olmaysiz (sizdan yuqori daraja yoki boshqa filial)")
    with transaction.atomic():
        if data.full_name is not None:
            u.full_name = data.full_name.strip()
        if data.phone:
            phone = User.objects.normalize_phone(data.phone)
            if phone != u.phone:
                if User.objects.filter(phone=phone).exclude(pk=u.pk).exists():
                    raise HttpError(400, "Bu telefon boshqa xodimda bor")
                u.phone, u.telegram_id = phone, None     # yangi raqam — botga qaytadan ulanadi
        if data.is_active is False:
            if u.memberships.filter(role__code="owner").exists() and Membership.objects.filter(role__code="owner", user__is_active=True).exclude(user=u).count() == 0:
                raise HttpError(400, "Oxirgi Superadminni o'chirib bo'lmaydi")
            u.is_active = False
            u.save()
            record(request, "deactivate", u)
            return {"ok": True, "is_active": False}
        if data.is_active is True:
            u.is_active = True
        u.save()
        _apply(request, u, data, new=False)
    record(request, "update", u, after={"roles": data.role_codes, "branches": data.branch_ids, "extra": data.extra_permissions})
    return _user_out(User.objects.prefetch_related("memberships__role", "memberships__branches").get(pk=u.pk), actor, _areas(request.tenant))


# ------------------------------------------------------------------ rollar (shablonlar)
class RoleIn(Schema):
    name: str
    description: str = ""
    permissions: list[str] = []


def _roles_guard(request):
    require_perm(request, "core.users.manage")
    if request.auth.access_level() < 80:
        raise HttpError(403, "Rollarni faqat Superadmin va Bosh menejer o'zgartiradi")


def _slug(name: str) -> str:
    tr = str.maketrans({"ʻ": "", "'": "", "ʼ": "", "’": "", "`": ""})
    s = re.sub(r"[^a-z0-9]+", "_", name.lower().translate(tr)).strip("_")[:30] or "rol"
    base, n = s, 2
    while Role.objects.filter(code=s).exists():
        s, n = f"{base}_{n}", n + 1
    return s


@router.post("/roles", auth=auth)
def role_create(request, data: RoleIn):
    _roles_guard(request)
    if not data.name.strip():
        raise HttpError(400, "Rol nomini yozing")
    r = Role.objects.create(code=_slug(data.name), name=data.name.strip(), description=data.description.strip()[:200],
                            permissions=acc.check_perms(request.auth, data.permissions), level=10)
    record(request, "create", r)
    return _role_out(r, request.auth)


@router.put("/roles/{rid}", auth=auth)
def role_update(request, rid: int, data: RoleIn):
    _roles_guard(request)
    r = get_object_or_404(Role, pk=rid)
    if "*" in (r.permissions or []) or r.level >= request.auth.access_level() or r.code == "platform_support":
        raise HttpError(400, "Bu rolni o'zgartirib bo'lmaydi")
    old = set(r.permissions or [])
    keep = [p for p in data.permissions if p in old]
    r.name = data.name.strip() or r.name
    r.description = data.description.strip()[:200]
    r.permissions = sorted(set(keep) | set(acc.check_perms(request.auth, [p for p in data.permissions if p not in old])))
    with transaction.atomic():
        r.save()
        if request.tenant.module_enabled("ai") and "ai.use" not in old and acc.covers(r.permissions, "ai.use"):
            from modules.ai import limits
            if limits.over_seats(request.tenant):
                raise HttpError(400, "AI Kotib o'rinlari yetmaydi — bu rol a'zolari ko'p. AI Kotibni xodimlarga alohida bering.")
    record(request, "update", r)
    return _role_out(r, request.auth)


@router.delete("/roles/{rid}", auth=auth)
def role_delete(request, rid: int):
    _roles_guard(request)
    r = get_object_or_404(Role, pk=rid)
    if r.is_system:
        raise HttpError(400, "Tizim rolini o'chirib bo'lmaydi")
    if r.memberships.filter(is_active=True, user__is_active=True).exists():
        raise HttpError(400, "Bu rolda xodimlar bor — avval ularni boshqa rolga o'tkazing")
    r.memberships.all().delete()
    r.delete()
    return {"ok": True}


# ------------------------------------------------------------------ bitta xodim: kirish va xavfsizlik
def _target(request, uid: str) -> User:
    require_perm(request, "core.users.manage")
    u = get_object_or_404(User, pk=uid)
    if u.pk != request.auth.pk and not acc.can_manage_user(request.auth, u):
        raise HttpError(403, "Bu xodimni boshqara olmaysiz (sizdan yuqori daraja yoki boshqa filial)")
    return u


def _login_info(request, u: User) -> dict:
    from core import security
    fresh = bool(u.tg_invite) and u.tg_invite_at is not None
    return {"history": security.history(u, 10), "bot": security.bot_username(request.tenant), "login_url": security.admin_url(request.tenant),
            "invite": ({"link": f"https://t.me/{security.bot_username(request.tenant)}?start=inv_{u.tg_invite}" if security.bot_username(request.tenant) else "",
                        "expires": (u.tg_invite_at + timedelta(days=security.INVITE_DAYS)).isoformat()} if fresh and not u.telegram_id else None)}


@router.get("/users/{uid}", auth=auth)
def person(request, uid: str):
    u = _target(request, uid)
    u = User.objects.prefetch_related("memberships__role", "memberships__branches").get(pk=u.pk)
    return {**_user_out(u, request.auth, _areas(request.tenant)), "login": _login_info(request, u)}


@router.post("/users/{uid}/invite", auth=auth)
def person_invite(request, uid: str):
    """Telegram taklif havolasi: xodim bosadi → bot uni o'zi taniydi (telefon ulashish shart emas)."""
    from core import security
    u = _target(request, uid)
    if u.telegram_id:
        raise HttpError(400, "Bu xodim Telegram botga allaqachon ulangan")
    r = security.invite(request.tenant, u)
    if not r["link"]:
        raise HttpError(400, "Telegram bot ulanmagan (bot nomi noma'lum) — «Telegram bot» sahifasida tokenni tekshiring")
    record(request, "update", u, after={"telegram_invite": True})
    return r


@router.post("/users/{uid}/logout-all", auth=auth)
def person_logout_all(request, uid: str):
    from core import security
    u = _target(request, uid)
    if u.pk == request.auth.pk:
        raise HttpError(400, "O'zingiz uchun «Sozlamalar → Kirish va xavfsizlik» dan foydalaning")
    security.logout_all(u)
    record(request, "logout_all", u)
    return {"ok": True}


@router.post("/users/{uid}/telegram-unlink", auth=auth)
def person_tg_unlink(request, uid: str):
    u = _target(request, uid)
    u.telegram_id = None
    u.save(update_fields=["telegram_id"])
    record(request, "update", u, after={"telegram": "uzildi"})
    return {"ok": True}


@router.delete("/users/{uid}/password", auth=auth)
def person_password_off(request, uid: str):
    """Parol bilan kirishni o'chirish (faqat Telegram orqali kiradi)."""
    from core import security
    u = _target(request, uid)
    u.set_unusable_password()
    u.save(update_fields=["password"])
    security.logout_all(u)
    record(request, "update", u, after={"password": "o'chirildi"})
    return {"ok": True}
