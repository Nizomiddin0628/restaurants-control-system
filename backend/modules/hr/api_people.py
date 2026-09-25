"""
HR API (2-qism) — /api/v1/hr/...: xodim profili, ish tarixi, hujjatlar, baholash, KPI, vakansiyalar, nomzodlar.
Asosiy router (`api.router`) ga ulanadi — alohida modul emas, «Xodimlar» modulining davomi.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Optional

from django.db.models import Count, Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from ninja import File, Schema
from ninja.errors import HttpError
from ninja.files import UploadedFile

from core.audit import record
from core.auth import auth

from . import kpi, recruit
from .api import EmployeeOut, _employee_qs, _guard, router
from .models import (
    REVIEW_CRITERIA,
    Application,
    DocKind,
    Employee,
    EmployeeDocument,
    PayrollStatus,
    Payslip,
    Review,
    ShiftFeedback,
    Stage,
    Vacancy,
    VacancyStatus,
    WorkHistory,
    month_start,
)


def _d(v):
    return v.isoformat() if v else None


def _month(s: Optional[str]) -> date:
    if s:
        try:
            y, m = s.split("-")[:2]
            return date(int(y), int(m), 1)
        except (ValueError, TypeError):
            raise HttpError(400, "Oy formati: YYYY-MM") from None
    return month_start(timezone.localdate())


def _media_url(f):
    try:
        return f.url if f else None
    except Exception:
        return None


# ================================================================== XODIM PROFILI
class ProfileIn(Schema):
    birth_date: Optional[date] = None
    gender: str = ""
    address: str = ""
    emergency_name: str = ""
    emergency_phone: str = ""
    education: str = ""
    languages: list[str] = []
    skills: list[str] = []
    about: str = ""
    medical_book_until: Optional[date] = None


def _wh_out(w: WorkHistory) -> dict:
    return {"id": w.pk, "company": w.company, "position": w.position, "start": w.start, "end": w.end,
            "reason_left": w.reason_left, "reference_phone": w.reference_phone, "note": w.note}


def _doc_out(x: EmployeeDocument) -> dict:
    today = timezone.localdate()
    return {"id": x.pk, "kind": x.kind, "kind_label": DocKind(x.kind).label, "title": x.title,
            "url": _media_url(x.file) or x.url or None, "expires_on": _d(x.expires_on),
            "expired": bool(x.expires_on and x.expires_on < today),
            "expiring": bool(x.expires_on and 0 <= (x.expires_on - today).days <= 30)}


def _review_out(r: Review) -> dict:
    return {"id": r.pk, "period": r.period.strftime("%Y-%m"), "scores": r.scores, "average": r.average,
            "strengths": r.strengths, "improve": r.improve, "goals": r.goals,
            "reviewer": r.reviewer.full_name if r.reviewer_id else None, "created_at": _d(r.created_at)}


@router.get("/employees/{int:eid}/profile", auth=auth)
def employee_profile(request, eid: int, month: Optional[str] = None):
    """To'liq xodim profili: shaxsiy ma'lumot, ish tarixi, hujjatlar, baholar, KPI, kayfiyat, qayerdan kelgani."""
    _guard(request, "hr.view")
    e = get_object_or_404(_employee_qs(), pk=eid)
    today = timezone.localdate()
    m = _month(month)
    app = Application.objects.filter(employee=e).select_related("vacancy").first()
    fb = list(ShiftFeedback.objects.filter(employee=e)[:12])
    tenure = (today - e.hire_date).days if e.hire_date else 0
    return {
        "employee": EmployeeOut.from_orm(e).dict(),
        "profile": {"birth_date": _d(e.birth_date), "age": (today.year - e.birth_date.year - ((today.month, today.day) < (e.birth_date.month, e.birth_date.day))) if e.birth_date else None,
                    "gender": e.gender, "address": e.address, "emergency_name": e.emergency_name, "emergency_phone": e.emergency_phone,
                    "education": e.education, "languages": e.languages, "skills": e.skills, "about": e.about,
                    "medical_book_until": _d(e.medical_book_until),
                    "medical_expired": bool(e.medical_book_until and e.medical_book_until < today),
                    "medical_expiring": bool(e.medical_book_until and 0 <= (e.medical_book_until - today).days <= 30),
                    "source": e.source, "fire_date": _d(e.fire_date), "fire_reason": e.fire_reason,
                    "tenure_days": tenure, "tenure_text": _tenure(tenure)},
        "work_history": [_wh_out(w) for w in e.work_history.all()],
        "documents": [_doc_out(x) for x in e.documents.all()],
        "reviews": [_review_out(r) for r in e.reviews.select_related("reviewer")[:12]],
        "kpi": {"month": m.strftime("%Y-%m"), **kpi.compute(e, m, request.tenant)},
        "kpi_history": [{"month": mm.strftime("%Y-%m"), **{k: v for k, v in kpi.compute(e, mm, request.tenant).items() if k in ("score", "grade")}}
                        for mm in _last_months(m, 6)],
        "feedback": [{"date": _d(f.date), "mood": f.mood, "comment": f.comment} for f in fb],
        "application": {"id": app.pk, "vacancy": app.vacancy.title if app.vacancy else None, "source": app.source,
                        "applied_at": _d(app.created_at), "answers": app.answers} if app else None,
        "criteria": [{"key": k, "label": v} for k, v in REVIEW_CRITERIA],
    }


def _tenure(days: int) -> str:
    if days < 31:
        return f"{days} kun"
    if days < 365:
        return f"{days // 30} oy"
    y, mo = divmod(days // 30, 12)
    return f"{y} yil" + (f" {mo} oy" if mo else "")


def _last_months(m: date, n: int) -> list[date]:
    out = [m]
    for _ in range(n - 1):
        prev = (out[0].replace(day=1) - timedelta(days=1)).replace(day=1)
        out.insert(0, prev)
    return out


@router.put("/employees/{int:eid}/profile", auth=auth)
def update_profile(request, eid: int, data: ProfileIn):
    _guard(request, "hr.edit")
    e = get_object_or_404(Employee, pk=eid)
    if data.gender not in ("", "m", "f"):
        raise HttpError(400, "Jinsi: m yoki f")
    for k, v in data.dict().items():
        if isinstance(v, list):
            v = [str(x).strip() for x in v if str(x).strip()][:20]
        setattr(e, k, v)
    e.save()
    record(request, "update", e, after={"profile": True})
    return employee_profile(request, eid)


class WorkIn(Schema):
    company: str
    position: str = ""
    start: str = ""
    end: str = ""
    reason_left: str = ""
    reference_phone: str = ""
    note: str = ""


@router.post("/employees/{int:eid}/work-history", auth=auth)
def add_work(request, eid: int, data: WorkIn):
    _guard(request, "hr.edit")
    e = get_object_or_404(Employee, pk=eid)
    if not data.company.strip():
        raise HttpError(400, "Ish joyi nomini yozing.")
    w = WorkHistory.objects.create(employee=e, **{k: (v or "").strip() for k, v in data.dict().items()})
    return _wh_out(w)


@router.put("/work-history/{int:wid}", auth=auth)
def update_work(request, wid: int, data: WorkIn):
    _guard(request, "hr.edit")
    w = get_object_or_404(WorkHistory, pk=wid)
    for k, v in data.dict().items():
        setattr(w, k, (v or "").strip())
    w.save()
    return _wh_out(w)


@router.delete("/work-history/{int:wid}", auth=auth)
def delete_work(request, wid: int):
    _guard(request, "hr.edit")
    get_object_or_404(WorkHistory, pk=wid).delete()
    return {"ok": True}


@router.post("/employees/{int:eid}/documents", auth=auth)
def add_document(request, eid: int, title: str = "", kind: str = "other", url: str = "", expires_on: Optional[date] = None,
                 file: Optional[UploadedFile] = File(None)):
    _guard(request, "hr.edit")
    e = get_object_or_404(Employee, pk=eid)
    if kind not in DocKind.values:
        kind = DocKind.OTHER
    if not file and not url.startswith(("http://", "https://")):
        raise HttpError(400, "Fayl yuklang yoki havola (https://…) kiriting.")
    if file and file.size > 15 * 1024 * 1024:
        raise HttpError(400, "Fayl 15 MB dan katta bo'lmasin (katta fayl uchun havola qo'ying).")
    d = EmployeeDocument(employee=e, kind=kind, title=(title or DocKind(kind).label)[:160], url=url if not file else "", expires_on=expires_on)
    if file:
        d.file.save(file.name, file, save=False)
    d.save()
    if kind == DocKind.MEDBOOK and expires_on and (not e.medical_book_until or expires_on > e.medical_book_until):
        e.medical_book_until = expires_on
        e.save(update_fields=["medical_book_until"])
    record(request, "create", d)
    return _doc_out(d)


@router.delete("/documents/{int:did}", auth=auth)
def delete_document(request, did: int):
    _guard(request, "hr.edit")
    get_object_or_404(EmployeeDocument, pk=did).delete()
    return {"ok": True}


class FireIn(Schema):
    date: Optional[date] = None
    reason: str = ""


@router.post("/employees/{int:eid}/fire", auth=auth)
def fire(request, eid: int, data: FireIn):
    """Ishdan bo'shatish: karta arxivga (tarix saqlanadi), tizimga kirish yopiladi."""
    _guard(request, "hr.edit")
    e = get_object_or_404(Employee.objects.select_related("user"), pk=eid)
    if not data.reason.strip():
        raise HttpError(400, "Sababini yozing (ichki ma'lumot).")
    e.is_active, e.fire_date, e.fire_reason = False, data.date or timezone.localdate(), data.reason.strip()[:200]
    e.save()
    if not e.user.is_superuser and not e.user.memberships.filter(role__code="owner").exists():
        e.user.is_active = False
        e.user.save(update_fields=["is_active"])
    record(request, "fire", e, after={"reason": e.fire_reason})
    return {"ok": True}


