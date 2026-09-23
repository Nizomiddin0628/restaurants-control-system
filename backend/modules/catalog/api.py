"""Taomnoma API — Django Ninja router. Barcha yo'llar: /api/v1/catalog/..."""
from __future__ import annotations

from typing import Optional

from django.shortcuts import get_object_or_404
from ninja import File, Router, Schema
from ninja.files import UploadedFile
from ninja.pagination import PageNumberPagination, paginate

from core.audit import record, snapshot
from core.auth import auth, require_module, require_perm

from . import services
from .models import BranchPrice, Category, MenuVersion, Modifier, ModifierGroup, Product

router = Router(tags=["catalog"])


def _guard(request, perm: str):
    require_module(request, "catalog")
    require_perm(request, perm)


# ------------------------------------------------------------------ sxemalar
class I18n(Schema):
    uz: str = ""
    ru: str = ""
    en: str = ""


class CategoryIn(Schema):
    name: I18n
    is_active: bool = True
    custom_data: dict = {}


class CategoryOut(Schema):
    id: int
    name: dict
    image: Optional[str] = None
    sort_order: int
    is_active: bool
    products_count: int = 0

    @staticmethod
    def resolve_image(obj):
        return obj.image.url if obj.image else None

    @staticmethod
    def resolve_products_count(obj):
        return obj.products.filter(deleted_at__isnull=True).count()


class ModifierOptionOut(Schema):
    id: int
    name: dict
    price: int
    is_default: bool
    is_active: bool


class ModifierGroupOut(Schema):
    id: int
    name: dict
    min_select: int
    max_select: int
    is_active: bool
    options: list[ModifierOptionOut] = []


class ModifierGroupIn(Schema):
    name: I18n
    min_select: int = 0
    max_select: int = 1
    options: list[dict] = []   # [{"name": {...}, "price": 0, "is_default": false}]


class ProductIn(Schema):
    category_id: int
    name: I18n
    description: I18n = I18n()
    price: int = 0
    cost: int = 0
    sku: str = ""
    weight_g: Optional[int] = None
    kcal: Optional[int] = None
    tags: list[str] = []
    modifier_group_ids: list[int] = []
    is_active: bool = True
    in_stop_list: bool = False
    ikpu_code: str = ""
    custom_data: dict = {}


class ProductPatch(Schema):
    """Inline tahrir: faqat yuborilgan maydonlar o'zgaradi."""
    name: Optional[I18n] = None
    price: Optional[int] = None
    cost: Optional[int] = None
    is_active: Optional[bool] = None
    in_stop_list: Optional[bool] = None
    category_id: Optional[int] = None
    tags: Optional[list[str]] = None
    custom_data: Optional[dict] = None


class ProductOut(Schema):
    id: int
    category_id: int
    name: dict
    description: dict
    sku: str
    price: int
    cost: int
    margin_percent: Optional[float] = None
    image: Optional[str] = None
    weight_g: Optional[int] = None
    kcal: Optional[int] = None
    tags: list
    modifier_group_ids: list[int] = []
    is_active: bool
    in_stop_list: bool
    sort_order: int
    ikpu_code: str
    custom_data: dict

    @staticmethod
    def resolve_image(obj):
        return obj.image.url if obj.image else None

    @staticmethod
    def resolve_modifier_group_ids(obj):
        return [g.pk for g in obj.modifier_groups.all()]


class BulkPatch(Schema):
    ids: list[int]
    price_percent: Optional[float] = None   # +10 → narx 10% oshadi
    is_active: Optional[bool] = None
    category_id: Optional[int] = None


class ReorderIn(Schema):
    ids: list[int]


class BranchPriceIn(Schema):
    branch_id: int
    price: Optional[int] = None   # None → filial narxi o'chiriladi


class VersionOut(Schema):
    id: int
    version: int
    published_at: str
    published_by: str
    note: str

    @staticmethod
    def resolve_published_at(obj):
        return obj.published_at.isoformat()


# ------------------------------------------------------------------ kategoriyalar
@router.get("/categories", response=list[CategoryOut], auth=auth)
def list_categories(request):
    _guard(request, "catalog.view")
    return Category.objects.filter(deleted_at__isnull=True)


@router.post("/categories", response=CategoryOut, auth=auth)
def create_category(request, data: CategoryIn):
    _guard(request, "catalog.edit")
    c = Category.objects.create(name=data.name.dict(), is_active=data.is_active, custom_data=data.custom_data,
                                sort_order=Category.objects.count())
    record(request, "create", c)
    return c


