"""
Telegram bot — HR suhbatlari («Xodimlar» moduli yoqilgan bo'lsa):

1) Ariza: saytdagi «Telegram orqali ariza» → t.me/<bot>?start=job_<id>  yoki botda «💼 Vakansiyalar».
   Qadamlar: ism → telefon (tugma) → tug'ilgan yil → vakansiya savollari → tajriba → oldingi ish joyi → yuborish.
   Har qadamda «✖️ Bekor qilish». 2 daqiqa, rezyume shart emas.
2) Kayfiyat: /ketdim dan keyin «Smena qanday o'tdi?» 😀 🙂 😐 🙁 (callback mood:<attendance>:<1-4>).
"""
from __future__ import annotations

from .models import BotUser

BTN_JOBS, BTN_SKIP2, BTN_SEND = "💼 Vakansiyalar", "⏭ O'tkazib yuborish", "✅ Arizani yuborish"
MOODS = {4: "😀", 3: "🙂", 2: "😐", 1: "🙁"}


def hr_on(tenant) -> bool:
    return tenant.module_enabled("hr")


def open_jobs():
    from modules.hr import recruit
    from modules.hr.models import Vacancy, VacancyStatus
    return [v for v in Vacancy.objects.filter(status=VacancyStatus.OPEN) if recruit.is_open(v)]


def _kb(*rows):
    from .services import BTN_CANCEL
    return {"keyboard": [*rows, [BTN_CANCEL]], "resize_keyboard": True}


def show_jobs(tenant, bu: BotUser) -> bool:
    from modules.hr import recruit

    from .services import say
    jobs = open_jobs()
    if not jobs:
        say(tenant, bu.chat_id, "Hozircha ochiq vakansiya yo'q. Keyinroq qayta kiring 🙂")
        return True
    lines = [f"💼 <b>{tenant.name} — vakansiyalar</b>"]
    lines += [f"• <b>{v.title}</b> — {recruit.salary_text(v)}" for v in jobs[:10]]
    say(tenant, bu.chat_id, "\n".join(lines) + "\n\nQaysi biriga ariza berasiz? 👇",
        {"inline_keyboard": [[{"text": f"📝 {v.title}", "callback_data": f"job:{v.pk}"}] for v in jobs[:10]]})
    return True


def start_apply(tenant, bu: BotUser, vid: int) -> bool:
    from modules.hr import recruit
    from modules.hr.models import Vacancy

    from .services import say
    v = Vacancy.objects.filter(pk=vid).first()
    if v is None or not recruit.is_open(v):
        say(tenant, bu.chat_id, "Bu vakansiya yopilgan. Boshqalarini ko'ring: «💼 Vakansiyalar».")
        return True
    lines = [f"📝 <b>{v.title}</b>", f"💰 {recruit.salary_text(v)}"]
    if v.schedule:
        lines.append(f"🕒 {v.schedule}")
    if v.requirements:
        lines.append("\n<b>Talablar:</b>\n" + "\n".join(f"• {x}" for x in v.requirements[:6]))
    lines.append("\nAriza 2 daqiqa oladi. <b>Ism familiyangizni</b> yozing:")
    bu.state = {"step": "rec_name", "job": v.pk, "d": {"answers": []}}
    bu.save(update_fields=["state"])
    say(tenant, bu.chat_id, "\n".join(lines), _kb([bu.full_name] if bu.full_name else []))
    return True


