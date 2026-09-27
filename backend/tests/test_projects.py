"""
Loyihalar: shablondan yaratish (bosqich/vazifa, muddatlar loyiha davomiyligiga moslanadi), vazifa berish → jamoaga qo'shiladi va
xabar hodisasi, kanban surish → bosqich avtomatik yakunlanadi, xavf/kechikish, kirish huquqi (xodim faqat o'z loyihasini
va o'z vazifasini), kalendar, byudjet, hujjat-havola, izoh va bildirishnomalar.
"""
from datetime import timedelta

import pytest
from django.utils import timezone
from django_tenants.utils import schema_context


@pytest.fixture
def pm(tenant):
    from public.services import set_modules
    with schema_context("public"):
        set_modules(tenant, sorted({*tenant.enabled_modules, "projects"}))
    with schema_context("lazzat"):
        from modules.projects.models import Project
        Project.objects.all().delete()
    yield


def _staff(client, phone, role="cook"):
    from core.auth import issue_token
    from core.models import Membership, Role, User
    with schema_context("lazzat"):
        u = User.objects.filter(phone=f"+{phone}").first() or User.objects.create_user(phone, full_name=f"Xodim {phone[-2:]}")
        Membership.objects.get_or_create(user=u, role=Role.objects.get(code=role))
        tok = issue_token(u, "lazzat")
    h = {"HTTP_HOST": "lazzat.testserver", "HTTP_AUTHORIZATION": f"Bearer {tok}"}

    class C:
        uid = str(u.pk)

        def get(self, url):
            return client.get(url, **h)

        def post(self, url, data=None):
            return client.post(url, data=data, content_type="application/json", **h)

        def put(self, url, data=None):
            return client.put(url, data=data, content_type="application/json", **h)
    return C()


@pytest.mark.django_db
def test_create_from_template(api, pm):
    start = timezone.localdate()
    p = api.post("/api/v1/projects/", {"template_key": "branch_open", "start": start.isoformat(),
                                        "due": (start + timedelta(days=150)).isoformat(), "budget": 300_000_000}).json()
    assert p["title"] == "Yangi filial ochish" and p["category"]["code"] == "branch" and p["status"] == "active"
    assert len(p["milestones"]) == 6 and p["tasks_total"] == 21
    assert p["milestones"][-1]["due"] == (start + timedelta(days=150)).isoformat()      # 75 kunlik shablon 150 kunga cho'zildi
    assert p["members"][0]["role"] == "lead" and p["can_edit"] is True
    first = next(t for t in p["tasks"] if t["check_total"])
    assert first["check_total"] == 3 and first["check_done"] == 0
    assert api.post("/api/v1/projects/", {"title": ""}).status_code == 400
    assert api.post("/api/v1/projects/", {"title": "X", "start": "2026-10-10", "due": "2026-10-01"}).status_code == 400
    blank = api.post("/api/v1/projects/", {"title": "Bo'sh", "category": "it"}).json()
    assert blank["status"] == "plan" and blank["tasks_total"] == 0


@pytest.mark.django_db
def test_task_flow_milestone_and_events(api, pm, client, monkeypatch):
    from core import events
    sent = []
    monkeypatch.setattr(events, "_handlers", {**events._handlers, "projects.task_assigned": [lambda p: sent.append(p)]})
    worker = _staff(client, "998935550101")
    p = api.post("/api/v1/projects/", {"title": "Ta'mir", "category": "renovation"}).json()
    p = api.post(f"/api/v1/projects/{p['id']}/milestones", {"title": "Tayyorgarlik", "due": timezone.localdate().isoformat()}).json()
    ms = p["milestones"][0]["id"]
    t1 = api.post(f"/api/v1/projects/{p['id']}/tasks", {"title": "Smeta", "milestone_id": ms, "assignee_id": worker.uid,
                                                          "checklist": [{"text": "3 ta smeta"}, {"text": ""}]}).json()
    t2 = api.post(f"/api/v1/projects/{p['id']}/tasks", {"title": "Pudratchi", "milestone_id": ms}).json()
    assert t1["assignee"]["id"] == worker.uid and t1["check_total"] == 1
    assert sent and sent[0]["assignee_id"] == worker.uid
    d = api.get(f"/api/v1/projects/{p['id']}").json()
    assert any(m["user"]["id"] == worker.uid for m in d["members"])                     # mas'ul jamoaga qo'shildi
    api.post(f"/api/v1/projects/tasks/{t1['id']}/move", {"status": "done", "order": [t1["id"]]})
    d = api.get(f"/api/v1/projects/{p['id']}").json()
    assert d["progress"] == 50 and d["status"] == "active" and not d["milestones"][0]["done"]
    assert next(t for t in d["tasks"] if t["id"] == t1["id"])["check_done"] == 1       # bajarildi → checklist ham yopildi
    api.post(f"/api/v1/projects/tasks/{t2['id']}/move", {"status": "done"})
    d = api.get(f"/api/v1/projects/{p['id']}").json()
    assert d["progress"] == 100 and d["milestones"][0]["done"] and d["milestones_done"] == 1
    assert any(a["kind"] == "milestone" for a in d["activity"])
    api.post(f"/api/v1/projects/tasks/{t2['id']}/move", {"status": "doing"})
    assert not api.get(f"/api/v1/projects/{p['id']}").json()["milestones"][0]["done"]  # qayta ochildi


