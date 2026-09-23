"""Ombor va tannarx API — /api/v1/inventory/..."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from django.db.models import Q
from django.shortcuts import get_object_or_404
from ninja import Router, Schema
from ninja.errors import HttpError

from core.audit import record, snapshot
from core.auth import auth, require_module, require_perm
from core.models import Branch
from modules.catalog.models import Product

from . import services
from .models import (
    SUB_UNIT,
    Ingredient,
    MovementKind,
    Purchase,
    Recipe,
    RecipeLine,
    StockMovement,
    Supplier,
    Unit,
)

router = Router(tags=["inventory"])


def _guard(request, perm: str):
    require_module(request, "inventory")
    require_perm(request, perm)


class I18n(Schema):
    uz: str = ""
    ru: str = ""
    en: str = ""


class IngredientIn(Schema):
    name: I18n
    category: str = ""
    unit: str = "kg"
    price: float = 0
    min_stock: float = 0
    supplier_id: Optional[int] = None
    is_active: bool = True


class IngredientOut(Schema):
    id: int
    name: dict
    category: str
    unit: str
    sub_unit: str
    price: float
    stock: float
    min_stock: float
    is_low: bool
    stock_value: int
    supplier_id: Optional[int] = None
    is_active: bool
    used_in: int = 0

    @staticmethod
    def resolve_used_in(obj):
        return obj.recipe_lines.count()


class SupplierIn(Schema):
    name: str
    phone: str = ""
    note: str = ""
    is_active: bool = True


class SupplierOut(SupplierIn):
    id: int


class PurchaseLineIn(Schema):
    ingredient_id: int
    qty: float
    unit_price: float


class PurchaseIn(Schema):
    lines: list[PurchaseLineIn]
    branch_id: Optional[int] = None
    supplier_id: Optional[int] = None
    date: Optional[date] = None
    note: str = ""


class PurchaseOut(Schema):
    id: int
    number: int
    date: date
    total: float
    note: str
    supplier: Optional[str] = None
    branch: Optional[str] = None
    lines: list[dict] = []
    created_at: datetime

    @staticmethod
    def resolve_supplier(obj):
        return obj.supplier.name if obj.supplier_id else None

    @staticmethod
    def resolve_branch(obj):
        return obj.branch.name if obj.branch_id else None

    @staticmethod
    def resolve_lines(obj):
        return [{"ingredient_id": ln.ingredient_id, "name": ln.ingredient.name, "qty": float(ln.qty),
                 "unit": ln.ingredient.unit, "unit_price": float(ln.unit_price), "total": float(ln.total)}
                for ln in obj.lines.select_related("ingredient")]


class RecipeLineIn(Schema):
    ingredient_id: int
    qty: float
    waste_percent: float = 0


class RecipeIn(Schema):
    yield_qty: float = 1
    note: str = ""
    lines: list[RecipeLineIn]


class RecipeOut(Schema):
    product_id: int
    product_name: dict
    price: int
    yield_qty: float
    note: str
    cost: float
    margin_percent: Optional[float] = None
    food_cost_percent: Optional[float] = None
    computed_at: Optional[datetime] = None
    lines: list[dict] = []

    @staticmethod
    def resolve_product_name(obj):
        return obj.product.name

    @staticmethod
    def resolve_price(obj):
        return obj.product.price

    @staticmethod
    def resolve_margin_percent(obj):
        p = obj.product.price
        return round((p - float(obj.cost)) / p * 100, 1) if p else None

    @staticmethod
    def resolve_food_cost_percent(obj):
        p = obj.product.price
        return round(float(obj.cost) / p * 100, 1) if p else None

    @staticmethod
    def resolve_lines(obj):
        return [{"id": ln.id, "ingredient_id": ln.ingredient_id, "name": ln.ingredient.name, "unit": ln.ingredient.sub_unit,
                 "qty": float(ln.qty), "waste_percent": float(ln.waste_percent), "price": float(ln.ingredient.price),
                 "cost": float(ln.cost)} for ln in obj.lines.select_related("ingredient")]


class AdjustIn(Schema):
    qty: float
    kind: str = "adjust"
    note: str = ""
    branch_id: Optional[int] = None


class MovementOut(Schema):
    id: int
    at: datetime
    ingredient: dict
    kind: str
    qty: float
    unit_price: float
    ref: str
    note: str
    actor: Optional[str] = None

    @staticmethod
    def resolve_ingredient(obj):
        return {"id": obj.ingredient_id, "name": obj.ingredient.name, "unit": obj.ingredient.unit}

    @staticmethod
    def resolve_actor(obj):
        return obj.actor.full_name if obj.actor_id else None


# ------------------------------------------------------------------ umumiy
@router.get("/summary", auth=auth)
def summary(request):
    _guard(request, "inventory.view")
    s = services.stock_summary()
    s["units"] = [{"code": u.value, "label": u.label, "sub": SUB_UNIT[u][0]} for u in Unit]
    s["kinds"] = [{"code": k.value, "label": k.label} for k in MovementKind]
    return s


# ------------------------------------------------------------------ xomashyo
@router.get("/ingredients", response=list[IngredientOut], auth=auth)
def list_ingredients(request, q: Optional[str] = None, low: bool = False, category: Optional[str] = None):
    _guard(request, "inventory.view")
    qs = Ingredient.objects.filter(deleted_at__isnull=True).prefetch_related("recipe_lines")
    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(category__icontains=q))
    if category:
        qs = qs.filter(category=category)
    items = list(qs)
    return [i for i in items if i.is_low] if low else items


@router.post("/ingredients", response=IngredientOut, auth=auth)
def create_ingredient(request, data: IngredientIn):
    _guard(request, "inventory.edit")
    d = data.dict()
    d["name"] = data.name.dict()
    i = Ingredient.objects.create(**d)
    record(request, "create", i)
    return i


@router.put("/ingredients/{iid}", response=IngredientOut, auth=auth)
def update_ingredient(request, iid: int, data: IngredientIn):
    _guard(request, "inventory.edit")
    i = get_object_or_404(Ingredient, pk=iid, deleted_at__isnull=True)
    before = snapshot(i)
    old_price = i.price
    for k, v in data.dict().items():
        setattr(i, k, v.dict() if k == "name" else v)
    i.save()
    if Decimal(str(i.price)) != old_price:
        services.recompute_for_ingredient(i, request.tenant)   # narx qo'lda o'zgardi → taomlar tannarxi
    record(request, "update", i, before=before)
    return i


@router.delete("/ingredients/{iid}", auth=auth)
def delete_ingredient(request, iid: int):
    _guard(request, "inventory.edit")
    i = get_object_or_404(Ingredient, pk=iid, deleted_at__isnull=True)
    if i.recipe_lines.exists():
        raise HttpError(400, "Bu xomashyo tex-kartalarda ishlatilgan — avval u yerdan olib tashlang.")
    i.soft_delete()
    record(request, "delete", i)
    return {"ok": True}


@router.post("/ingredients/{iid}/adjust", response=IngredientOut, auth=auth)
def adjust(request, iid: int, data: AdjustIn):
    """Inventarizatsiya / chiqindi: haqiqiy qoldiqni yozish."""
    _guard(request, "inventory.edit")
    i = get_object_or_404(Ingredient, pk=iid, deleted_at__isnull=True)
    services.adjust_stock(i, Decimal(str(data.qty)), kind=data.kind, note=data.note,
                          branch=Branch.objects.filter(pk=data.branch_id).first() if data.branch_id else None,
                          actor=request.auth, tenant=request.tenant)
    record(request, "adjust", i, after={"qty": data.qty, "kind": data.kind})
    return i


# ------------------------------------------------------------------ yetkazib beruvchilar
@router.get("/suppliers", response=list[SupplierOut], auth=auth)
def list_suppliers(request):
    _guard(request, "inventory.view")
    return Supplier.objects.all()


@router.post("/suppliers", response=SupplierOut, auth=auth)
def create_supplier(request, data: SupplierIn):
    _guard(request, "inventory.edit")
    return Supplier.objects.create(**data.dict())


# ------------------------------------------------------------------ kirim
@router.get("/purchases", response=list[PurchaseOut], auth=auth)
def list_purchases(request, limit: int = 50):
    _guard(request, "inventory.view")
    return Purchase.objects.select_related("supplier", "branch").prefetch_related("lines__ingredient")[:limit]


@router.post("/purchases", response=PurchaseOut, auth=auth)
def create_purchase(request, data: PurchaseIn):
    """Bozorlik: kirim → qoldiq oshadi, narx yangilanadi, taomlar tannarxi qayta hisoblanadi."""
    _guard(request, "inventory.purchase")
    if not data.lines:
        raise HttpError(400, "Kamida bitta qator kiriting.")
    p = services.create_purchase(
        lines=[ln.dict() for ln in data.lines],
        branch=Branch.objects.filter(pk=data.branch_id).first() if data.branch_id else None,
        supplier=Supplier.objects.filter(pk=data.supplier_id).first() if data.supplier_id else None,
        date=data.date, note=data.note, actor=request.auth, tenant=request.tenant,
    )
    record(request, "create", p)
    return p


# ------------------------------------------------------------------ tex-karta
@router.get("/recipes", auth=auth)
def list_recipes(request):
    """Barcha taomlar: tex-kartasi bor/yo'q, tannarx, marja, food cost %."""
    _guard(request, "inventory.view")
    out = []
    for p in Product.objects.filter(deleted_at__isnull=True).select_related("category", "recipe"):
        r = getattr(p, "recipe", None)
        cost = float(r.cost) if r else float(p.cost)
        out.append({"product_id": p.pk, "name": p.name, "category": p.category.name, "price": p.price, "cost": cost,
                    "has_recipe": r is not None, "lines": r.lines.count() if r else 0,
                    "food_cost_percent": round(cost / p.price * 100, 1) if p.price else None,
                    "margin_percent": round((p.price - cost) / p.price * 100, 1) if p.price else None})
    return out


