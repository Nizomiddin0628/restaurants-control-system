"""Ombor xizmatlari: kirim, tannarx qayta hisoblash, savdoda kamaytirish, ogohlantirish."""
from __future__ import annotations

from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from core.events import emit

from .models import Ingredient, MovementKind, Purchase, PurchaseLine, Recipe, RecipeLine, StockMovement


def _setting(tenant, key, default):
    try:
        return (tenant.settings.get("modules", {}).get("inventory", {}) or {}).get(key, default)
    except Exception:
        return default


# ------------------------------------------------------------------ tannarx

@transaction.atomic
def recompute_recipe(recipe: Recipe, tenant=None) -> Decimal:
    """Tex-karta tannarxini hisoblab, taomga yozadi (Product.cost)."""
    recipe.cost = recipe.compute_cost()
    recipe.computed_at = timezone.now()
    recipe.save(update_fields=["cost", "computed_at", "updated_at"])
    if tenant is None or _setting(tenant, "auto_update_product_cost", True):
        p = recipe.product
        if int(p.cost) != int(recipe.cost):
            p.cost = int(recipe.cost)
            p.save(update_fields=["cost", "updated_at"])
            emit("inventory.cost_changed", {"product_id": p.pk, "cost": int(recipe.cost)}, tenant=tenant)
    return recipe.cost


def recompute_for_ingredient(ingredient: Ingredient, tenant=None) -> int:
    """Xomashyo narxi o'zgardi → shu xomashyo bor barcha taomlar."""
    n = 0
    for rid in RecipeLine.objects.filter(ingredient=ingredient).values_list("recipe_id", flat=True).distinct():
        recompute_recipe(Recipe.objects.get(pk=rid), tenant)
        n += 1
    return n


def recompute_all(tenant=None) -> int:
    n = 0
    for r in Recipe.objects.all():
        recompute_recipe(r, tenant)
        n += 1
    return n


# ------------------------------------------------------------------ kirim

@transaction.atomic
def post_purchase(purchase: Purchase, tenant=None, actor=None) -> Purchase:
    """Kirimni omborga o'tkazish: qoldiq +, narx yangilanadi, tannarx qayta hisoblanadi."""
    method = _setting(tenant, "price_method", "average")
    total = Decimal("0")
    touched: list[Ingredient] = []
    for line in purchase.lines.select_related("ingredient"):
        ing = line.ingredient
        old_stock, old_price = ing.stock, ing.price
        if method == "average" and old_stock > 0 and old_price > 0:
            ing.price = ((old_stock * old_price + line.qty * line.unit_price) / (old_stock + line.qty)).quantize(Decimal("0.01"))
        else:
            ing.price = line.unit_price
        ing.stock = old_stock + line.qty
        ing.save(update_fields=["price", "stock", "updated_at"])
        StockMovement.objects.create(ingredient=ing, branch=purchase.branch, kind=MovementKind.PURCHASE, qty=line.qty,
                                     unit_price=line.unit_price, ref=f"Kirim #{purchase.number}", actor=actor)
        total += line.total
        if ing.price != old_price:
            touched.append(ing)
    purchase.total = total
    purchase.is_posted = True
    purchase.save(update_fields=["total", "is_posted", "updated_at"])
    for ing in touched:
        recompute_for_ingredient(ing, tenant)
    emit("inventory.purchase_posted", {"purchase_id": purchase.pk, "total": int(total)}, tenant=tenant)
    return purchase


# ------------------------------------------------------------------ savdo / chiqindi / inventarizatsiya

@transaction.atomic
def consume_for_sale(items: list[dict], *, branch=None, ref: str = "", tenant=None, actor=None) -> int:
    """
    Kassa savdosi: [{"product_id": 1, "qty": 2}, ...] → tex-karta bo'yicha xomashyo kamayadi.
    Tex-kartasi yo'q taom o'tkazib yuboriladi. Kam qoldiq → `inventory.low_stock` hodisasi.
    """
    if tenant is not None and not _setting(tenant, "deduct_on_sale", True):
        return 0
    n = 0
    recipes = {r.product_id: r for r in Recipe.objects.filter(product_id__in=[i["product_id"] for i in items]).prefetch_related("lines__ingredient")}
    low: list[Ingredient] = []
    for item in items:
        r = recipes.get(item["product_id"])
        if not r:
            continue
        portions = Decimal(str(item.get("qty", 1))) / (r.yield_qty or 1)
        for line in r.lines.all():
            ing = line.ingredient
            qty = (line.base_qty * (1 + line.waste_percent / 100) * portions).quantize(Decimal("0.001"))
            ing.stock = ing.stock - qty
            ing.save(update_fields=["stock", "updated_at"])
            StockMovement.objects.create(ingredient=ing, branch=branch, kind=MovementKind.SALE, qty=-qty,
                                         unit_price=ing.price, ref=ref, actor=actor)
            n += 1
            if ing.is_low:
                low.append(ing)
    for ing in {i.pk: i for i in low}.values():
        emit("inventory.low_stock", {"ingredient_id": ing.pk, "product_name": str(ing), "qty": f"{ing.stock} {ing.unit}",
                                     "min": str(ing.min_stock)}, tenant=tenant)
    return n


@transaction.atomic
def adjust_stock(ingredient: Ingredient, new_qty: Decimal, *, kind: str = MovementKind.ADJUST, note: str = "",
                 branch=None, actor=None, tenant=None) -> StockMovement:
    diff = Decimal(str(new_qty)) - ingredient.stock
    ingredient.stock = Decimal(str(new_qty))
    ingredient.save(update_fields=["stock", "updated_at"])
    m = StockMovement.objects.create(ingredient=ingredient, branch=branch, kind=kind, qty=diff,
                                     unit_price=ingredient.price, note=note, actor=actor)
    if ingredient.is_low:
        emit("inventory.low_stock", {"ingredient_id": ingredient.pk, "product_name": str(ingredient),
                                     "qty": f"{ingredient.stock} {ingredient.unit}", "min": str(ingredient.min_stock)}, tenant=tenant)
    return m


def create_purchase(*, lines: list[dict], branch=None, supplier=None, date=None, note: str = "", actor=None, tenant=None) -> Purchase:
    p = Purchase.objects.create(branch=branch, supplier=supplier, date=date or timezone.localdate(), note=note,
                                created_by=actor, is_posted=False)
    for ln in lines:
        PurchaseLine.objects.create(purchase=p, ingredient_id=ln["ingredient_id"], qty=Decimal(str(ln["qty"])),
                                    unit_price=Decimal(str(ln["unit_price"])))
    return post_purchase(p, tenant, actor)


def stock_summary() -> dict:
    ings = Ingredient.objects.filter(deleted_at__isnull=True, is_active=True)
    total_value = sum((i.stock_value for i in ings), Decimal("0"))
    return {
        "ingredients": ings.count(),
        "low": sum(1 for i in ings if i.is_low),
        "stock_value": int(total_value),
        "recipes": Recipe.objects.count(),
        "products_without_recipe": __import__("modules.catalog.models", fromlist=["Product"]).Product.objects.filter(
            deleted_at__isnull=True, recipe__isnull=True).count(),
    }