@pytest.mark.django_db
def test_permissions(api, pm, client):
    worker = _staff(client, "998935550202")
    other = _staff(client, "998935550303")
    p = api.post("/api/v1/projects/", {"title": "Menyu", "category": "menu"}).json()
    secret = api.post("/api/v1/projects/", {"title": "Maxfiy", "category": "other"}).json()
    mine = api.post(f"/api/v1/projects/{p['id']}/tasks", {"title": "Retsept", "assignee_id": worker.uid}).json()
    theirs = api.post(f"/api/v1/projects/{p['id']}/tasks", {"title": "Foto", "assignee_id": other.uid}).json()
    assert worker.post("/api/v1/projects/", {"title": "Men ham"}).status_code == 403
    assert [x["id"] for x in worker.get("/api/v1/projects/list").json()] == [p["id"]]
    assert worker.get(f"/api/v1/projects/{secret['id']}").status_code == 403
    d = worker.get(f"/api/v1/projects/{p['id']}").json()
    assert d["can_edit"] is False
    assert worker.post(f"/api/v1/projects/tasks/{mine['id']}/move", {"status": "doing"}).status_code == 200
    assert worker.post(f"/api/v1/projects/tasks/{theirs['id']}/move", {"status": "doing"}).status_code == 403
    r = worker.put(f"/api/v1/projects/tasks/{mine['id']}", {"title": "Boshqa nom", "status": "review", "checklist": [{"text": "a", "done": True}]}).json()
    assert r["title"] == "Retsept" and r["status"] == "review" and r["check_done"] == 1   # nomni faqat rahbar o'zgartiradi
    assert worker.put(f"/api/v1/projects/{p['id']}", {"title": "X"}).status_code == 403
    assert worker.post(f"/api/v1/projects/{p['id']}/comments", {"text": "Tayyor!"}).status_code == 200
    ks = worker.get("/api/v1/projects/tasks").json()
    assert {t["id"]: t["can_move"] for t in ks} == {mine["id"]: True, theirs["id"]: False}
    feed = api.get("/api/v1/projects/feed").json()
    assert feed[0]["kind"] == "comment" and feed[0]["text"] == "Tayyor!"


@pytest.mark.django_db
def test_health_calendar_budget_files(api, pm):
    today = timezone.localdate()
    p = api.post("/api/v1/projects/", {"title": "Aksiya", "category": "marketing", "budget": 1_000_000,
                                        "start": (today - timedelta(days=20)).isoformat(), "due": (today + timedelta(days=10)).isoformat()}).json()
    for k in range(4):
        api.post(f"/api/v1/projects/{p['id']}/tasks", {"title": f"Ish {k}", "due": (today - timedelta(days=5 - k)).isoformat()})
    d = api.get(f"/api/v1/projects/{p['id']}").json()
    assert d["planned_progress"] == 100 and d["health"] == "risk" and d["overdue"] == 4
    late = api.post("/api/v1/projects/", {"title": "Eski", "category": "other", "start": (today - timedelta(days=30)).isoformat(),
                                           "due": (today - timedelta(days=1)).isoformat()}).json()
    api.post(f"/api/v1/projects/{late['id']}/status", {"status": "active"})
    assert api.get(f"/api/v1/projects/{late['id']}").json()["health"] == "late"
    d = api.post(f"/api/v1/projects/{p['id']}/expenses", {"amount": 1_200_000, "note": "Reklama"}).json()
    assert d["spent"] == 1_200_000 and d["budget_percent"] == 120
    assert any("Byudjetdan oshdi" in a["text"] for a in d["activity"])
    assert api.post(f"/api/v1/projects/{p['id']}/links", {"title": "Dizayn", "url": "ftp://x"}).status_code == 400
    f = api.post(f"/api/v1/projects/{p['id']}/links", {"title": "Dizayn", "url": "https://figma.com/x"}).json()
    assert f["is_link"] and f["url"] == "https://figma.com/x"
    c = api.get(f"/api/v1/projects/calendar?month={today:%Y-%m}").json()
    due = (today + timedelta(days=10))
    if due.month == today.month:
        assert any(e["type"] == "due" and e["project_id"] == p["id"] for e in c["events"])
    assert c["days"] >= 28 and 0 <= c["first_weekday"] <= 6
    o = api.get("/api/v1/projects/overview").json()
    assert o["kpis"]["risk"] >= 2 and o["kpis"]["overdue_tasks"] >= 4
    assert api.get("/api/v1/projects/calendar?month=2026-13").status_code == 400
    api.post(f"/api/v1/projects/{p['id']}/status", {"status": "done"})
    assert api.get(f"/api/v1/projects/{p['id']}").json()["progress"] == 100


@pytest.mark.django_db
def test_module_disabled(api, pm, tenant):
    from public.services import set_modules
    with schema_context("public"):
        set_modules(tenant, [m for m in tenant.enabled_modules if m != "projects"])
    assert api.get("/api/v1/projects/overview").status_code in (403, 404)
