"""Moliya tinglovchilari: oylik to'landi → mehnat chiqimi; (ixtiyoriy) ombor kirimi → chiqim."""
from __future__ import annotations

from core.events import on


@on("hr.payslip_paid")
def payroll_expense(payload: dict) -> None:
    """Oylik to'langanda P&L'da 'Mehnat' allaqachon Payslip'dan olinadi — bu yerda faqat kassa chiqimi belgisi (ref)."""
    return None


@on("inventory.purchase_posted")
def purchase_expense(payload: dict) -> None:
    from .models import Expense, ExpenseCategory, ensure_categories

    tenant = payload.get("_tenant")
    auto = False
    try:
        auto = bool((tenant.settings.get("modules", {}).get("finance", {}) or {}).get("auto_expense_from_purchases"))
    except Exception:
        pass
    if not auto:
        return
    ensure_categories()
    cat, _ = ExpenseCategory.objects.get_or_create(code="purchases", defaults={"name": "Xomashyo xaridi", "sort_order": 50})
    Expense.objects.get_or_create(source="purchase", ref=f"purchase:{payload.get('purchase_id')}",
                                  defaults={"category": cat, "amount": int(payload.get("total", 0)), "note": "Ombor kirimi"})
