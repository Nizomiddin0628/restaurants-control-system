"""Profil rasmi: xodim o'ziga qo'yadi (400×400 ga kichrayadi), egasi boshqalarga qo'yadi, oddiy xodim boshqaga qo'ya olmaydi."""
import io

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django_tenants.utils import schema_context

H = {"HTTP_HOST": "lazzat.testserver"}


def _png(w=1200, h=800):
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (w, h), (200, 80, 40)).save(buf, format="PNG")
    return SimpleUploadedFile("men.png", buf.getvalue(), content_type="image/png")


@pytest.fixture
def cashier(tenant):
    with schema_context("lazzat"):
        from core.auth import issue_token
        from core.models import Membership, Role, User
        role, _ = Role.objects.get_or_create(code="cashier", defaults={"name": "Kassir", "permissions": ["pos.sell"]})
        u, _ = User.objects.get_or_create(phone="+998900000333", defaults={"full_name": "Kassir Test"})
        Membership.objects.get_or_create(user=u, role=role)
        return u, {**H, "HTTP_AUTHORIZATION": f"Bearer {issue_token(u, 'lazzat')}"}


@pytest.mark.django_db
def test_user_sets_own_avatar_and_it_is_resized(client, cashier):
    u, h = cashier
    r = client.post("/api/v1/me/avatar", {"file": _png()}, **h)
    assert r.status_code == 200, r.content
    assert r.json()["avatar"]
    with schema_context("lazzat"):
        from PIL import Image
        u.refresh_from_db()
        with u.avatar.open("rb") as f:
            assert Image.open(f).size == (400, 400)
    assert client.delete("/api/v1/me/avatar", **h).json()["avatar"] is None


@pytest.mark.django_db
def test_bad_file_rejected(client, cashier):
    _, h = cashier
    bad = SimpleUploadedFile("x.png", b"not an image", content_type="image/png")
    assert client.post("/api/v1/me/avatar", {"file": bad}, **h).status_code == 400
    pdf = SimpleUploadedFile("x.pdf", b"%PDF", content_type="application/pdf")
    assert client.post("/api/v1/me/avatar", {"file": pdf}, **h).status_code == 400


@pytest.mark.django_db
def test_owner_sets_others_avatar_cashier_cannot(client, api, cashier, owner_token):
    u, h = cashier
    r = client.post(f"/api/v1/users/{u.pk}/avatar", {"file": _png()}, **{**H, "HTTP_AUTHORIZATION": f"Bearer {owner_token}"})
    assert r.status_code == 200 and r.json()["avatar"], r.content
    with schema_context("lazzat"):
        from core.models import User
        owner = User.objects.get(phone="+998901234567")
    assert client.post(f"/api/v1/users/{owner.pk}/avatar", {"file": _png()}, **h).status_code == 403
