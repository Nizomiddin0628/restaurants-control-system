"""
Bayram va ob-havo prognozi: tizim bayramlari (bir marta, o'chirilgani qaytmaydi), xarid rejasi (tarix × hafta kuni ×
bayram), ogohlantirish → bitta vazifa, o'tgan bayramning haqiqiy o'sishi, ob-havo (Open-Meteo, internet yo'q — xato
emas), boshqaruv paneli bloki, validatsiya, modul o'chsa 404.
"""
from datetime import date, datetime, time, timedelta

import pytest
from django.utils import timezone
from django_tenants.utils import schema_context

H = {"HTTP_HOST": "lazzat.testserver"}


def _offline(url):
    raise OSError("testda internet yo'q")


@pytest.fixture
def fc(tenant, monkeypatch):
    from modules.forecast import weather
    from public.services import set_modules
    monkeypatch.setattr(weather, "_http_get", _offline)                          # testlar internetga chiqmaydi
    with schema_context("public"):
        set_modules(tenant, sorted({*tenant.enabled_modules, "forecast", "inventory", "pos", "tasks"}))
        mods = dict(tenant.settings.get("modules") or {})
        mods["forecast"] = {"history_days": 28, "purchase_lead_days": 2, "create_task": True}
        tenant.settings = {**tenant.settings, "modules": mods}
        tenant.save()
    with schema_context("lazzat"):
        from django.core.cache import cache

        from modules.catalog.models import Category, Product
        from modules.forecast.models import Holiday, WeatherDay
        from modules.inventory.models import Ingredient, Recipe, RecipeLine
        from modules.pos.models import Order, OrderItem, OrderStatus
        cache.clear()
        from modules.forecast import services
        Holiday.objects.all().delete()
        services.ensure_holidays()
        Holiday.objects.update(is_active=False)                                   # tizim bayramlari sanaga bog'liq — o'chiramiz
        WeatherDay.objects.all().delete()
        Order.objects.all().delete()
        Ingredient.objects.update(is_active=False)
        cat, _ = Category.objects.get_or_create(name={"uz": "FC test", "ru": "", "en": ""})
        p = Product.objects.create(category=cat, name={"uz": "FC osh", "ru": "", "en": ""}, price=10000)
        ing = Ingredient.objects.create(name={"uz": "FC go'sht", "ru": "", "en": ""}, unit="kg", price=50000, stock=5, min_stock=2)
        rc = Recipe.objects.create(product=p, yield_qty=1)
        RecipeLine.objects.create(recipe=rc, ingredient=ing, qty=200)            # 200 g / porsiya
        today = timezone.localdate()
        for k in range(1, 15):                                                    # 14 kun: har kuni 10 porsiya
            d = today - timedelta(days=k)
            o = Order.objects.create(status=OrderStatus.PAID, total=100000, subtotal=100000,
                                     paid_at=timezone.make_aware(datetime.combine(d, time(13, 0))))
            OrderItem.objects.create(order=o, product=p, name="FC osh", qty=10, price=10000)
        yield {"product": p, "ing": ing, "today": today}


def _holiday(days_ahead, uplift=50, prep=7, code="", days=1):
    from modules.forecast.models import Holiday
    return Holiday.objects.create(code=code, name={"uz": "Test bayram", "ru": "", "en": ""},
                                  date=timezone.localdate() + timedelta(days=days_ahead), days=days,
                                  uplift_percent=uplift, prep_days=prep)


@pytest.mark.django_db
def test_builtin_holidays_once_and_disable_not_recreated(api, fc):
    with schema_context("lazzat"):
        from modules.forecast import services
        from modules.forecast.models import Holiday
        Holiday.objects.filter(date__year=2027).delete()
        assert services.ensure_year(2027) > 10
        assert services.ensure_year(2027) == 0                                   # ikkinchi marta — qo'shilmaydi
        nav = Holiday.objects.get(code="navruz", date__year=2027)
        assert nav.date == date(2027, 3, 21) and not nav.is_approx
        eid = Holiday.objects.get(code="kurban_eid", date__year=2027)
        assert eid.is_approx and eid.date == date(2027, 5, 16)
    r = api.delete(f"/api/v1/forecast/holidays/{nav.pk}")
    assert r.json() == {"ok": True, "disabled": True}
    with schema_context("lazzat"):
        services.ensure_year(2027)
        assert Holiday.objects.filter(code="navruz", date__year=2027).count() == 1
        assert not Holiday.objects.get(code="navruz", date__year=2027).is_active