def step(tenant, bu: BotUser, msg: dict, text: str) -> bool:
    """Ariza suhbatining navbatdagi qadami. True — xabar shu yerda qayta ishlandi."""
    from modules.hr import recruit
    from modules.hr.models import Vacancy

    from .services import BTN_PHONE, main_keyboard, normalize, say
    st = dict(bu.state or {})
    d = st.get("d") or {"answers": []}
    v = Vacancy.objects.filter(pk=st.get("job")).first()
    if v is None:
        bu.state = {}
        bu.save(update_fields=["state"])
        say(tenant, bu.chat_id, "Vakansiya topilmadi.", main_keyboard(tenant, bu, None))
        return True
    s = st.get("step")

    def go(nxt: str, prompt: str, markup=None):
        st.update(step=nxt, d=d)
        bu.state = st
        bu.save(update_fields=["state"])
        say(tenant, bu.chat_id, prompt, markup or _kb())

    if s == "rec_name":
        if len(text) < 3:
            return go("rec_name", "Iltimos, ism familiyangizni to'liq yozing:") or True
        d["name"] = text[:120]
        if bu.phone:
            d["phone"] = bu.phone
            go("rec_year", f"📱 Telefon: {bu.phone}\n\nTug'ilgan yilingiz? (masalan 1999)", _kb())
        else:
            go("rec_phone", "📱 Telefon raqamingizni ulashing (tugma) yoki yozing:",
               {"keyboard": [[{"text": BTN_PHONE, "request_contact": True}]], "resize_keyboard": True})
        return True
    if s == "rec_phone":
        c = msg.get("contact") or {}
        ph = normalize(c.get("phone_number") or text)
        if not ph or len(ph) < 12:
            return go("rec_phone", "Raqam noto'g'ri. Masalan: +998 90 123 45 67",
                      {"keyboard": [[{"text": BTN_PHONE, "request_contact": True}]], "resize_keyboard": True}) or True
        d["phone"] = ph
        if not bu.phone:
            bu.phone = ph
            bu.save(update_fields=["phone"])
        go("rec_year", "Tug'ilgan yilingiz? (masalan 1999)")
        return True
    if s == "rec_year":
        y = "".join(ch for ch in text if ch.isdigit())
        if not (len(y) == 4 and 1950 < int(y) < 2012):
            return go("rec_year", "4 xonali yil yozing, masalan 1999:") or True
        d["year"] = int(y)
        st["qi"] = 0
        return _ask_q(tenant, bu, st, d, v, go)
    if s == "rec_q":
        i = int(st.get("qi", 0))
        d["answers"].append({"i": i, "a": text[:300]})
        st["qi"] = i + 1
        return _ask_q(tenant, bu, st, d, v, go)
    if s == "rec_exp":
        d["exp"] = "" if text == BTN_SKIP2 else text[:3000]
        go("rec_prev", "Oxirgi ish joyingiz va lavozimingiz? (masalan: «Rayhon» restorani, ofitsiant, 2 yil)", _kb([BTN_SKIP2]))
        return True
    if s == "rec_prev":
        d["prev"] = "" if text == BTN_SKIP2 else text[:200]
        summary = [f"<b>Arizangiz:</b> {v.title}", f"👤 {d.get('name')}", f"📱 {d.get('phone')}", f"🎂 {d.get('year')}"]
        for a in d["answers"]:
            q = (v.questions or [])[a["i"]]["text"] if a["i"] < len(v.questions or []) else ""
            summary.append(f"❓ {q} — <b>{a['a']}</b>")
        if d.get("exp"):
            summary.append(f"📝 {d['exp'][:200]}")
        if d.get("prev"):
            summary.append(f"🏢 {d['prev']}")
        go("rec_confirm", "\n".join(summary) + "\n\nHammasi to'g'rimi?", _kb([BTN_SEND]))
        return True
    if s == "rec_confirm":
        if text != BTN_SEND:
            return go("rec_confirm", "Yuborish uchun «✅ Arizani yuborish» tugmasini bosing yoki bekor qiling.", _kb([BTN_SEND])) or True
        wh = [{"company": d["prev"], "position": "", "years": ""}] if d.get("prev") else []
        frm = msg.get("from") or {}
        try:
            recruit.create_application(tenant, v, full_name=d.get("name", ""), phone=d.get("phone", ""), answers=d["answers"],
                                       experience=d.get("exp", ""), work_history=wh, birth_year=d.get("year"), source="telegram",
                                       tg_chat_id=bu.chat_id, tg_username=frm.get("username") or bu.username)
        except ValueError as e:
            say(tenant, bu.chat_id, f"Xato: {e}")
        bu.state = {}
        bu.save(update_fields=["state"])
        say(tenant, bu.chat_id, "Asosiy menyu 👇", main_keyboard(tenant, bu, None))
        return True
    return False


def _ask_q(tenant, bu, st, d, v, go) -> bool:
    qs = v.questions or []
    i = int(st.get("qi", 0))
    if i < len(qs):
        q = qs[i]
        mk = _kb(["Ha", "Yo'q"]) if q.get("type") == "yesno" else _kb()
        go("rec_q", f"❓ {q.get('text')}", mk)
        return True
    go("rec_exp", "O'zingiz haqingizda qisqacha: tajriba, qachondan ishga chiqa olasiz?", _kb([BTN_SKIP2]))
    return True


# ------------------------------------------------------------------ kayfiyat (smenadan keyin)
def mood_markup(att_id: int) -> dict:
    return {"inline_keyboard": [[{"text": MOODS[n], "callback_data": f"mood:{att_id}:{n}"} for n in (4, 3, 2, 1)]]}


def save_mood(tenant, chat_id: int, att_id: int, mood: int) -> str:
    from modules.hr.models import Attendance, ShiftFeedback
    a = Attendance.objects.select_related("employee__user").filter(pk=att_id, employee__user__telegram_id=chat_id).first()
    if a is None or mood not in MOODS:
        return "Topilmadi"
    ShiftFeedback.objects.update_or_create(attendance=a, defaults={"employee": a.employee, "mood": mood,
                                                                    "date": a.check_in.date()})
    return {4: "Zo'r! Rahmat 🙌", 3: "Rahmat!", 2: "Tushunarli. Nima yaxshilash kerak — yozib qoldirishingiz mumkin.",
            1: "Afsus 😔 Menejeringizga aytamiz — yozib qoldiring, nima bo'ldi?"}[mood]


def handle_callback(tenant, cq: dict) -> bool:
    from integrations.telegram import call

    from .services import touch
    data = cq.get("data") or ""
    msg = cq.get("message") or {}
    chat_id = (msg.get("chat") or {}).get("id") or (cq.get("from") or {}).get("id")
    reply = ""
    if data.startswith("job:") and hr_on(tenant):
        bu = touch({"from": cq.get("from") or {}, "chat": {"id": chat_id}})
        start_apply(tenant, bu, int(data.split(":")[1]))
    elif data.startswith("mood:") and hr_on(tenant):
        _, att, n = data.split(":")
        reply = save_mood(tenant, chat_id, int(att), int(n))
    else:
        return False
    try:
        from .services import token
        call("answerCallbackQuery", {"callback_query_id": cq.get("id"), "text": reply[:190]}, token(tenant))
    except Exception:
        pass
    return True
