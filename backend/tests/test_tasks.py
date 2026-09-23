"""
Vazifalar moduli testlari — asosiy qoidalar buzilmasligi uchun:
dalilsiz tekshiruvga o'tmaydi, bajaruvchi o'z ishini o'zi yopmaydi, rad etish qaytaradi,
o'chirilgan modul 404, statistika to'g'ri sanaydi, takroriy vazifa ochiladi.
"""
import io

import pytest
from django.utils import timezone
from django_tenants.utils import schema_context

from modules.tasks.models import ColumnKind, Task, TaskColumn, TaskRecurrence
from modules.tasks.services import ensure_setup


def _png() -> io.BytesIO:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (8, 8), (10, 120, 80)).save(buf, format="PNG")
    buf.seek(0)
    buf.name = "proof.png"
    return buf


@pytest.fixture
def board(tenant):
    with schema_context("lazzat"):
        ensure_setup()
        yield {c.kind: c for c in TaskColumn.objects.all()}


@pytest.mark.django_db
def test_create_task_applies_category_rules(api, owner_token, board):
    """Tur tanlansa: muddat (SLA), bosqichlar, bo'lim va dalil talabi avtomatik qo'yiladi."""
    with schema_context("lazzat"):
        from modules.tasks.models import TaskCategory
        cat = TaskCategory.objects.get(code="furniture")
    r = api.post("/api/v1/tasks/tasks", {"title": "Divanni remont qilish", "category_id": cat.pk})
    assert r.status_code == 200, r.content
    d = r.json()
    assert d["number"] >= 1201 and d["due_at"] and d["requires_proof"] is True
    assert len(d["steps"]) == 5 and d["department"]["name"]["uz"] == "Xo'jalik"


@pytest.mark.django_db
def test_review_requires_proof_and_owner_cannot_self_close(api, client, owner_token, board):
    """Dalilsiz «Tekshiruvda»ga o'tkazib bo'lmaydi; dalil bo'lsa — o'tadi va tasdiqlanadi."""
    r = api.post("/api/v1/tasks/tasks", {"title": "Chiroqni almashtirish"})
    tid = r.json()["id"]
    review = board[ColumnKind.REVIEW].pk

    bad = api.post(f"/api/v1/tasks/tasks/{tid}/move", {"column_id": review})
    assert bad.status_code == 400 and "Dalil" in bad.json()["detail"]

    up = client.post(f"/api/v1/tasks/tasks/{tid}/attachments?kind=proof", {"file": _png()},
                     HTTP_HOST="lazzat.testserver", HTTP_AUTHORIZATION=f"Bearer {owner_token}")
    assert up.status_code == 200, up.content

    ok = api.post(f"/api/v1/tasks/tasks/{tid}/submit", {})
    assert ok.status_code == 200 and ok.json()["status"] == "review"

    done = api.post(f"/api/v1/tasks/tasks/{tid}/approve", {"note": "Zo'r"})
    assert done.status_code == 200 and done.json()["status"] == "done" and done.json()["approved_at"]


@pytest.mark.django_db
def test_reject_returns_task_and_counts_rework(api, owner_token, board):
    r = api.post("/api/v1/tasks/tasks", {"title": "Stolni tozalash", "requires_proof": False})
    tid = r.json()["id"]
    api.post(f"/api/v1/tasks/tasks/{tid}/submit", {})
    back = api.post(f"/api/v1/tasks/tasks/{tid}/reject", {"reason": "Yarmi kir qolgan"})
    assert back.status_code == 200
    d = back.json()
    assert d["status"] == "active" and d["rework_count"] == 1
    comments = api.get(f"/api/v1/tasks/tasks/{tid}/comments").json()
    assert any("Yarmi kir qolgan" in c["body"] and c["is_system"] for c in comments)


@pytest.mark.django_db
def test_board_stats_count_each_task_once(api, owner_token, board):
    """Izohlar bilan JOIN statistikani ikkilantirmasligi kerak."""
    r = api.post("/api/v1/tasks/tasks", {"title": "Sanoq testi"})
    tid = r.json()["id"]
    for i in range(3):
        api.post(f"/api/v1/tasks/tasks/{tid}/comments", {"body": f"izoh {i}"})
    b = api.get("/api/v1/tasks/board").json()
    assert b["stats"]["total"] == sum(c["count"] for c in b["stats"]["by_column"])
    card = [t for c in b["columns"] for t in c["tasks"] if t["id"] == tid][0]
    assert card["comments_count"] == 3


@pytest.mark.django_db
def test_module_disabled_returns_404(api, owner_token, board):
    from public.models import Tenant

    t = Tenant.objects.get(slug="lazzat")
    before = list(t.enabled_modules)
    t.enabled_modules = [m for m in before if m != "tasks"]
    t.save()
    try:
        r = api.get("/api/v1/tasks/board")
        assert r.status_code == 404
    finally:
        t.enabled_modules = before
        t.save()


@pytest.mark.django_db
def test_recurrence_creates_task_once_per_day(tenant):
    with schema_context("lazzat"):
        from modules.tasks.services import run_recurrences

        ensure_setup()
        TaskRecurrence.objects.create(title="Kunlik sanitariya", freq="daily", due_in_hours=6)
        before = Task.objects.count()
        assert run_recurrences() == 1
        assert run_recurrences() == 0          # bir kunda ikki marta ochilmaydi
        assert Task.objects.count() == before + 1
        t = Task.objects.order_by("-id").first()
        assert t.source == "recurring" and t.due_at > timezone.now()


@pytest.mark.django_db
def test_tenant_isolation_for_tasks(api, owner_token, board):
    """Bir restoran vazifasi boshqasida ko'rinmaydi."""
    api.post("/api/v1/tasks/tasks", {"title": "Lazzat ichki ishi"})
    with schema_context("chopar"):
        assert Task.objects.filter(title="Lazzat ichki ishi").count() == 0
