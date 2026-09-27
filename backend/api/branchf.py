"""Filial filtri (bo'lim panellari va dashboardlar uchun).

strict — faqat shu filial yozuvlari (savdo, cheklar);
loose  — shu filial + filialga bog'lanmagan «umumiy» yozuvlar (xarajat, xarid, vazifa, loyiha…).
branch_id bo'sh bo'lsa — hammasi (barcha filiallar).
"""
from __future__ import annotations

from django.db.models import Q


def make(branch_id: int | None):
    def strict(qs, f: str = "branch"):
        return qs.filter(**{f"{f}_id": branch_id}) if branch_id else qs

    def loose(qs, f: str = "branch"):
        return qs.filter(Q(**{f"{f}_id": branch_id}) | Q(**{f"{f}__isnull": True})) if branch_id else qs

    return strict, loose
