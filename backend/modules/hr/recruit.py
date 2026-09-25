"""
Ishga olish (ATS): vakansiya → ariza (sayt yoki Telegram) → bosqichlar → qabul (xodim kartasi o'zi ochiladi).

Restoran uchun muhim (Harri / Workstream tajribasi):
  • ariza 2 daqiqada, telefondan — ortiqcha maydon yo'q;
  • «majburiy» savollar (masalan, kechki smena) — mos kelmasa ariza belgilanadi, lekin o'chirilmaydi;
  • har bosqichda nomzodga Telegram xabar (suhbat vaqti, joyi) — kelmay qolish kamayadi.
"""
from __future__ import annotations

import logging

from django.db import transaction
from django.utils import timezone

from core.models import Membership, Role, User

from .models import Application, ApplicationEvent, Employee, Stage, Vacancy, VacancyStatus, WorkHistory

log = logging.getLogger("hr")

EMPLOYMENT = {"full": "To'liq stavka", "part": "Yarim stavka", "shift": "Smenali", "intern": "Amaliyot / o'quvchi"}


def normalize_phone(p: str) -> str:
    digits = "".join(ch for ch in (p or "") if ch.isdigit())
    if len(digits) == 9:
        digits = "998" + digits
    return User.objects.normalize_phone(digits) if len(digits) >= 9 else ""


def salary_text(v: Vacancy) -> str:
    f = lambda x: f"{x:,}".replace(",", " ")  # noqa: E731
    if v.salary_from and v.salary_to:
        s = f"{f(v.salary_from)} – {f(v.salary_to)} so'm"
    elif v.salary_from:
        s = f"{f(v.salary_from)} so'mdan"
    elif v.salary_to:
        s = f"{f(v.salary_to)} so'mgacha"
    else:
        s = "Suhbatda kelishiladi"
    return s + (f" · {v.salary_note}" if v.salary_note else "")


def is_open(v: Vacancy) -> bool:
    return v.status == VacancyStatus.OPEN and not (v.closes_on and v.closes_on < timezone.localdate())


def check_answers(v: Vacancy, answers: list[dict]) -> tuple[list[dict], bool]:
    """Javoblarni savollar bilan birlashtiradi; «must» (majburiy javob) mos kelmasa — knocked_out."""
    out, knocked = [], False
    given = {str(a.get("i")): str(a.get("a") or "").strip() for a in answers or []}
    for i, q in enumerate(v.questions or []):
        a = given.get(str(i), "")
        must = str(q.get("must") or "").strip().lower()
        ok = True
        if must:
            ok = a.strip().lower().startswith(must[:2])
            knocked = knocked or not ok
        out.append({"q": q.get("text", ""), "a": a, "ok": ok, "must": must})
    return out, knocked


def tg(tenant, chat_id, text: str, markup: dict | None = None) -> bool:
    if not chat_id or tenant is None:
        return False
    try:
        if tenant.module_enabled("telegram"):
            from modules.telegram.services import say
            return say(tenant, chat_id, text, markup)
        from integrations.telegram import send_message
        return send_message(chat_id, text, reply_markup=markup)
    except Exception:
        log.exception("hr telegram")
        return False


def _staff_notify(tenant, app: Application) -> None:
    v = app.vacancy
    text = (f"🧑‍🍳 <b>Yangi ariza</b>: {app.full_name}, {app.phone}\n"
            f"Vakansiya: <b>{v.title if v else '—'}</b> · manba: {app.source}"
            + ("\n⚠️ Majburiy savolga mos emas" if app.knocked_out else "")
            + "\nAdmin panel → Ishga olish")
    if v and v.responsible and v.responsible.telegram_id:
        tg(tenant, v.responsible.telegram_id, text)
    try:
        from modules.telegram.services import conf
        chat = (conf(tenant).get("notify_staff_chat_id") or "").strip() if tenant.module_enabled("telegram") else ""
        if chat:
            tg(tenant, chat, text)
    except Exception:
        pass


