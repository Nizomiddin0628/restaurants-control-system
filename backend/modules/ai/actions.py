"""
AI Kotib — o'zgartiruvchi amallar (rahbar buyrug'i bilan), HAMMASI tasdiq bilan.

  1) Rahbar AI'ga aytadi: «Azizga Ombor bo'limini ko'rishga ruxsat ber», «Rustamni Yunusobod filialiga o'tkaz»,
     «Palovni stop-listga qo'y», «Nodiraning parolini tiklab ber»…
  2) AI amalni TAYYORLAYDI (AiAction, holat «proposed») — hech narsa o'zgarmaydi.
  3) Rahbar «✅ Tasdiqlash» ni bosadi (buyruq Telegram'dan bo'lsa — Telegram'da, saytdan bo'lsa — AI Kotib oynasida) → bajariladi.
     Bajarishdan oldin ruxsatlar qayta tekshiriladi (ierarxiya, filial, «o'zida yo'q ruxsatni bera olmaydi»).

Parolni tiklash: AI parolni hech qachon ko'rmaydi va so'ramaydi.
  rahbar buyuradi → xodimga botda «yangi parol yozing» → xodim 2 marta yozadi (xabarlari darhol o'chiriladi, faqat hash saqlanadi)
  → rahbarga «X yangi parol qo'ydi — tasdiqlaysizmi?» → «Ha» → yangi parol kuchga kiradi, xodimning eski kirishlari yopiladi.

MUMKIN EMAS (AI umuman qila olmaydi): kassa, moliya, oylik, to'lov, narx, chegirma, bonus — pul bilan bog'liq hamma narsa;
Superadmin (egasi) rolini berish; o'zining kirishini o'zgartirish.
"""
from __future__ import annotations

import html
import logging
from datetime import timedelta
from types import SimpleNamespace

from django.contrib.auth.hashers import check_password, make_password
from django.db import transaction
from django.utils import timezone
from ninja.errors import HttpError

from core import access as acc
from core.models import Branch, Membership, Role, User

from .models import AiAction

log = logging.getLogger("ai")

MONEY_AREAS = {"pos", "finance", "dashboard"}                       # Kassa, Moliya, savdo raqamlari — AI tegmaydi
MONEY_PERMS = {"hr.payroll", "procurement.pay", "crm.bonus", "payments.view", "pos.refund", "pos.view_all", "catalog.publish"}
NO_ROLES = {"owner", "platform_support"}
TTL_PROPOSED, TTL_WAITING, TTL_READY = timedelta(minutes=30), timedelta(minutes=30), timedelta(hours=3)
PREFIX = "aiact:"
OPEN = (AiAction.PROPOSED, AiAction.WAITING, AiAction.READY)
LEVELS = {"none": "Yo'q", "view": "Ko'radi", "edit": "Ishlaydi (o'zgartira oladi)", "full": "To'liq"}


class ActionError(Exception):
    pass


def esc(s) -> str:
    return html.escape(str(s or ""), quote=False)


def _req(user):
    return SimpleNamespace(auth=user, META={}, request_id="ai")


def _record(user, action, instance, after=None):
    try:
        from core.audit import record
        record(_req(user), action, instance, after=after)
    except Exception:
        log.exception("ai audit")


# ------------------------------------------------------------------ yordamchilar
def find_user(actor, who: str) -> User:
    """Ism yoki telefon bo'yicha xodim + «boshqara olasizmi» tekshiruvi."""
    from core.phone import normalize_uz

    from .tools import find_employee
    who = (who or "").strip()
    if not who:
        raise ActionError("xodim ismi yoki telefoni aytilmadi")
    digits = "".join(c for c in who if c.isdigit())
    u = None
    if len(digits) >= 9:
        try:
            u = User.objects.filter(phone=normalize_uz(who)).first()
        except ValueError:
            u = None
    if u is None:
        hit = find_employee(who)
        if isinstance(hit, list):
            raise ActionError("bir nechta xodim topildi, aniqlashtiring: " + ", ".join(x.full_name for x in hit[:6]))
        u = hit
    if u is None:
        raise ActionError(f"«{who}» ismli xodim topilmadi")
    if u.pk == actor.pk:
        raise ActionError("o'z kirishingizni o'zingiz o'zgartira olmaysiz — yuqori rahbardan so'rang")
    if not acc.can_manage_user(actor, u):
        raise ActionError(f"{u.full_name or u.phone} — bu xodimni boshqara olmaysiz (sizdan yuqori daraja yoki boshqa filial)")
    return u


