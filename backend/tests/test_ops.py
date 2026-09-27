"""
Tuzilma va lavozimlar: shablon (takror bosilsa ko'paymaydi, «Menejer» → Filial menejeri), daraxt (bosh ofis + filiallar),
lavozim kartasi, kurs biriktirish → xodimga o'zi beriladi, xodim lavozimi o'zgarsa → kurs, aylana bo'ysunish taqiqlanadi,
xodimli lavozim/bo'lim o'chmaydi, modul o'chsa 404.
"""
import pytest
from django_tenants.utils import schema_context


@pytest.fixture
def ops(tenant):
    from public.services import set_modules
    with schema_context("public"):
        set_modules(tenant, sorted({*tenant.enabled_modules, "ops", "hr", "training"}))
    with schema_context("lazzat"):
        from modules.hr.models import Position
        from modules.ops.models import Department, PositionProfile
        PositionProfile.objects.all().delete()
        Department.objects.all().delete()
        Position.objects.get_or_create(name="Menejer", defaults={"department": "Boshqaruv"})
    yield


@pytest.mark.django_db
def test_template_idempotent_and_maps_existing(api, ops):
    r = api.post("/api/v1/ops/template").json()
    assert r["departments"] == 9 and r["positions"] + r["linked"] == 17
    again = api.post("/api/v1/ops/template").json()
    assert again["departments"] == 0 and again["positions"] == 0
    with schema_context("lazzat"):
        from modules.hr.models import Position
        m = Position.objects.get(name="Menejer")
        assert m.profile.template_key == "branch_manager" and m.department == "Boshqaruv"
        assert m.profile.reports_to.profile.template_key == "ops_director"
        assert not Position.objects.filter(name="Filial menejeri").exists()          # dublikat yaratilmadi
    meta = api.get("/api/v1/ops/meta").json()
    assert meta["has_structure"] and len(meta["departments"]) == 9


@pytest.mark.django_db
def test_tree_has_hq_and_branch_nodes(api, ops):
    api.post("/api/v1/ops/template")
    t = api.get("/api/v1/ops/tree").json()
    assert [r["name"] for r in t["roots"]] == ["Rahbar (CEO)"]

    def find(n, name):
        if n["name"] == name:
            return n
        for c in n["children"]:
            x = find(c, name)
            if x:
                return x
    ops_dir = find(t["roots"][0], "Operatsion direktor")
    branches = [c for c in ops_dir["children"] if c["type"] == "branch"]
    assert branches and branches[0]["children"][0]["name"] == "Menejer"
    assert find(branches[0], "Kassir")["headcount"] == 2
    assert t["stats"]["positions"] >= 17 and t["stats"]["departments"] == 9


@pytest.mark.django_db
def test_position_crud_links_and_auto_enroll(api, ops):
    api.post("/api/v1/ops/template")
    meta = api.get("/api/v1/ops/meta").json()
    kitchen = next(d for d in meta["departments"] if d["name"] == "Oshxona")
    chef = next(p for p in meta["positions"] if p["name"] == "Brend-shef")
    r = api.post("/api/v1/ops/positions", {"name": "Pitsa ustasi", "icon": "🍕", "department_id": kitchen["id"], "reports_to_id": chef["id"],
                                          "level": 5, "scope": "branch", "headcount": 2, "purpose": "Pitsani standart bo'yicha pishiradi.",
                                          "responsibilities": [{"text": "Xamirni tayyorlash", "freq": "shift"}, {"text": " ", "freq": "daily"}]})
    assert r.status_code == 200, r.content
    p = r.json()
    assert p["department"]["name"] == "Oshxona" and p["reports_to"]["name"] == "Brend-shef" and len(p["responsibilities"]) == 1
    assert api.post("/api/v1/ops/positions", {"name": "pitsa USTASI"}).status_code == 400          # dublikat nom
    with schema_context("lazzat"):
        from core.models import Membership, Role, User
        from modules.hr.models import Employee, Position
        from modules.training.models import Course, Enrollment
        c = Course.objects.create(title="Pitsa kursi", is_published=True)
        u = User.objects.create_user("998935551122", full_name="Pitsachi")
        Membership.objects.create(user=u, role=Role.objects.get(code="cook"))
        Employee.objects.create(user=u, position=Position.objects.get(pk=p["id"]))
    r = api.put(f"/api/v1/ops/positions/{p['id']}/links", {"courses": [c.pk]}).json()
    assert r["enrolled"] == 1 and r["position"]["counts"]["courses"] >= 1
    with schema_context("lazzat"):
        assert Enrollment.objects.filter(course=c, user=u).exists()
        c.refresh_from_db()
        assert p["id"] in c.positions
    api.put(f"/api/v1/ops/positions/{p['id']}/links", {"courses": []})
    with schema_context("lazzat"):
        c.refresh_from_db()
        assert p["id"] not in c.positions
    assert api.delete(f"/api/v1/ops/positions/{p['id']}").status_code == 400                     # xodimi bor


@pytest.mark.django_db
def test_position_change_event_enrolls(api, ops):
    api.post("/api/v1/ops/template")
    with schema_context("lazzat"):
        from core.models import Role
        from modules.hr.models import Position
        from modules.training.models import Course, Enrollment
        cashier = Position.objects.get(name="Kassir")
        c = Course.objects.create(title="Kassa kursi", is_published=True, positions=[cashier.pk])
        role = Role.objects.get(code="waiter")
    e = api.post("/api/v1/hr/employees", {"full_name": "Yangi Xodim", "phone": "935557788", "role_code": role.code}).json()
    with schema_context("lazzat"):
        assert not Enrollment.objects.filter(course=c).exists()
    body = {"full_name": "Yangi Xodim", "phone": "935557788", "role_code": role.code, "position_id": cashier.pk}
    assert api.put(f"/api/v1/hr/employees/{e['id']}", body).status_code == 200
    with schema_context("lazzat"):
        assert Enrollment.objects.filter(course=c, user__phone="+998935557788").exists()


@pytest.mark.django_db
def test_move_cycle_departments_and_module_off(api, ops, tenant):
    api.post("/api/v1/ops/template")
    meta = api.get("/api/v1/ops/meta").json()
    pid = {p["name"]: p["id"] for p in meta["positions"]}
    r = api.post(f"/api/v1/ops/positions/{pid['Operatsion direktor']}/move", {"reports_to_id": pid["Kassir"]})
    assert r.status_code == 400 and "bo'ysuna olmaydi" in r.json()["detail"]
    assert api.post(f"/api/v1/ops/positions/{pid['Kassir']}/move", {"reports_to_id": pid["Menejer"]}).status_code == 200
    d = api.post("/api/v1/ops/departments", {"name": "Yetkazib berish", "icon": "🛵"}).json()
    assert api.put(f"/api/v1/ops/departments/{d['id']}", {"name": "Kuryerlar", "icon": "🛵", "color": "#111111"}).json()["name"] == "Kuryerlar"
    kitchen = next(x for x in meta["departments"] if x["name"] == "Oshxona")
    assert api.delete(f"/api/v1/ops/departments/{kitchen['id']}").status_code == 400
    assert api.delete(f"/api/v1/ops/departments/{d['id']}").json() == {"ok": True}
    detail = api.get(f"/api/v1/ops/positions/{pid['Kassir']}").json()
    assert detail["reports_to"]["name"] == "Menejer" and detail["training"] is not None
    from public.services import set_modules
    with schema_context("public"):
        set_modules(tenant, [m for m in tenant.enabled_modules if m != "ops"])
    assert api.get("/api/v1/ops/tree").status_code == 404