# ================================================================== BAHOLASH / KPI
class ReviewIn(Schema):
    month: Optional[str] = None
    scores: dict[str, int]
    strengths: str = ""
    improve: str = ""
    goals: str = ""


@router.post("/employees/{int:eid}/reviews", auth=auth)
def add_review(request, eid: int, data: ReviewIn):
    _guard(request, "hr.review")
    e = get_object_or_404(Employee, pk=eid)
    keys = {k for k, _ in REVIEW_CRITERIA}
    sc = {k: int(v) for k, v in (data.scores or {}).items() if k in keys and v}
    if len(sc) < 3:
        raise HttpError(400, "Kamida 3 ta mezonni baholang (1–5).")
    if any(not 1 <= v <= 5 for v in sc.values()):
        raise HttpError(400, "Baho 1 dan 5 gacha.")
    per = _month(data.month)
    r, _ = Review.objects.update_or_create(employee=e, period=per, reviewer=request.auth,
                                           defaults={"scores": sc, "strengths": data.strengths[:300], "improve": data.improve[:300], "goals": data.goals[:300]})
    record(request, "review", e, after={"period": per.isoformat(), "avg": r.average})
    if e.user.telegram_id and data.goals.strip():
        recruit.tg(request.tenant, e.user.telegram_id, f"📊 <b>{per:%m.%Y} oy bahongiz</b>: {r.average} / 5\n"
                                                        + (f"💪 {data.strengths}\n" if data.strengths else "") + f"🎯 Keyingi oy maqsadi: {data.goals}")
    return _review_out(r)