def _area(code: str) -> dict:
    code = (code or "").strip().lower()
    for a in acc.AREAS:
        if a["code"] == code or a["title"].lower().startswith(code) or code in a["title"].lower():
            return a
    raise ActionError(f"«{code}» degan bo'lim yo'q")


def _level_perms(a: dict, level: str) -> list[str]:
    if level == "none":
        return []
    if level == "full":
        base = [p for p in acc.area_perms(a)] or [p for p in a["full"] if not p.endswith(".*")]
    else:
        base = list(a[level])
    return [p for p in base if p not in MONEY_PERMS]


def _branches_of(u: User) -> list[int]:
    ids: set[int] = set()
    for m in u.memberships.filter(is_active=True, role__level__lt=80).prefetch_related("branches"):
        ids |= {b.pk for b in m.branches.all()}
    return sorted(ids)


def _bname(ids) -> str:
    return ", ".join(Branch.objects.filter(pk__in=ids).values_list("name", flat=True)) or "barcha filiallar"


def _role(code_or_name: str) -> Role:
    s = (code_or_name or "").strip()
    r = Role.objects.filter(code=s).first() or Role.objects.filter(name__iexact=s).first() or Role.objects.filter(name__icontains=s).first()
    if r is None:
        raise ActionError(f"«{s}» degan lavozim yo'q")
    return r


def _perm_check(actor, perms: list[str]) -> list[str]:
    try:
        return acc.check_perms(actor, perms)
    except HttpError as e:
        raise ActionError(str(e)) from e


