"""Hisobot hisob-kitoblari — API va Excel eksport shu funksiyalarni ishlatadi."""
from __future__ import annotations

from datetime import date, timedelta

from django.db.models import BigIntegerField, Count, ExpressionWrapper, F, Sum
from django.db.models.functions import TruncDate, TruncHour

from .models import Expense


def _orders(start: date, end: date, branch_id=None):
    from modules.pos.models import Order, OrderStatus

    qs = Order.objects.filter(status=OrderStatus.PAID, paid_at__date__gte=start, paid_at__date__lte=end)
    return qs.filter(branch_id=branch_id) if branch_id else qs


def _labor(start: date, end: date) -> int:
    """Davrga to'g'ri keladigan oyliklar (oy ichida kunlarga proporsional)."""
    try:
        from modules.hr.models import Payslip
    except Exception:
        return 0
    total = 0
    for slip in Payslip.objects.filter(period__gte=start.replace(day=1), period__lte=end):
        m_start = slip.period
        m_end = (m_start.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
        days_in_month = (m_end - m_start).days + 1
        overlap = (min(end, m_end) - max(start, m_start)).days + 1
        if overlap > 0:
            total += int(slip.total * overlap / days_in_month)
    return total


def pnl(start: date, end: date, branch_id=None) -> dict:
    orders = _orders(start, end, branch_id)
    agg = orders.aggregate(revenue=Sum("total"), cogs=Sum("cost_total"), discount=Sum("discount"), n=Count("id"))
    revenue, cogs, n = int(agg["revenue"] or 0), int(agg["cogs"] or 0), agg["n"] or 0
    labor = _labor(start, end)
    exp_qs = Expense.objects.filter(date__gte=start, date__lte=end)
    if branch_id:
        exp_qs = exp_qs.filter(branch_id=branch_id)
    expenses = [{"category": r["category__name"], "code": r["category__code"], "is_fixed": r["category__is_fixed"], "amount": int(r["s"])}
                for r in exp_qs.values("category__name", "category__code", "category__is_fixed").annotate(s=Sum("amount")).order_by("-s")]
    expenses_total = sum(e["amount"] for e in expenses)
    gross = revenue - cogs
    net = gross - labor - expenses_total
    pct = lambda x: round(100 * x / revenue, 1) if revenue else 0.0  # noqa: E731
    days = (end - start).days + 1
    return {
        "period": {"start": start, "end": end, "days": days},
        "revenue": revenue, "orders": n, "avg_check": int(revenue / n) if n else 0, "discount": int(agg["discount"] or 0),
        "cogs": cogs, "food_cost_percent": pct(cogs), "gross_profit": gross, "gross_margin_percent": pct(gross),
        "labor": labor, "labor_percent": pct(labor),
        "expenses": expenses, "expenses_total": expenses_total, "expenses_percent": pct(expenses_total),
        "prime_cost": cogs + labor, "prime_cost_percent": pct(cogs + labor),
        "net_profit": net, "net_margin_percent": pct(net),
        "revenue_per_day": int(revenue / days) if days else 0,
        "break_even_revenue": int((labor + expenses_total) / (gross / revenue)) if revenue and gross > 0 else None,
    }


def daily_series(start: date, end: date, branch_id=None) -> list[dict]:
    rows = (_orders(start, end, branch_id).annotate(d=TruncDate("paid_at")).values("d")
            .annotate(revenue=Sum("total"), cogs=Sum("cost_total"), n=Count("id")).order_by("d"))
    by = {r["d"]: r for r in rows}
    out = []
    d = start
    while d <= end:
        r = by.get(d)
        out.append({"date": d, "revenue": int(r["revenue"]) if r else 0, "cogs": int(r["cogs"]) if r else 0, "orders": r["n"] if r else 0})
        d += timedelta(days=1)
    return out


def hourly_profile(start: date, end: date, branch_id=None) -> list[dict]:
    rows = (_orders(start, end, branch_id).annotate(h=TruncHour("paid_at")).values("h")
            .annotate(revenue=Sum("total"), n=Count("id")))
    by_hour = {h: {"hour": h, "revenue": 0, "orders": 0} for h in range(24)}
    for r in rows:
        hh = r["h"].hour if r["h"] else 0
        by_hour[hh]["revenue"] += int(r["revenue"])
        by_hour[hh]["orders"] += r["n"]
    return [v for v in by_hour.values() if v["orders"]]


def top_products(start: date, end: date, branch_id=None, limit: int = 10) -> list[dict]:
    from modules.pos.models import OrderItem, OrderStatus

    qs = OrderItem.objects.filter(order__status=OrderStatus.PAID, order__paid_at__date__gte=start, order__paid_at__date__lte=end)
    if branch_id:
        qs = qs.filter(order__branch_id=branch_id)
    rev = ExpressionWrapper(F("qty") * F("price"), output_field=BigIntegerField())
    cst = ExpressionWrapper(F("qty") * F("cost"), output_field=BigIntegerField())
    rows = (qs.values("product_id", "name").annotate(qty_sum=Sum("qty"), revenue=Sum(rev), cost=Sum(cst)).order_by("-revenue")[:limit])
    total = sum(int(r["revenue"]) for r in rows) or 1
    return [{"product_id": r["product_id"], "name": r["name"], "qty": int(r["qty_sum"]), "revenue": int(r["revenue"]),
             "cost": int(r["cost"]), "margin": int(r["revenue"] - r["cost"]), "share": round(100 * int(r["revenue"]) / total, 1)}
            for r in rows]


def by_payment_method(start: date, end: date, branch_id=None) -> list[dict]:
    rows = _orders(start, end, branch_id).values("payment_method").annotate(s=Sum("total"), n=Count("id")).order_by("-s")
    return [{"method": r["payment_method"], "total": int(r["s"]), "orders": r["n"]} for r in rows]


def by_branch(start: date, end: date) -> list[dict]:
    rows = _orders(start, end).values("branch_id", "branch__name").annotate(s=Sum("total"), c=Sum("cost_total"), n=Count("id")).order_by("-s")
    return [{"branch_id": r["branch_id"], "name": r["branch__name"] or "—", "revenue": int(r["s"]), "cogs": int(r["c"]),
             "orders": r["n"], "food_cost_percent": round(100 * int(r["c"]) / int(r["s"]), 1) if r["s"] else 0} for r in rows]


def menu_engineering(start: date, end: date, branch_id=None) -> list[dict]:
    """
    Menyu muhandisligi (Kasavana-Smith): mashhurlik × marja → Yulduz / Ot / Jumboq / It.
    Yulduz — ko'p sotiladi, marjasi baland (saqlang). Ot — ko'p sotiladi, marjasi past (narx/tannarx ko'ring).
    Jumboq — kam sotiladi, marjasi baland (reklama qiling). It — kam sotiladi, marjasi past (menyudan oling).
    """
    items = top_products(start, end, branch_id, limit=500)
    if not items:
        return []
    avg_qty = sum(i["qty"] for i in items) / len(items) * 0.7      # 70% qoidasi
    avg_margin = sum(i["margin"] / i["qty"] for i in items if i["qty"]) / len(items)
    for i in items:
        unit_margin = i["margin"] / i["qty"] if i["qty"] else 0
        popular, profitable = i["qty"] >= avg_qty, unit_margin >= avg_margin
        i["unit_margin"] = int(unit_margin)
        i["class"] = "star" if popular and profitable else "plowhorse" if popular else "puzzle" if profitable else "dog"
    return items