@router.get("/kpi", auth=auth)
def kpi_board(request, month: Optional[str] = None, branch_id: Optional[int] = None):
    _guard(request, "hr.review")
    m = _month(month)
    rows = kpi.leaderboard(m, request.tenant, branch_id)
    scored = [r for r in rows if r["score"] is not None]
    return {"month": m.strftime("%Y-%m"), "rows": rows, "criteria": [{"key": k, "label": v} for k, v in REVIEW_CRITERIA],
            "weights": [{"key": k, "label": kpi.LABELS[k], "weight": w} for k, w in kpi.WEIGHTS.items()],
            "summary": {"avg": round(sum(r["score"] for r in scored) / len(scored), 1) if scored else None,
                        "grades": {g: sum(1 for r in scored if r["grade"] == g) for g in "ABCD"},
                        "risk": sum(1 for r in rows if r["risk"]), "reviewed": sum(1 for r in rows if r["reviewed"]), "total": len(rows),
                        "bonus_total": sum(r["bonus_suggest"] for r in rows)}}


class BonusIn(Schema):
    month: Optional[str] = None
    employee_ids: list[int] = []


@router.post("/kpi/apply-bonus", auth=auth)
def kpi_apply_bonus(request, data: BonusIn):
    """KPI bo'yicha tavsiya bonusni shu oyning QORALAMA oyliklariga yozadi (tasdiqlanganlarga tegmaydi)."""
    _guard(request, "hr.payroll")
    m = _month(data.month)
    n = 0
    for r in kpi.leaderboard(m, request.tenant):
        if data.employee_ids and r["employee_id"] not in data.employee_ids:
            continue
        if not r["bonus_suggest"]:
            continue
        s = Payslip.objects.filter(employee_id=r["employee_id"], period=m, status=PayrollStatus.DRAFT).first()
        if s is None:
            continue
        s.bonus = r["bonus_suggest"]
        s.note = (s.note + f" · KPI {r['grade']} ({r['score']})").strip(" ·")[:200]
        s.compute()
        s.save()
        n += 1
    record(request, "kpi_bonus", model="Payslip", after={"month": m.isoformat(), "count": n})
    return {"updated": n}


