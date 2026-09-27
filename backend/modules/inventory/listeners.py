"""Ombor hodisa tinglovchilari: kassa savdosi → xomashyo kamayadi."""
from __future__ import annotations

from core.events import on


@on("pos.order_paid")
def deduct_on_sale(payload: dict) -> None:
    """Kassa: buyurtma to'landi → tex-karta bo'yicha ombordan yechiladi."""
    from .services import consume_for_sale

    items = [{"product_id": i["product_id"], "qty": i["qty"]} for i in payload.get("items", []) if i.get("product_id")]
    if items:
        from core.models import Branch
        branch = Branch.objects.filter(pk=payload.get("branch_id")).first() if payload.get("branch_id") else None
        consume_for_sale(items, branch=branch, ref=f"Buyurtma #{payload.get('number')}", tenant=payload.get("_tenant"))