@pytest.mark.django_db
def test_plan_math_history_weekday_holiday(api, fc):
    with schema_context("lazzat"):
        h = _holiday(3, uplift=50)
    p = api.get(f"/api/v1/forecast/plan?holiday_id={h.pk}").json()
    assert p["days"] == 4 and p["history"]["days"] == 14
    assert p["weekday_factors"] == [1.0] * 7                                      # bir xil savdo — hafta kuni ta'siri yo'q
    ln = next(x for x in p["lines"] if x["ingredient_id"] == fc["ing"].pk)
    # 4 kun: 1+1+1+1,5 = 4,5 × 10 porsiya × 0,2 kg = 9 kg; + min 2 − qoldiq 5 = 6 kg
    assert ln["need"] == pytest.approx(9.0) and ln["buy"] == 6.0 and ln["cost"] == 300000
    assert p["revenue_forecast"] == 450000 and p["revenue_normal"] == 400000
    assert p["short_count"] == 1 and p["total_cost"] == 300000
    assert p["products"][0]["qty"] == 15                                         # bayram kuni: 10 × 1,5
    assert p["buy_by"] == (fc["today"] + timedelta(days=1)).isoformat()           # 2 kun oldin
    r = api.get("/api/v1/forecast/plan?days=7").json()
    assert r["days"] == 7 and r["holiday"] is None


@pytest.mark.django_db
def test_alert_creates_single_task(api, fc):
    with schema_context("lazzat"):
        h = _holiday(3)
        _holiday(30)                                                              # hali uzoq — ogohlantirish yo'q
    ov = api.get("/api/v1/forecast/overview").json()
    assert [a["id"] for a in ov["alerts"]] == [h.pk]
    a = ov["alerts"][0]
    assert a["short_count"] == 1 and "3 kundan keyin" in a["message"] and a["top_short"] == ["FC go'sht"]
    api.get("/api/v1/forecast/overview")
    with schema_context("lazzat"):
        from modules.tasks.models import Task
        t = Task.objects.filter(title__startswith="Bayramga tayyorgarlik")
        assert t.count() == 1
        assert "300 000" in t.first().description and t.first().due_at is not None


@pytest.mark.django_db
def test_history_uplift_and_learn(api, fc):
    with schema_context("lazzat"):
        from modules.forecast import services
        from modules.pos.models import Order, OrderStatus
        today = fc["today"]
        past = _holiday(-3, code="xtest")
        Order.objects.create(status=OrderStatus.PAID, total=50000, subtotal=50000,          # o'sha kuni 150 000
                             paid_at=timezone.make_aware(datetime.combine(today - timedelta(days=3), time(19, 0))))
        assert services.history_uplift(past) == 50
        nxt = _holiday(40, uplift=5, code="xtest")
    r = api.post(f"/api/v1/forecast/holidays/{nxt.pk}/learn")
    assert r.status_code == 200 and r.json()["uplift_percent"] == 50
    with schema_context("lazzat"):
        lone = _holiday(20, code="")
    assert api.post(f"/api/v1/forecast/holidays/{lone.pk}/learn").status_code == 400


@pytest.mark.django_db
def test_weather_fetch_hints_factor_and_offline(api, fc, monkeypatch):
    from modules.forecast import weather
    today = fc["today"]
    fake = {"daily": {"time": [(today + timedelta(days=i)).isoformat() for i in range(3)],
                      "weather_code": [0, 63, 3], "temperature_2m_max": [38.2, 22, 18], "temperature_2m_min": [24, 14, 9],
                      "precipitation_sum": [0, 8.5, 0], "precipitation_probability_max": [0, 90, 10], "wind_speed_10m_max": [10, 45, 12]}}
    monkeypatch.setattr(weather, "_http_get", lambda url: fake)
    w = api.get("/api/v1/forecast/weather").json()
    assert w["ok"] and len(w["days"]) == 3 and w["location"]["name"] == "Toshkent"
    hot, rain = w["days"][0], w["days"][1]
    assert hot["icon"] == "☀️" and hot["effect"] == -5 and "Issiq 38°" in hot["hints"][0]["text"]
    assert rain["effect"] == -10 and any("Yomg'ir" in x["text"] for x in rain["hints"]) and any("shamol" in x["text"] for x in rain["hints"])
    p = api.get("/api/v1/forecast/plan?days=3").json()
    assert [d["factor"] for d in p["daily"]] == [0.95, 0.9, 1.0]

    monkeypatch.setattr(weather, "_http_get", _offline)
    r = api.post("/api/v1/forecast/weather/refresh")
    assert r.status_code == 503 and "ulanib bo'lmadi" in r.json()["detail"]
    assert len(api.get("/api/v1/forecast/weather").json()["days"]) == 3         # eski prognoz qoladi


@pytest.mark.django_db
def test_dashboard_block_validation_and_module_off(api, fc, tenant):
    with schema_context("lazzat"):
        _holiday(2)
    assert api.post("/api/v1/forecast/holidays", {"name": {"uz": " "}, "date": "2026-12-01"}).status_code == 400
    assert api.post("/api/v1/forecast/holidays", {"name": {"uz": "Ok"}, "date": "2026-12-01", "uplift_percent": 500}).status_code == 400
    r = api.post("/api/v1/forecast/holidays", {"name": {"uz": "Filial yubileyi"}, "date": "2026-12-01", "uplift_percent": 25})
    assert r.status_code == 200 and not r.json()["builtin"]
    assert api.delete(f"/api/v1/forecast/holidays/{r.json()['id']}").json()["disabled"] is False
    from public.services import set_modules
    with schema_context("public"):
        set_modules(tenant, [m for m in tenant.enabled_modules if m != "forecast"])
    assert api.get("/api/v1/forecast/overview").status_code == 404
