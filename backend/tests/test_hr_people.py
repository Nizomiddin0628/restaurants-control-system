"""
HR (2-qism): vakansiya → saytdan / Telegramdan ariza (majburiy savol) → bosqichlar (suhbat vaqti majburiy) →
qabul (xodim kartasi + ish tarixi) → profil, hujjat, baho → KPI reytingi va bonus → smenadan keyingi kayfiyat.
"""
import json
import os
from datetime import timedelta

import pytest
from django.utils import timezone
from django_tenants.utils import schema_context

H = {"HTTP_HOST": "lazzat.testserver"}


@pytest.fixture
def hr(tenant):
    from public.services import set_modules
    with schema_context("public"):
        set_modules(tenant, sorted({*tenant.enabled_modules, "hr", "telegram", "pos", "training", "tasks"}))
    with schema_context("lazzat"):
        from modules.hr.models import Application, Vacancy
        Application.objects.all().delete()
        Vacancy.objects.all().delete()
    yield


def _vac(api, **kw):
    body = {"title": "Ofitsiant", "role_code": "waiter", "salary_from": 3_000_000, "salary_to": 4_500_000, "schedule": "2/2, 10:00–23:00",
            "requirements": ["18 yoshdan katta", "Rus tilini bilish — afzallik"], "duties": ["Mehmonni kutib olish"], "benefits": ["Bepul tushlik"],
            "video_url": "https://www.youtube.com/watch?v=jBe8e69ypcc", "status": "open",
            "questions": [{"text": "Kechki smenada ishlay olasizmi?", "type": "yesno", "must": "ha"}, {"text": "Qachon ishga chiqa olasiz?", "type": "text"}]}
    body.update(kw)
    r = api.post("/api/v1/hr/vacancies", body)
    assert r.status_code == 200, r.content
    return r.json()


@pytest.mark.django_db
def test_vacancy_public_pages_and_site_application(api, client, hr):
    v = _vac(api)
    assert v["salary_text"].startswith("3 000 000 – 4 500 000") and v["is_open"]
    draft = _vac(api, title="Yashirin", status="draft")
    lst = client.get("/vacancies/", **H)
    assert lst.status_code == 200 and "Ofitsiant" in lst.content.decode() and "Yashirin" not in lst.content.decode()
    page = client.get(f"/vacancies/{v['id']}/", **H)
    assert page.status_code == 200 and "youtube.com/embed/jBe8e69ypcc" in page.content.decode()
    assert client.get(f"/vacancies/{draft['id']}/", **H).status_code == 200            # yopiq — «yopilgan» xabari
    r = client.post(f"/vacancies/{v['id']}/", {"full_name": "Bobur Aliyev", "phone": "90 123 45 67", "birth_year": "2001",
                                               "q0": "Yo'q", "q1": "Dushanbadan", "prev_company": "Rayhon", "prev_position": "ofitsiant"}, **H)
    assert r.status_code == 200 and "qabul qilindi" in r.content.decode()
    apps = api.get("/api/v1/hr/applications").json()
    assert len(apps) == 1 and apps[0]["phone"] == "+998901234567"
    a = api.get(f"/api/v1/hr/applications/{apps[0]['id']}").json()
    assert a["knocked_out"] is True and a["answers"][0]["ok"] is False and a["work_history"][0]["company"] == "Rayhon"
    # takror ariza — ikkinchi karta ochilmaydi
    client.post(f"/vacancies/{v['id']}/", {"full_name": "Bobur Aliyev", "phone": "+998901234567", "q0": "Ha"}, **H)
    assert len(api.get("/api/v1/hr/applications").json()) == 1