@router.put("/categories/{cid}", response=CategoryOut, auth=auth)
def update_category(request, cid: int, data: CategoryIn):
    _guard(request, "catalog.edit")
    c = get_object_or_404(Category, pk=cid, deleted_at__isnull=True)
    before = snapshot(c)
    c.name, c.is_active, c.custom_data = data.name.dict(), data.is_active, data.custom_data
    c.save()
    record(request, "update", c, before=before)
    return c


@router.delete("/categories/{cid}", auth=auth)
def delete_category(request, cid: int):
    _guard(request, "catalog.edit")
    c = get_object_or_404(Category, pk=cid, deleted_at__isnull=True)
    if c.products.filter(deleted_at__isnull=True).exists():
        return 400, {"detail": "Kategoriyada taomlar bor — avval ularni ko'chiring"}
    c.soft_delete()
    record(request, "delete", c)
    return {"ok": True}


@router.post("/categories/reorder", auth=auth)
def reorder_categories(request, data: ReorderIn):
    _guard(request, "catalog.edit")
    services.reorder(Category, data.ids)
    record(request, "reorder", model="Category", after={"ids": data.ids})
    return {"ok": True}


@router.post("/categories/{cid}/image", response=CategoryOut, auth=auth)
def upload_category_image(request, cid: int, file: UploadedFile = File(...)):
    _guard(request, "catalog.edit")
    c = get_object_or_404(Category, pk=cid)
    c.image.save(file.name, file, save=True)
    return c


# ------------------------------------------------------------------ taomlar
@router.get("/products", response=list[ProductOut], auth=auth)
@paginate(PageNumberPagination, page_size=100)
def list_products(request, category_id: Optional[int] = None, q: Optional[str] = None, active: Optional[bool] = None):
    _guard(request, "catalog.view")
    qs = Product.objects.filter(deleted_at__isnull=True).prefetch_related("modifier_groups")
    if category_id:
        qs = qs.filter(category_id=category_id)
    if q:
        qs = qs.filter(name__icontains=q)
    if active is not None:
        qs = qs.filter(is_active=active)
    return qs


@router.post("/products", response=ProductOut, auth=auth)
def create_product(request, data: ProductIn):
    _guard(request, "catalog.edit")
    payload = data.dict()
    gids = payload.pop("modifier_group_ids")
    payload["name"], payload["description"] = data.name.dict(), data.description.dict()
    p = Product.objects.create(sort_order=Product.objects.filter(category_id=data.category_id).count(), **payload)
    p.modifier_groups.set(gids)
    record(request, "create", p)
    return p


@router.get("/products/{pid}", response=ProductOut, auth=auth)
def get_product(request, pid: int):
    _guard(request, "catalog.view")
    return get_object_or_404(Product, pk=pid, deleted_at__isnull=True)


@router.put("/products/{pid}", response=ProductOut, auth=auth)
def update_product(request, pid: int, data: ProductIn):
    _guard(request, "catalog.edit")
    p = get_object_or_404(Product, pk=pid, deleted_at__isnull=True)
    before = snapshot(p)
    payload = data.dict()
    gids = payload.pop("modifier_group_ids")
    payload["name"], payload["description"] = data.name.dict(), data.description.dict()
    for k, v in payload.items():
        setattr(p, k, v)
    p.save()
    p.modifier_groups.set(gids)
    record(request, "update", p, before=before)
    return p


@router.patch("/products/{pid}", response=ProductOut, auth=auth)
def patch_product(request, pid: int, data: ProductPatch):
    _guard(request, "catalog.edit")
    p = get_object_or_404(Product, pk=pid, deleted_at__isnull=True)
    before = snapshot(p)
    for k, v in data.dict(exclude_unset=True).items():
        if k == "name" and v is not None:
            v = {**p.name, **{kk: vv for kk, vv in v.items() if vv is not None}}
        setattr(p, k, v)
    p.save()
    record(request, "update", p, before=before)
    return p


@router.delete("/products/{pid}", auth=auth)
def delete_product(request, pid: int):
    _guard(request, "catalog.edit")
    p = get_object_or_404(Product, pk=pid, deleted_at__isnull=True)
    p.soft_delete()
    record(request, "delete", p)
    return {"ok": True}


@router.post("/products/{pid}/image", response=ProductOut, auth=auth)
def upload_product_image(request, pid: int, file: UploadedFile = File(...)):
    _guard(request, "catalog.edit")
    p = get_object_or_404(Product, pk=pid)
    p.image.save(file.name, file, save=True)
    record(request, "update", p, after={"image": p.image.name})
    return p