# ------------------------------------------------------------------ har amal: tekshiruv (check) va bajarish (do)
def check(kind: str, actor: User, target: User | None, p: dict, tenant) -> dict:
    """Tayyorlashda ham, bajarishdan oldin ham chaqiriladi. Xato bo'lsa ActionError."""
    if kind in ("access", "role", "branches", "active", "phone", "password"):
        if not actor.has_perm_code("core.users.manage"):
            raise ActionError("sizda xodimlarga kirish berish ruxsati yo'q")
        if target is None or not acc.can_manage_user(actor, target):
            raise ActionError("bu xodimni boshqara olmaysiz")
    if kind == "access":
        a = _area(p["area"])
        if a["code"] in MONEY_AREAS:
            raise ActionError(f"«{a['title']}» — pul bilan bog'liq bo'lim. Unga kirishni faqat saytda o'zingiz berasiz (Xodimlar va kirish).")
        if a["module"] and not tenant.module_enabled(a["module"]):
            raise ActionError(f"«{a['title']}» moduli restoranda yoqilmagan")
        if p["level"] not in LEVELS:
            raise ActionError("daraja: none | view | edit | full")
        perms = _level_perms(a, p["level"])
        if p["level"] != "none" and not perms:
            raise ActionError(f"«{a['title']}» bo'limida «{LEVELS[p['level']]}» darajasi yo'q — boshqa daraja tanlang")
        _perm_check(actor, perms)
        return {**p, "area": a["code"], "perms": perms}
    if kind == "role":
        r = _role(p["role"])
        if r.code in NO_ROLES:
            raise ActionError("Superadmin (egasi) rolini AI orqali berib/olib bo'lmaydi — faqat saytda")
        if not acc.can_grant_role(actor, r):
            raise ActionError(f"«{r.name}» rolini bera olmaysiz — bu sizdan yuqori yoki teng daraja")
        has = target.memberships.filter(role=r, is_active=True).exists()
        if p["op"] == "remove":
            if not has:
                raise ActionError(f"{target.full_name} da «{r.name}» lavozimi yo'q")
            if target.memberships.filter(is_active=True).count() <= 1:
                raise ActionError("xodimda kamida bitta lavozim qolishi kerak — avval boshqasini qo'shing yoki xodimni bloklang")
        elif has:
            raise ActionError(f"{target.full_name} da «{r.name}» lavozimi allaqachon bor")
        return {**p, "role": r.code}
    if kind == "branches":
        ids = [int(x) for x in p.get("branch_ids") or []]
        if not ids:
            raise ActionError("filial(lar)ni ayting")
        try:
            ids = acc.check_branches(actor, ids)
        except HttpError as e:
            raise ActionError(str(e)) from e
        if Branch.objects.filter(pk__in=ids, deleted_at__isnull=True).count() != len(set(ids)):
            raise ActionError("bunday filial topilmadi")
        return {**p, "branch_ids": sorted(set(ids))}
    if kind == "active":
        if not p["active"] and target.memberships.filter(role__code="owner", is_active=True).exists():
            raise ActionError("Superadminni bloklab bo'lmaydi")
        return p
    if kind == "phone":
        from core.phone import normalize_uz
        try:
            ph = normalize_uz(p["phone"])
        except ValueError as e:
            raise ActionError(str(e)) from e
        if User.objects.filter(phone=ph).exclude(pk=target.pk).exists():
            raise ActionError("bu raqam boshqa xodimda bor")
        if ph == target.phone:
            raise ActionError("raqam o'zgarmayapti — hozir ham shu")
        return {**p, "phone": ph}
    if kind == "create":
        if not actor.has_perm_code("core.users.manage"):
            raise ActionError("sizda xodim qo'shish ruxsati yo'q")
        from core.phone import normalize_uz
        try:
            ph = normalize_uz(p["phone"])
        except ValueError as e:
            raise ActionError(str(e)) from e
        if len((p.get("full_name") or "").split()) < 2:
            raise ActionError("xodimning ism va familiyasini ayting")
        ex = User.objects.filter(phone=ph).first()
        if ex and ex.is_active and ex.memberships.filter(is_active=True).exists():
            raise ActionError(f"bu raqam allaqachon ro'yxatda ({ex.full_name}) — uni o'zgartirish uchun ismini ayting")
        r = _role(p["role"])
        if r.code in NO_ROLES or not acc.can_grant_role(actor, r):
            raise ActionError(f"«{r.name}» lavozimini bera olmaysiz")
        ids = [int(x) for x in p.get("branch_ids") or []]
        try:
            ids = acc.check_branches(actor, ids) if ids or actor.branch_scope() is not None else []
        except HttpError as e:
            raise ActionError(str(e)) from e
        return {**p, "phone": ph, "role": r.code, "branch_ids": ids}
    if kind == "stop":
        if not actor.has_perm_code("catalog.edit"):
            raise ActionError("sizda menyuni o'zgartirish ruxsati yo'q")
        return p
    if kind == "password":
        if not target.telegram_id:
            raise ActionError(f"{target.full_name} Telegram botga ulanmagan — bot orqali parol qo'ya olmaydi. "
                              "Saytda: Xodimlar va kirish → xodim → «Kirish va xavfsizlik» (Telegram taklif havolasi yoki parol)")
        return p
    raise ActionError("noma'lum amal")