def event(app: Application, kind: str, text: str, actor=None) -> None:
    ApplicationEvent.objects.create(application=app, kind=kind, text=text[:400], actor=actor)


def create_application(tenant, vacancy: Vacancy | None, *, full_name: str, phone: str, answers=None, experience: str = "",
                       work_history=None, birth_year=None, city: str = "", source: str = "site", tg_chat_id=None,
                       tg_username: str = "", photo=None, resume=None) -> Application:
    ph = normalize_phone(phone)
    if not ph:
        raise ValueError("Telefon raqam noto'g'ri. Masalan: +998 90 123 45 67")
    if not (full_name or "").strip():
        raise ValueError("Ismingizni yozing.")
    ans, knocked = check_answers(vacancy, answers or []) if vacancy else ([], False)
    dup = Application.objects.filter(phone=ph, vacancy=vacancy).exclude(stage__in=[Stage.HIRED, Stage.REJECTED]).first()
    if dup:                                            # takror ariza — yangilab qo'yamiz, ikkinchi karta ochmaymiz
        dup.answers, dup.knocked_out = ans or dup.answers, knocked
        dup.experience = experience or dup.experience
        dup.tg_chat_id = tg_chat_id or dup.tg_chat_id
        dup.save()
        event(dup, "note", f"Qayta ariza yubordi ({source})")
        return dup
    app = Application.objects.create(vacancy=vacancy, full_name=full_name.strip()[:120], phone=ph, answers=ans, knocked_out=knocked,
                                     experience=(experience or "")[:3000], work_history=work_history or [], birth_year=birth_year,
                                     city=city[:80], source=source, tg_chat_id=tg_chat_id, tg_username=(tg_username or "")[:64])
    if photo:
        app.photo.save(photo.name, photo, save=True)
    if resume:
        app.resume.save(resume.name, resume, save=True)
    event(app, "created", f"Ariza keldi: {source}")
    _staff_notify(tenant, app)
    if tg_chat_id:
        tg(tenant, tg_chat_id, f"✅ Arizangiz qabul qilindi: <b>{vacancy.title if vacancy else 'ish'}</b>.\n"
                               "Mas'ul 1–2 kun ichida ko'rib chiqadi va shu yerga yozadi. Rahmat!")
    return app


def _fmt_dt(d) -> str:
    return timezone.localtime(d).strftime("%d.%m.%Y, %H:%M") if d else ""


def move(tenant, app: Application, stage: str, actor=None, *, note: str = "", interview_at=None, place: str = "",
         reason: str = "", notify: bool = True) -> Application:
    if stage not in Stage.values:
        raise ValueError("Noto'g'ri bosqich")
    if stage == Stage.HIRED:
        raise ValueError("Qabul qilish uchun «Qabul qilish» tugmasidan foydalaning.")
    if stage in (Stage.INTERVIEW, Stage.TRIAL) and not interview_at:
        raise ValueError("Suhbat / sinov kuni vaqtini tanlang.")
    if stage == Stage.REJECTED and not reason.strip():
        raise ValueError("Rad etish sababini yozing (nomzodga ko'rinmaydi).")
    app.stage = stage
    app.stage_changed_at = timezone.now()
    if interview_at:
        app.interview_at, app.interview_place = interview_at, place or app.interview_place
    if stage == Stage.REJECTED:
        app.reject_reason = reason.strip()
    app.save()
    title = app.vacancy.title if app.vacancy else "vakansiya"
    event(app, "stage", f"{Stage(stage).label}" + (f" · {_fmt_dt(interview_at)}" if interview_at else "") + (f" · {note}" if note else ""), actor)
    if notify and app.tg_chat_id:
        msgs = {
            Stage.SCREEN: f"👀 Arizangiz ko'rib chiqilmoqda: <b>{title}</b>.",
            Stage.INTERVIEW: f"📅 <b>Suhbatga taklif</b> — {title}\n🕒 {_fmt_dt(app.interview_at)}\n📍 {app.interview_place or tenant.name}\n"
                             "Pasport va (bo'lsa) tibbiy daftarchani olib keling. Kela olmasangiz, shu yerga yozing.",
            Stage.TRIAL: f"🧑‍🍳 <b>Sinov kuni</b> — {title}\n🕒 {_fmt_dt(app.interview_at)}\n📍 {app.interview_place or tenant.name}\nQulay kiyim va poyabzal bilan keling.",
            Stage.OFFER: f"🎉 Sizga ish taklif qilamiz: <b>{title}</b>!\nTafsilotlar uchun mas'ul qo'ng'iroq qiladi.",
            Stage.REJECTED: f"Rahmat, {app.full_name}! Hozircha «{title}» bo'yicha boshqa nomzodni tanladik. "
                            "Ma'lumotlaringizni saqlab qo'ydik — yangi vakansiya bo'lsa, xabar beramiz.",
        }
        if msgs.get(stage):
            tg(tenant, app.tg_chat_id, msgs[stage] + (f"\n\n{note}" if note and stage != Stage.REJECTED else ""))
            event(app, "message", "Nomzodga Telegram xabar yuborildi")
    return app