@router.get("/recipes/{pid}", response=RecipeOut, auth=auth)
def get_recipe(request, pid: int):
    _guard(request, "inventory.view")
    p = get_object_or_404(Product, pk=pid, deleted_at__isnull=True)
    r, _ = Recipe.objects.get_or_create(product=p)
    return r


@router.put("/recipes/{pid}", response=RecipeOut, auth=auth)
def save_recipe(request, pid: int, data: RecipeIn):
    _guard(request, "inventory.recipe")
    p = get_object_or_404(Product, pk=pid, deleted_at__isnull=True)
    r, _ = Recipe.objects.get_or_create(product=p)
    before = snapshot(r)
    r.yield_qty = Decimal(str(data.yield_qty or 1))
    r.note = data.note
    r.save()
    r.lines.all().delete()
    for i, ln in enumerate(data.lines):
        RecipeLine.objects.create(recipe=r, ingredient_id=ln.ingredient_id, qty=Decimal(str(ln.qty)),
                                  waste_percent=Decimal(str(ln.waste_percent)), sort_order=i)
    services.recompute_recipe(r, request.tenant)
    record(request, "update", r, before=before)
    return Recipe.objects.get(pk=r.pk)


@router.post("/recipes/recompute", auth=auth)
def recompute(request):
    _guard(request, "inventory.recipe")
    return {"recomputed": services.recompute_all(request.tenant)}


# ------------------------------------------------------------------ harakatlar
@router.get("/movements", response=list[MovementOut], auth=auth)
def movements(request, ingredient_id: Optional[int] = None, kind: Optional[str] = None, limit: int = 100):
    _guard(request, "inventory.view")
    qs = StockMovement.objects.select_related("ingredient", "actor")
    if ingredient_id:
        qs = qs.filter(ingredient_id=ingredient_id)
    if kind:
        qs = qs.filter(kind=kind)
    return qs[:limit]