def _do(kind: str, actor: User, target: User | None, p: dict, tenant) -> str:
    from core import security
    if kind == "access":
        a = next(x for x in acc.AREAS if x["code"] == p["area"])
        drop = set(acc.area_perms(a)) | set(a["full"]) | set(a["edit"]) | set(a["view"])
        extra = [x for x in (target.extra_permissions or []) if x not in drop] + list(p["perms"])
        before_ai = target.has_perm_code("ai.use")
        target.extra_permissions = sorted(set(extra))
        target.save(update_fields=["extra_permissions"])
        if a["code"] == "ai" and not before_ai and target.has_perm_code("ai.use"):
            from . import limits
            if limits.over_seats(tenant):
                target.extra_permissions = [x for x in target.extra_permissions if x not in drop]
                target.save(update_fields=["extra_permissions"])
                raise ActionError(f"AI Kotib o'rinlari tugagan (tarif bo'yicha {limits.platform(tenant)['seats']} kishi)")
        _record(actor, "update", target, {"ai": True, "area": a["code"], "level": p["level"]})
        role_perms = set().union(*[set(m.role.permissions or []) for m in target.memberships.filter(is_active=True).select_related("role")] or [set()])
        now = acc.area_level(role_perms | set(target.extra_permissions), a)
        note = ""
        if p["level"] == "none" and now != "none":
            note = " (lekin lavozimi orqali baribir kiradi — butunlay yopish uchun lavozimini o'zgartiring)"
        return f"{target.full_name}: «{a['title']}» — {LEVELS.get(p['level'])}{note}"
    if kind == "role":
        r = Role.objects.get(code=p["role"])
        if p["op"] == "remove":
            Membership.objects.filter(user=target, role=r).delete()
            _record(actor, "update", target, {"ai": True, "role_removed": r.code})
            return f"{target.full_name}: «{r.name}» lavozimi olib tashlandi"
        bids = _branches_of(target)
        m, _ = Membership.objects.get_or_create(user=target, role=r)
        if not m.is_active:
            m.is_active = True
            m.save(update_fields=["is_active"])
        m.branches.set([] if r.level >= 80 else bids)
        _record(actor, "update", target, {"ai": True, "role_added": r.code})
        return f"{target.full_name}: «{r.name}» lavozimi qo'shildi"
    if kind == "branches":
        for m in target.memberships.filter(is_active=True, role__level__lt=80):
            m.branches.set(p["branch_ids"])
        _record(actor, "update", target, {"ai": True, "branches": p["branch_ids"]})
        return f"{target.full_name}: filial — {_bname(p['branch_ids'])}"
    if kind == "active":
        target.is_active = bool(p["active"])
        target.save(update_fields=["is_active"])
        if not target.is_active:
            security.logout_all(target)
        _record(actor, "activate" if target.is_active else "deactivate", target, {"ai": True})
        return f"{target.full_name}: " + ("kirish qayta yoqildi" if target.is_active else "bloklandi — tizimga kira olmaydi")
    if kind == "phone":
        old_tg = target.telegram_id
        target.phone, target.telegram_id = p["phone"], None          # yangi raqam — botga qaytadan ulanadi
        target.save(update_fields=["phone", "telegram_id"])
        security.logout_all(target)
        if old_tg:
            _send(tenant, old_tg, f"ℹ️ Kirish raqamingiz (login) o'zgartirildi: <b>{esc(p['phone'])}</b>.\nSaytga endi shu raqam bilan kirasiz. "
                                  "Botga qaytadan /start → «📱 Telefonni ulashish».")
        _record(actor, "update", target, {"ai": True, "phone": p["phone"]})
        return f"{target.full_name}: login (telefon) — {p['phone']}"
    if kind == "create":
        r = Role.objects.get(code=p["role"])
        with transaction.atomic():
            u = User.objects.filter(phone=p["phone"]).first()
            if u is None:
                u = User.objects.create_user(p["phone"], full_name=p["full_name"].strip())
            else:
                u.is_active, u.full_name = True, p["full_name"].strip()
                u.save(update_fields=["is_active", "full_name"])
            m, _ = Membership.objects.get_or_create(user=u, role=r)
            m.is_active = True
            m.save(update_fields=["is_active"])
            m.branches.set([] if r.level >= 80 else p["branch_ids"])
        _record(actor, "create", u, {"ai": True, "role": r.code, "branches": p["branch_ids"]})
        return f"Yangi xodim: {u.full_name} ({u.phone}) — {r.name}, {_bname(p['branch_ids']) if r.level < 80 else 'barcha filiallar'}. Saytga birinchi kirishda raqamini tasdiqlab parol qo'yadi"
    if kind == "stop":
        from modules.catalog.models import Product
        pr = Product.objects.filter(pk=p["product_id"], deleted_at__isnull=True).first()
        if pr is None:
            raise ActionError("taom topilmadi")
        pr.in_stop_list = bool(p["stop"])
        pr.save(update_fields=["in_stop_list"])
        _record(actor, "update", pr, {"ai": True, "in_stop_list": pr.in_stop_list})
        return f"«{p['name']}» — " + ("stop-listga qo'yildi (kassa va saytda ko'rinmaydi)" if pr.in_stop_list else "stop-listdan chiqarildi, yana sotuvda")
    if kind == "password":
        pw = p.get("pw")
        if not pw:
            raise ActionError("xodim hali yangi parolni yozmagan")
        target.password = pw
        target.save(update_fields=["password"])
        security.logout_all(target)
        _record(actor, "update", target, {"ai": True, "password": "yangilandi (xodim o'zi qo'ydi)"})
        if target.telegram_id:
            _send(tenant, target.telegram_id, "✅ <b>Parolingiz yangilandi.</b>\nSaytga telefon raqamingiz va yangi parolingiz bilan kiring.\n" + security.admin_url(tenant))
        return f"{target.full_name}: yangi parol kuchga kirdi, eski kirishlari yopildi"
    raise ActionError("noma'lum amal")


