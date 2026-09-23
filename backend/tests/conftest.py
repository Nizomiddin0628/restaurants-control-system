"""
Testlar uchun tenant fixture'lari. django-tenants: test bazasi yaratiladi, public migratsiya, so'ng tenant sxemasi.
Talab: ishlaydigan PostgreSQL (docker compose up db).
"""
import pytest
from django_tenants.utils import schema_context


@pytest.fixture(scope="session")
def django_db_setup(django_db_setup, django_db_blocker):
    from public.models import Domain, Tenant
    from public.services import create_tenant

    with django_db_blocker.unblock():
        public = Tenant(schema_name="public", name="Platforma", slug="public")
        public.save()
        Domain.objects.create(tenant=public, domain="testserver", is_primary=True)
        create_tenant(name="Lazzat", slug="lazzat", owner_phone="998901234567", preset="fast_food", domain="lazzat.testserver")
        create_tenant(name="Chopar", slug="chopar", owner_phone="998907654321", preset="cafe", domain="chopar.testserver")


@pytest.fixture
def tenant():
    from public.models import Tenant
    return Tenant.objects.get(slug="lazzat")


@pytest.fixture
def other_tenant():
    from public.models import Tenant
    return Tenant.objects.get(slug="chopar")


@pytest.fixture
def owner_token(tenant):
    from core.auth import issue_token
    from core.models import User
    with schema_context(tenant.schema_name):
        u = User.objects.get(phone="+998901234567")
        return issue_token(u, tenant.schema_name)


@pytest.fixture
def api(client, owner_token):
    """lazzat.testserver domeniga egasi tokeni bilan so'rov yuboradigan mijoz."""
    class Api:
        def __init__(self):
            self.h = {"HTTP_HOST": "lazzat.testserver", "HTTP_AUTHORIZATION": f"Bearer {owner_token}"}

        def get(self, url, **kw):
            return client.get(url, **self.h, **kw)

        def post(self, url, data=None, **kw):
            return client.post(url, data=data, content_type="application/json", **self.h, **kw)

        def put(self, url, data=None, **kw):
            return client.put(url, data=data, content_type="application/json", **self.h, **kw)

        def patch(self, url, data=None, **kw):
            return client.patch(url, data=data, content_type="application/json", **self.h, **kw)

        def delete(self, url, **kw):
            return client.delete(url, **self.h, **kw)
    return Api()