@router.post("/products/reorder", auth=auth)
def reorder_products(request, data: ReorderIn):
    _guard(request, "catalog.edit")
    services.reorder(Product, data.ids)
    return {"ok": True}


@router.post("/products/bulk", auth=auth)
def bulk_products(request, data: BulkPatch):
    """Ommaviy tahrir: tanlangan taomlarga narx %, faollik yoki kategoriya."""
    _guard(request, "catalog.edit")
    qs = Product.objects.filter(pk__in=data.ids, deleted_at__isnull=True)
    n = 0
    for p in qs:
        if data.price_percent is not None:
            p.price = int(round(p.price * (1 + data.price_percent / 100) / 100.0) * 100)  # 100 so'mga yaxlitlash
        if data.is_active is not None:
            p.is_active = data.is_active
        if data.category_id is not None:
            p.category_id = data.category_id
        p.save()
        n += 1
    record(request, "bulk_update", model="Product", after={"ids": data.ids, "patch": data.dict(exclude_none=True)})
    return {"updated": n}


@router.put("/products/{pid}/branch-price", auth=auth)
def set_branch_price(request, pid: int, data: BranchPriceIn):
    _guard(request, "catalog.edit")
    p = get_object_or_404(Product, pk=pid)
    if data.price is None:
        BranchPrice.objects.filter(product=p, branch_id=data.branch_id).delete()
    else:
        BranchPrice.objects.update_or_create(product=p, branch_id=data.branch_id, defaults={"price": data.price})
    return {"ok": True}


# ------------------------------------------------------------------ modifikatorlar
@router.get("/modifier-groups", response=list[ModifierGroupOut], auth=auth)
def list_modifier_groups(request):
    _guard(request, "catalog.view")
    return ModifierGroup.objects.prefetch_related("options").all()


@router.post("/modifier-groups", response=ModifierGroupOut, auth=auth)
def create_modifier_group(request, data: ModifierGroupIn):
    _guard(request, "catalog.edit")
    g = ModifierGroup.objects.create(name=data.name.dict(), min_select=data.min_select, max_select=data.max_select,
                                     sort_order=ModifierGroup.objects.count())
    for i, o in enumerate(data.options):
        Modifier.objects.create(group=g, name=o.get("name", {}), price=int(o.get("price", 0)), is_default=bool(o.get("is_default")), sort_order=i)
    record(request, "create", g)
    return g


@router.put("/modifier-groups/{gid}", response=ModifierGroupOut, auth=auth)
def update_modifier_group(request, gid: int, data: ModifierGroupIn):
    _guard(request, "catalog.edit")
    g = get_object_or_404(ModifierGroup, pk=gid)
    g.name, g.min_select, g.max_select = data.name.dict(), data.min_select, data.max_select
    g.save()
    g.options.all().delete()
    for i, o in enumerate(data.options):
        Modifier.objects.create(group=g, name=o.get("name", {}), price=int(o.get("price", 0)), is_default=bool(o.get("is_default")), sort_order=i)
    record(request, "update", g)
    return g


@router.delete("/modifier-groups/{gid}", auth=auth)
def delete_modifier_group(request, gid: int):
    _guard(request, "catalog.edit")
    get_object_or_404(ModifierGroup, pk=gid).delete()
    return {"ok": True}


# ------------------------------------------------------------------ import / e'lon
@router.post("/import", auth=auth)
def import_products(request, file: UploadedFile = File(...)):
    _guard(request, "catalog.edit")
    result = services.import_excel(file.read())
    record(request, "import", model="Product", after=result)
    return result


@router.post("/publish", response=VersionOut, auth=auth)
def publish_menu(request, note: str = ""):
    _guard(request, "catalog.publish")
    mv = services.publish(by=str(request.auth), note=note, tenant=request.tenant)
    record(request, "publish", mv, after={"version": mv.version})
    return mv


@router.get("/versions", response=list[VersionOut], auth=auth)
def list_versions(request):
    _guard(request, "catalog.view")
    return MenuVersion.objects.all()[:20]


@router.get("/published")
def published_menu(request, version: Optional[int] = None):
    """Ochiq endpoint: sayt, Mini App, kassa e'lon qilingan taomnomani shu yerdan oladi (auth shart emas)."""
    require_module(request, "catalog")
    mv = MenuVersion.objects.filter(version=version).first() if version else MenuVersion.objects.order_by("-version").first()
    if not mv:
        return {"version": 0, "categories": []}
    return {"version": mv.version, "published_at": mv.published_at.isoformat(), **mv.snapshot}