# ------------------------------------------------------------------ Telegram yordamchilari
def _send(tenant, chat_id, text: str, markup: dict | None = None) -> int | None:
    from .tg import send
    try:
        return send(tenant, chat_id, text, markup)
    except Exception:
        log.exception("ai action send")
        return None


def _kb(a: AiAction) -> dict:
    return {"inline_keyboard": [[{"text": "✅ Tasdiqlash", "callback_data": f"{PREFIX}ok:{a.pk}"},
                                 {"text": "✖️ Bekor", "callback_data": f"{PREFIX}no:{a.pk}"}]]}


def ask_text(a: AiAction) -> str:
    head = "🔐 <b>Parolni almashtirish</b>" if a.kind == "password" else "🛠 <b>Tasdiqlaysizmi?</b>"
    return f"{head}\n\n{esc(a.summary)}\n\n<i>Tasdiqlasangiz — darhol kuchga kiradi.</i>"


def send_confirm(tenant, a: AiAction) -> None:
    """Buyruq bergan rahbarga Telegram'da «Tasdiqlaysizmi?» (Ha / Bekor)."""
    chat = a.requested_by.telegram_id
    if not chat:
        return
    mid = _send(tenant, chat, ask_text(a), _kb(a))
    if mid:
        a.tg_msgs = [*(a.tg_msgs or []), [chat, mid]]
        a.save(update_fields=["tg_msgs"])


def _close_tg(tenant, a: AiAction, text: str) -> None:
    from .tg import edit
    for chat, mid in a.tg_msgs or []:
        try:
            edit(tenant, chat, mid, text)
        except Exception:
            pass


# ------------------------------------------------------------------ tayyorlash (AI asboblari chaqiradi)
def propose(ctx, kind: str, target: User | None, params: dict, summary: str) -> dict:
    actor = ctx.user
    try:
        p = check(kind, actor, target, params, ctx.tenant)
    except ActionError as e:
        return {"ok": False, "error": str(e)}
    AiAction.objects.filter(requested_by=actor, kind=kind, target=target, status=AiAction.PROPOSED).update(status=AiAction.CANCELLED)
    a = AiAction.objects.create(kind=kind, params=p, summary=summary, requested_by=actor, target=target,
                                channel=getattr(ctx, "channel", "panel"), expires_at=timezone.now() + TTL_PROPOSED)
    lst = getattr(ctx, "actions", None)
    if lst is not None:
        lst.append(a.pk)
    return {"ok": True, "status": "TASDIQ KUTILMOQDA — hali bajarilmadi", "action": summary,
            "note": "Foydalanuvchiga amal tayyorligini va «✅ Tasdiqlash» tugmasini bosishi kerakligini qisqa ayt. «Bajarildi» dema."}


def start_password(ctx, target: User) -> dict:
    actor = ctx.user
    try:
        check("password", actor, target, {}, ctx.tenant)
    except ActionError as e:
        return {"ok": False, "error": str(e)}
    AiAction.objects.filter(kind="password", target=target, status__in=OPEN).update(status=AiAction.CANCELLED)
    a = AiAction.objects.create(kind="password", params={}, summary=f"{target.full_name} ({target.phone}) — yangi parol", requested_by=actor,
                                target=target, status=AiAction.WAITING, channel=getattr(ctx, "channel", "panel"),
                                expires_at=timezone.now() + TTL_WAITING)
    mid = _send(ctx.tenant, target.telegram_id,
                f"🔐 <b>Yangi parol qo'yish</b>\n\n{esc(actor.full_name or 'Rahbaringiz')} parolingizni yangilashni so'radi.\n\n"
                "Yangi parolni shu yerga <b>yozib yuboring</b> (kamida 6 belgi). Xavfsizlik uchun xabaringiz darhol o'chiriladi.\n\n"
                "Siz so'ramagan bo'lsangiz — /bekor deb yozing.")
    if not mid:
        a.status, a.result = AiAction.FAILED, "xodimga Telegram xabari yetmadi"
        a.save(update_fields=["status", "result"])
        return {"ok": False, "error": f"{target.full_name}ga Telegram xabari yetmadi (botni bloklagan bo'lishi mumkin)"}
    lst = getattr(ctx, "actions", None)
    if lst is not None:
        lst.append(a.pk)
    return {"ok": True, "status": f"{target.full_name}ga Telegram'da xabar yuborildi",
            "note": "Xodim botda yangi parolni 2 marta yozadi, keyin sizdan tasdiq so'raladi (Telegram'dan buyurgan bo'lsangiz — Telegram'da, saytdan — AI Kotib oynasida). "
                    "Parolni AI ko'rmaydi. Shuni foydalanuvchiga qisqa ayt."}