# ================================================================== VAKANSIYALAR
class VacancyIn(Schema):
    title: str
    position_id: Optional[int] = None
    branch_id: Optional[int] = None
    role_code: str = "waiter"
    employment: str = "full"
    salary_from: int = 0
    salary_to: int = 0
    salary_note: str = ""
    schedule: str = ""
    summary: str = ""
    requirements: list[str] = []
    duties: list[str] = []
    benefits: list[str] = []
    image_url: str = ""
    video_url: str = ""
    link_url: str = ""
    questions: list[dict] = []
    status: str = VacancyStatus.DRAFT
    responsible_id: Optional[str] = None
    closes_on: Optional[date] = None


def vacancy_out(v: Vacancy, stats: bool = True) -> dict:
    out = {"id": v.pk, "title": v.title, "position_id": v.position_id, "position": v.position.name if v.position_id else None,
           "branch_id": v.branch_id, "branch": v.branch.name if v.branch_id else None, "role_code": v.role_code,
           "employment": v.employment, "employment_label": recruit.EMPLOYMENT.get(v.employment, v.employment),
           "salary_from": v.salary_from, "salary_to": v.salary_to, "salary_note": v.salary_note, "salary_text": recruit.salary_text(v),
           "schedule": v.schedule, "summary": v.summary, "requirements": v.requirements, "duties": v.duties, "benefits": v.benefits,
           "image": v.image_src, "image_url": v.image_url, "video_url": v.video_url, "link_url": v.link_url, "questions": v.questions,
           "status": v.status, "status_label": VacancyStatus(v.status).label, "is_open": recruit.is_open(v),
           "responsible_id": str(v.responsible_id) if v.responsible_id else None,
           "responsible": v.responsible.full_name if v.responsible_id else None, "closes_on": _d(v.closes_on), "views": v.views,
           "created_at": _d(v.created_at)}
    if stats:
        c = dict(v.applications.values_list("stage").annotate(n=Count("id")))
        out["applications"] = sum(c.values())
        out["by_stage"] = c
        out["new"] = c.get(Stage.NEW, 0)
    return out


def _clean_vacancy(data: VacancyIn) -> dict:
    d = data.dict()
    d["title"] = d["title"].strip()
    if not d["title"]:
        raise HttpError(400, "Vakansiya nomini yozing.")
    if d["status"] not in VacancyStatus.values:
        raise HttpError(400, "Noto'g'ri holat.")
    for k in ("image_url", "video_url", "link_url"):
        if d[k] and not d[k].startswith(("http://", "https://")):
            raise HttpError(400, "Havola https:// bilan boshlanishi kerak.")
    for k in ("requirements", "duties", "benefits"):
        d[k] = [str(x).strip() for x in d[k] if str(x).strip()][:20]
    qs = []
    for q in d["questions"][:10]:
        t = str(q.get("text") or "").strip()
        if t:
            qs.append({"text": t[:200], "type": q.get("type") if q.get("type") in ("yesno", "text") else "text",
                       "must": str(q.get("must") or "").strip().lower()[:10]})
    d["questions"] = qs
    if d["salary_to"] and d["salary_from"] and d["salary_to"] < d["salary_from"]:
        raise HttpError(400, "Maosh «gacha» qiymati «dan»dan kichik bo'lmasin.")
    d["responsible_id"] = d.pop("responsible_id") or None
    return d


@router.get("/vacancies", auth=auth)
def list_vacancies(request):
    _guard(request, "hr.recruit")
    from website.views import _bot_link
    out = [vacancy_out(v) for v in Vacancy.objects.select_related("position", "branch", "responsible")]
    for x in out:
        x["public_path"] = f"/vacancies/{x['id']}/"
        x["bot_link"] = _bot_link(request, x["id"])
    return out


