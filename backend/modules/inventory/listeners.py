"""Ombor hodisa tinglovchilari: kassa savdosi → xomashyo kamayadi."""
from __future__ import annotations

from core.events import on


@on("pos.order_paid")
def deduct_on_sale(payload: dict) -> None:
    """Kassa: buyurtma to'landi → tex-karta bo'yicha ombordan yechiladi."""
    from .services import consume_for_sale

    items = [{"product_id": i["product_id"], "qty": i["qty"]} for i in payload.get("items", []) if i.get("product_id")]
    if items:
        consume_for_sale(items, branch=None, ref=f"Buyurtma #{payload.get('number')}", tenant=payload.get("_tenant"))