# ------------------------------------------------------------------ tasdiqlash / bekor qilish
def confirm(tenant, aid: int, user: User) -> tuple[bool, str]:
    with transaction.atomic():
        a = AiAction.objects.select_for_update(of=("self",)).select_related("target", "requested_by").filter(pk=aid).first()
        if a is None or a.requested_by_id != user.pk:
            return False, "Bu amal sizga tegishli emas"
        if a.status == AiAction.WAITING:
            return False, "Xodim hali yangi parolni yozmadi — yozgach tasdiqlaysiz"
        if a.status not in (AiAction.PROPOSED, AiAction.READY):
            return False, f"Bu amal allaqachon: {a.get_status_display().lower()}"
        if a.expired:
            a.status = AiAction.EXPIRED
            a.save(update_fields=["status"])
            return False, "Muddati o'tdi — AI Kotibga qaytadan buyuring"
        try:
            p = check(a.kind, user, a.target, a.params, tenant)
            res = _do(a.kind, user, a.target, p, tenant)
            a.status, a.result = AiAction.DONE, res[:400]
            ok = True
        except ActionError as e:
            a.status, a.result = AiAction.FAILED, str(e)[:400]
            ok = False
        if a.kind == "password":
            a.params = {}
        a.decided_at = timezone.now()
        a.save(update_fields=["status", "result", "params", "decided_at"])
    _close_tg(tenant, a, ("✅ <b>Bajarildi:</b> " if ok else "⚠️ <b>Bajarilmadi:</b> ") + esc(a.result))
    return ok, a.result


def cancel(tenant, aid: int, user: User) -> tuple[bool, str]:
    a = AiAction.objects.select_related("target").filter(pk=aid, requested_by=user).first()
    if a is None:
        return False, "Bu amal sizga tegishli emas"
    if a.status not in OPEN:
        return False, f"Bu amal allaqachon: {a.get_status_display().lower()}"
    a.status, a.decided_at, a.params = AiAction.CANCELLED, timezone.now(), {}
    a.save(update_fields=["status", "decided_at", "params"])
    _close_tg(tenant, a, "✖️ <b>Bekor qilindi:</b> " + esc(a.summary))
    if a.kind == "password" and a.target and a.target.telegram_id:
        _send(tenant, a.target.telegram_id, "❌ Parolni yangilash bekor qilindi — eski parolingiz amal qiladi.")
    return True, "Bekor qilindi"


def open_for(user: User) -> list[AiAction]:
    now = timezone.now()
    AiAction.objects.filter(requested_by=user, status__in=OPEN, expires_at__lt=now).update(status=AiAction.EXPIRED)
    return list(AiAction.objects.filter(requested_by=user, status__in=OPEN).select_related("target")[:20])


def out(a: AiAction) -> dict:
    return {"id": a.pk, "kind": a.kind, "summary": a.summary, "status": a.status, "status_label": a.get_status_display(),
            "result": a.result, "target": (a.target.full_name if a.target else None),
            "can_confirm": a.status in (AiAction.PROPOSED, AiAction.READY), "created_at": a.created_at.isoformat(),
            "expires_at": a.expires_at.isoformat()}