@transaction.atomic
def hire(tenant, app: Application, actor=None, *, role_code: str | None = None, branch_id=None, position_id=None,
         salary_type: str | None = None, rate: int | None = None, hire_date=None) -> Employee:
    v = app.vacancy
    code = role_code or (v.role_code if v else "waiter")
    role = Role.objects.filter(code=code).first()
    if role is None:
        raise ValueError(f"Rol topilmadi: {code}")
    u, _ = User.objects.get_or_create(phone=app.phone, defaults={"full_name": app.full_name})
    if not u.full_name:
        u.full_name = app.full_name
    if app.tg_chat_id and not u.telegram_id:
        u.telegram_id = app.tg_chat_id
    u.is_active = True
    u.save()
    Membership.objects.get_or_create(user=u, role=role)
    pos = (v.position if v else None)
    if position_id:
        from .models import Position
        pos = Position.objects.filter(pk=position_id).first() or pos
    st = salary_type or (pos.default_salary_type if pos else "monthly")
    r = rate if rate is not None else (v.salary_from if v and v.salary_from and st == "monthly" else (pos.default_rate if pos else 0))
    e, created = Employee.objects.get_or_create(user=u, defaults={
        "position": pos, "branch_id": branch_id or (v.branch_id if v else None), "salary_type": st, "rate": r,
        "hire_date": hire_date or timezone.localdate(), "source": "vakansiya", "about": app.experience[:2000]})
    if not created:
        e.is_active, e.fire_date = True, None
        e.position = pos or e.position
        e.save()
    if app.birth_year and not e.birth_date:
        from datetime import date
        try:
            e.birth_date = date(int(app.birth_year), 1, 1)
            e.save(update_fields=["birth_date"])
        except ValueError:
            pass
    for w in app.work_history or []:
        if (w.get("company") or "").strip():
            WorkHistory.objects.get_or_create(employee=e, company=w["company"].strip()[:160],
                                              defaults={"position": (w.get("position") or "")[:120], "start": str(w.get("years") or "")[:20]})
    app.stage, app.employee, app.stage_changed_at = Stage.HIRED, e, timezone.now()
    app.save()
    event(app, "stage", f"Qabul qilindi → xodim kartasi #{e.pk}", actor)
    if app.tg_chat_id:
        tg(tenant, app.tg_chat_id, f"🎉 <b>{tenant.name}</b> jamoasiga xush kelibsiz, {app.full_name}!\n"
                                   "Botda «📱 Telefonni ulashish» tugmasini bosing — smena, vazifa va o'qitish xabarlari shu yerga keladi.\n"
                                   "Keldim / ketdim: /keldim · /ketdim")
    return e