@router.post("/vacancies", auth=auth)
def create_vacancy(request, data: VacancyIn):
    _guard(request, "hr.recruit")
    v = Vacancy.objects.create(**_clean_vacancy(data))
    record(request, "create", v)
    return vacancy_out(v)


@router.put("/vacancies/{int:vid}", auth=auth)
def update_vacancy(request, vid: int, data: VacancyIn):
    _guard(request, "hr.recruit")
    v = get_object_or_404(Vacancy, pk=vid)
    for k, val in _clean_vacancy(data).items():
        setattr(v, k, val)
    v.save()
    record(request, "update", v)
    return vacancy_out(v)


@router.post("/vacancies/{int:vid}/image", auth=auth)
def vacancy_image(request, vid: int, file: UploadedFile = File(...)):
    _guard(request, "hr.recruit")
    v = get_object_or_404(Vacancy, pk=vid)
    if not (file.content_type or "").startswith("image/") or file.size > 8 * 1024 * 1024:
        raise HttpError(400, "Rasm (JPG/PNG), 8 MB gacha.")
    v.image.save(file.name, file, save=True)
    return vacancy_out(v)


@router.delete("/vacancies/{int:vid}", auth=auth)
def delete_vacancy(request, vid: int):
    _guard(request, "hr.recruit")
    v = get_object_or_404(Vacancy, pk=vid)
    if v.applications.exists():
        v.status = VacancyStatus.CLOSED
        v.save(update_fields=["status", "updated_at"])
        return {"ok": True, "closed": True}
    v.delete()
    return {"ok": True}


# ================================================================== NOMZODLAR
def app_out(a: Application, full: bool = False) -> dict:
    age = (timezone.localdate().year - a.birth_year) if a.birth_year else None
    out = {"id": a.pk, "vacancy_id": a.vacancy_id, "vacancy": a.vacancy.title if a.vacancy_id else None, "full_name": a.full_name,
           "phone": a.phone, "age": age, "city": a.city, "source": a.source, "stage": a.stage, "stage_label": Stage(a.stage).label,
           "rating": a.rating, "knocked_out": a.knocked_out, "tg": bool(a.tg_chat_id), "tg_username": a.tg_username,
           "photo": _media_url(a.photo), "interview_at": _d(a.interview_at), "interview_place": a.interview_place,
           "created_at": _d(a.created_at), "stage_changed_at": _d(a.stage_changed_at), "employee_id": a.employee_id,
           "experience_short": (a.experience or "")[:120]}
    if full:
        out.update({"experience": a.experience, "work_history": a.work_history, "answers": a.answers, "notes": a.notes,
                    "resume": _media_url(a.resume), "reject_reason": a.reject_reason, "birth_year": a.birth_year,
                    "events": [{"at": _d(ev.at), "kind": ev.kind, "text": ev.text, "actor": ev.actor.full_name if ev.actor_id else None}
                               for ev in a.events.select_related("actor")[:30]]})
    return out


@router.get("/applications", auth=auth)
def list_applications(request, vacancy_id: Optional[int] = None, stage: Optional[str] = None, q: str = ""):
    _guard(request, "hr.recruit")
    qs = Application.objects.select_related("vacancy")
    if vacancy_id:
        qs = qs.filter(vacancy_id=vacancy_id)
    if stage:
        qs = qs.filter(stage=stage)
    if q.strip():
        digits = "".join(ch for ch in q if ch.isdigit())
        cond = Q(full_name__icontains=q.strip())
        if digits:
            cond |= Q(phone__contains=digits)
        qs = qs.filter(cond)
    return [app_out(a) for a in qs[:500]]


@router.get("/applications/{int:aid}", auth=auth)
def get_application(request, aid: int):
    _guard(request, "hr.recruit")
    return app_out(get_object_or_404(Application.objects.select_related("vacancy"), pk=aid), full=True)


class AppIn(Schema):
    vacancy_id: Optional[int] = None
    full_name: str
    phone: str
    birth_year: Optional[int] = None
    city: str = ""
    experience: str = ""
    work_history: list[dict] = []
    source: str = "manual"


