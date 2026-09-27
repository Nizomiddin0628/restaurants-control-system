"""Bo'lim panellari: har bo'lim ko'rsatkichlari va dashboard vidjetlari xatosiz qaytadi (xato bo'lsa log'da ERROR chiqadi)."""
import logging

import pytest

CODES = ["sales", "menu", "stock", "team", "training", "work", "finance", "settings"]


@pytest.mark.django_db
def test_sections_and_widgets(api, tenant, caplog):
    from django_tenants.utils import schema_context

    from public.services import set_modules
    with schema_context("public"):
        set_modules(tenant, sorted({*tenant.enabled_modules, "pos", "inventory", "procurement", "hr", "kds", "tables", "reservations",
                                    "crm", "finance", "tasks", "projects", "training", "catalog", "ops"}))
    caplog.set_level(logging.ERROR)
    s = api.get("/api/v1/dashboard/sections")
    assert s.status_code == 200 and "settings" in s.json()
    for code in CODES:
        for days in (1, 7, 30):
            r = api.get(f"/api/v1/dashboard/section/{code}?days={days}")
            assert r.status_code == 200, code
            body = r.json()
            assert body["code"] == code and isinstance(body["widgets"], list)
            for w in body["widgets"]:
                assert w["type"] in {"chart", "rank", "list", "donut", "table"} and w["title"]
    errs = [r for r in caplog.records if r.levelno >= logging.ERROR and ("bo'lim" in r.getMessage())]
    assert not errs, [e.getMessage() for e in errs]