# ------------------------------------------------------------------ Telegram: tugmalar va xodimning parol yozishi
def handle_callback(tenant, cq: dict) -> bool:
    from .tg import _tok, call
    data = str(cq.get("data") or "")
    if not data.startswith(PREFIX):
        return False
    chat_id = ((cq.get("message") or {}).get("chat") or {}).get("id")
    user = User.objects.filter(telegram_id=chat_id, is_active=True).first() if chat_id else None
    try:
        _, act, aid = data.split(":", 2)
        aid = int(aid)
    except ValueError:
        return True
    if user is None:
        call("answerCallbackQuery", {"callback_query_id": cq.get("id"), "text": "Ruxsat yo'q"}, _tok(tenant))
        return True
    ok, msg = confirm(tenant, aid, user) if act == "ok" else cancel(tenant, aid, user)
    call("answerCallbackQuery", {"callback_query_id": cq.get("id"), "text": msg[:180]}, _tok(tenant))
    if not ok and (cq.get("message") or {}).get("message_id"):
        from .tg import edit
        edit(tenant, chat_id, cq["message"]["message_id"], "ℹ️ " + esc(msg))
    return True


CANCEL_WORDS = {"/bekor", "/cancel", "bekor", "bekor qilish", "/stop"}


def maybe_password(tenant, upd: dict) -> bool:
    """Xodim botda yangi parolni yozyapti (rahbar AI orqali so'ragan). Parol xabari darhol o'chiriladi."""
    msg = upd.get("message") or {}
    chat = msg.get("chat") or {}
    text = (msg.get("text") or "").strip()
    if not msg or chat.get("type") not in (None, "private") or not text:
        return False
    chat_id = chat.get("id")
    a = (AiAction.objects.select_related("target", "requested_by")
         .filter(kind="password", status=AiAction.WAITING, target__telegram_id=chat_id).order_by("-id").first())
    if a is None:
        return False
    if a.expired:
        a.status, a.params = AiAction.EXPIRED, {}
        a.save(update_fields=["status", "params"])
        return False
    low = text.lower()
    if low in CANCEL_WORDS:
        a.status, a.params, a.decided_at, a.result = AiAction.CANCELLED, {}, timezone.now(), "xodim bekor qildi"
        a.save(update_fields=["status", "params", "decided_at", "result"])
        _send(tenant, chat_id, "Bekor qilindi — eski parolingiz amal qiladi.")
        if a.requested_by.telegram_id and a.channel == "telegram":
            _send(tenant, a.requested_by.telegram_id, f"ℹ️ {esc(a.target.full_name)} parolni yangilashni bekor qildi.")
        return True
    if text.startswith("/"):
        return False                                   # boshqa buyruq (/start…) — odatdagidek
    try:
        from .tg import _known_buttons
        if text in _known_buttons():
            return False
    except Exception:
        pass
    from .tg import _tok, call
    if msg.get("message_id"):
        call("deleteMessage", {"chat_id": chat_id, "message_id": msg["message_id"]}, _tok(tenant))   # parol chatda qolmasin
    p = dict(a.params or {})
    if len(text) < 6 or len(text) > 128:
        _send(tenant, chat_id, "⚠️ Parol kamida 6 belgi bo'lsin. Qaytadan yozing (yoki /bekor).")
        return True
    if not p.get("first"):
        p["first"] = make_password(text)
        a.params = p
        a.save(update_fields=["params"])
        _send(tenant, chat_id, "👍 Endi shu parolni <b>yana bir marta</b> yozing (tasdiqlash uchun).")
        return True
    if not check_password(text, p["first"]):
        a.params = {}
        a.save(update_fields=["params"])
        _send(tenant, chat_id, "❌ Ikkala parol bir xil emas. Yangi parolni boshidan yozing.")
        return True
    a.params = {"pw": p["first"]}
    a.status, a.expires_at = AiAction.READY, timezone.now() + TTL_READY
    a.save(update_fields=["params", "status", "expires_at"])
    _send(tenant, chat_id, "✅ Qabul qilindi. Rahbaringiz tasdiqlagach yangi parol kuchga kiradi — sizga xabar keladi.")
    a.summary = f"{a.target.full_name} ({a.target.phone}) yangi parol qo'ydi. Tasdiqlaysizmi?"
    a.save(update_fields=["summary"])
    if a.channel == "telegram":
        send_confirm(tenant, a)
    return True