@router.post("/applications", auth=auth)
def add_application(request, data: AppIn):
    """Qo'lda nomzod qo'shish (telefon orqali, tanish tavsiyasi)."""
    _guard(request, "hr.recruit")
    v = Vacancy.objects.filter(pk=data.vacancy_id).first() if data.vacancy_id else None
    try:
        a = recruit.create_application(request.tenant, v, full_name=data.full_name, phone=data.phone, experience=data.experience,
                                       work_history=data.work_history, birth_year=data.birth_year, city=data.city,
                                       source=data.source if data.source in ("manual", "referral") else "manual")
    except ValueError as e:
        raise HttpError(400, str(e)) from None
    return app_out(a, full=True)


class PatchIn(Schema):
    rating: Optional[int] = None
    notes: Optional[str] = None


@router.patch("/applications/{int:aid}", auth=auth)
def patch_application(request, aid: int, data: PatchIn):
    _guard(request, "hr.recruit")
    a = get_object_or_404(Application, pk=aid)
    if data.rating is not None:
        a.rating = max(0, min(5, data.rating))
    if data.notes is not None:
        a.notes = data.notes[:3000]
    a.save()
    return app_out(a, full=True)


class StageIn(Schema):
    stage: str
    note: str = ""
    interview_at: Optional[datetime] = None
    place: str = ""
    reason: str = ""
    notify: bool = True


@router.post("/applications/{int:aid}/stage", auth=auth)
def move_application(request, aid: int, data: StageIn):
    _guard(request, "hr.recruit")
    a = get_object_or_404(Application.objects.select_related("vacancy"), pk=aid)
    try:
        recruit.move(request.tenant, a, data.stage, request.auth, note=data.note, interview_at=data.interview_at,
                     place=data.place, reason=data.reason, notify=data.notify)
    except ValueError as e:
        raise HttpError(400, str(e)) from None
    return app_out(a, full=True)


class HireIn(Schema):
    role_code: Optional[str] = None
    branch_id: Optional[int] = None
    position_id: Optional[int] = None
    salary_type: Optional[str] = None
    rate: Optional[int] = None
    hire_date: Optional[date] = None


@router.post("/applications/{int:aid}/hire", auth=auth)
def hire_application(request, aid: int, data: HireIn):
    _guard(request, "hr.recruit")
    require = request.auth.has_perm_code("hr.edit")
    if not require:
        raise HttpError(403, "Xodim qo'shish uchun hr.edit ruxsati kerak.")
    a = get_object_or_404(Application.objects.select_related("vacancy"), pk=aid)
    if a.stage == Stage.HIRED:
        raise HttpError(400, "Bu nomzod allaqachon qabul qilingan.")
    try:
        e = recruit.hire(request.tenant, a, request.auth, **data.dict())
    except ValueError as err:
        raise HttpError(400, str(err)) from None
    record(request, "hire", e, after={"application": a.pk})
    return {"ok": True, "employee_id": e.pk, "application": app_out(a, full=True)}


class MsgIn(Schema):
    text: str


@router.post("/applications/{int:aid}/message", auth=auth)
def message_candidate(request, aid: int, data: MsgIn):
    _guard(request, "hr.recruit")
    a = get_object_or_404(Application, pk=aid)
    if not a.tg_chat_id:
        raise HttpError(400, "Nomzod Telegram orqali ariza bermagan — telefon qiling: " + a.phone)
    if not data.text.strip():
        raise HttpError(400, "Xabar matnini yozing.")
    ok = recruit.tg(request.tenant, a.tg_chat_id, data.text.strip())
    recruit.event(a, "message", f"Xabar: {data.text.strip()[:300]}", request.auth)
    return {"ok": ok}


@router.get("/recruit/stats", auth=auth)
def recruit_stats(request):
    _guard(request, "hr.recruit")
    now = timezone.now()
    m = now - timedelta(days=30)
    apps = Application.objects.all()
    hired = apps.filter(stage=Stage.HIRED, stage_changed_at__gte=m)
    days = [(a.stage_changed_at - a.created_at).days for a in hired]
    return {"open": Vacancy.objects.filter(status=VacancyStatus.OPEN).count(),
            "applications_30d": apps.filter(created_at__gte=m).count(), "new": apps.filter(stage=Stage.NEW).count(),
            "interviews_upcoming": apps.filter(stage__in=[Stage.INTERVIEW, Stage.TRIAL], interview_at__gte=now).count(),
            "hired_30d": len(days), "time_to_hire": round(sum(days) / len(days), 1) if days else None,
            "by_stage": dict(apps.values_list("stage").annotate(n=Count("id"))),
            "by_source": dict(apps.values_list("source").annotate(n=Count("id")))}