@pytest.mark.django_db
def test_telegram_application_flow(client, api, hr):
    v = _vac(api)

    def hook(text=None, contact=None):
        m = {"message_id": 1, "chat": {"id": 7700, "type": "private"}, "from": {"id": 7700, "first_name": "Laylo", "username": "laylo_uz"}}
        if text is not None:
            m["text"] = text
        if contact:
            m["contact"] = contact
        return client.post("/api/v1/telegram/webhook", data=json.dumps({"update_id": 1, "message": m}), content_type="application/json",
                           HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN=os.environ.get("TELEGRAM_WEBHOOK_SECRET", "restopos"), **H)
    for step in [f"/start job_{v['id']}", "Laylo Karimova"]:
        assert hook(step).status_code == 200
    hook(contact={"phone_number": "998935550077", "user_id": 7700})
    for step in ["1998", "Ha", "Ertaga", "Kafe'da 1 yil ishlaganman", "«Oqtepa», kassir, 1 yil", "✅ Arizani yuborish"]:
        hook(step)
    with schema_context("lazzat"):
        from modules.hr.models import Application
        a = Application.objects.get(phone="+998935550077")
        assert a.source == "telegram" and a.tg_chat_id == 7700 and a.birth_year == 1998 and not a.knocked_out
        assert a.answers[1]["a"] == "Ertaga" and a.work_history[0]["company"].startswith("«Oqtepa»")


@pytest.mark.django_db
def test_stages_and_hire_creates_employee(api, hr):
    v = _vac(api)
    a = api.post("/api/v1/hr/applications", {"vacancy_id": v["id"], "full_name": "Sardor Nazarov", "phone": "+998935550088", "birth_year": 1997,
                                             "work_history": [{"company": "Evos", "position": "kassir", "years": "2021–2023"}]}).json()
    assert api.post(f"/api/v1/hr/applications/{a['id']}/stage", {"stage": "interview"}).status_code == 400      # vaqt majburiy
    at = (timezone.now() + timedelta(days=1)).isoformat()
    r = api.post(f"/api/v1/hr/applications/{a['id']}/stage", {"stage": "interview", "interview_at": at, "place": "Chilonzor filiali"})
    assert r.status_code == 200 and r.json()["stage"] == "interview"
    assert api.post(f"/api/v1/hr/applications/{a['id']}/stage", {"stage": "rejected"}).status_code == 400       # sabab majburiy
    h = api.post(f"/api/v1/hr/applications/{a['id']}/hire", {"rate": 3_500_000})
    assert h.status_code == 200, h.content
    eid = h.json()["employee_id"]
    p = api.get(f"/api/v1/hr/employees/{eid}/profile").json()
    assert p["employee"]["role_code"] == "waiter" and p["employee"]["rate"] == 3_500_000
    assert p["work_history"][0]["company"] == "Evos" and p["application"]["vacancy"] == "Ofitsiant" and p["profile"]["source"] == "vakansiya"
    assert api.post(f"/api/v1/hr/applications/{a['id']}/hire", {}).status_code == 400                           # ikki marta emas


@pytest.mark.django_db
def test_profile_documents_review_and_kpi(api, hr):
    e = api.post("/api/v1/hr/employees", {"full_name": "KPI Kassir", "phone": "+998935550099", "role_code": "cashier", "salary_type": "monthly", "rate": 4_000_000}).json()
    soon = (timezone.localdate() + timedelta(days=10)).isoformat()
    r = api.put(f"/api/v1/hr/employees/{e['id']}/profile", {"birth_date": "1995-05-20", "education": "Oshpazlik kolleji", "languages": ["o'zbek", "rus"],
                                                            "skills": ["kassa"], "medical_book_until": soon})
    assert r.status_code == 200 and r.json()["profile"]["medical_expiring"] is True and r.json()["profile"]["age"] >= 30
    assert api.post(f"/api/v1/hr/employees/{e['id']}/work-history", {"company": "Safia", "position": "kassir", "start": "2020", "end": "2023"}).status_code == 200
    d = api.post(f"/api/v1/hr/employees/{e['id']}/documents?title=Shartnoma&kind=contract&url=https://drive.google.com/file/d/abc/view")
    assert d.status_code == 200 and d.json()["kind_label"] == "Mehnat shartnomasi"
    assert api.post(f"/api/v1/hr/employees/{e['id']}/documents?title=x").status_code == 400
    assert api.post(f"/api/v1/hr/employees/{e['id']}/reviews", {"scores": {"discipline": 5}}).status_code == 400     # kamida 3 mezon
    rv = api.post(f"/api/v1/hr/employees/{e['id']}/reviews", {"scores": {"discipline": 5, "quality": 4, "speed": 4, "service": 5}, "goals": "O'rtacha chekni oshirish"})
    assert rv.status_code == 200 and rv.json()["average"] == 4.5
    # davomat: 2 smena reja, 2 marta keldi (biri kechikib)
    with schema_context("lazzat"):
        from modules.hr.models import Attendance, Employee, ShiftPlan
        emp = Employee.objects.get(pk=e["id"])
        today = timezone.localdate()
        for k, late in ((1, 0), (2, 25)):
            d0 = today - timedelta(days=k) if today.day > 2 else today
            ShiftPlan.objects.get_or_create(employee=emp, date=d0, start="09:00", defaults={"end": "18:00"})
            Attendance.objects.create(employee=emp, check_in=timezone.now() - timedelta(days=k if today.day > 2 else 0, hours=1), late_minutes=late)
    board = api.get("/api/v1/hr/kpi").json()
    row = next(x for x in board["rows"] if x["employee_id"] == e["id"])
    assert row["score"] is not None and row["grade"] in "ABCD" and "review" in row["parts"] and "punctuality" in row["parts"]
    assert row["parts"]["review"]["value"] == 88                                                             # (4.5−1)/4
    api.post("/api/v1/hr/payroll/compute")
    res = api.post("/api/v1/hr/kpi/apply-bonus", {"employee_ids": [e["id"]]}).json()
    assert res["updated"] in (0, 1)


@pytest.mark.django_db
def test_shift_mood_callback(client, api, hr):
    e = api.post("/api/v1/hr/employees", {"full_name": "Mood Oshpaz", "phone": "+998935550111", "role_code": "cook", "telegram_id": 8800}).json()
    with schema_context("lazzat"):
        from modules.hr.models import Attendance, ShiftFeedback
        a = Attendance.objects.create(employee_id=e["id"], check_out=timezone.now())
    cq = {"update_id": 5, "callback_query": {"id": "cb1", "data": f"mood:{a.pk}:2", "from": {"id": 8800}, "message": {"chat": {"id": 8800}}}}
    r = client.post("/api/v1/telegram/webhook", data=json.dumps(cq), content_type="application/json",
                    HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN=os.environ.get("TELEGRAM_WEBHOOK_SECRET", "restopos"), **H)
    assert r.status_code == 200
    with schema_context("lazzat"):
        assert ShiftFeedback.objects.get(attendance=a).mood == 2
    # boshqa odam bu tugmani bosa olmaydi
    cq["callback_query"]["from"] = {"id": 9999}
    cq["callback_query"]["message"]["chat"]["id"] = 9999
    cq["callback_query"]["data"] = f"mood:{a.pk}:4"
    client.post("/api/v1/telegram/webhook", data=json.dumps(cq), content_type="application/json",
                HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN=os.environ.get("TELEGRAM_WEBHOOK_SECRET", "restopos"), **H)
    with schema_context("lazzat"):
        assert ShiftFeedback.objects.get(attendance=a).mood == 2


@pytest.mark.django_db
def test_demo_seed_and_admin_endpoints(api, client, hr):
    api.post("/api/v1/hr/employees", {"full_name": "Demo Ofitsiant", "phone": "+998935550222", "role_code": "waiter", "salary_type": "monthly", "rate": 4_000_000})
    with schema_context("lazzat"):
        from modules.hr.demo import seed_demo_hr, seed_demo_recruit_people
        seed_demo_hr()
        r = seed_demo_recruit_people()
    assert r["vacancies"] == 4 and r["applications"] >= 17, r
    vs = api.get("/api/v1/hr/vacancies").json()
    assert all(v["public_path"].startswith("/vacancies/") for v in vs) and sum(v["applications"] for v in vs) >= 17
    assert sum(1 for v in vs if v["is_open"]) == 3
    st = api.get("/api/v1/hr/recruit/stats").json()
    assert st["open"] == 3 and st["by_stage"]["rejected"] == 3
    board = api.get("/api/v1/hr/kpi").json()
    assert r["profiles"] >= 1 and board["summary"]["reviewed"] >= 1 and any(x["score"] is not None for x in board["rows"])
    eid = board["rows"][0]["employee_id"]
    p = api.get(f"/api/v1/hr/employees/{eid}/profile").json()
    assert p["work_history"] and p["documents"] and len(p["kpi_history"]) == 6
    page = client.get("/vacancies/", **H).content.decode()
    assert "Oshpaz yordamchisi" in page and "Kuryer" not in page
