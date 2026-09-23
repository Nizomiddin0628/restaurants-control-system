"""Zal hodisalari -> bron holati."""
from __future__ import annotations

from core.events import on


@on("tables.session_closed")
def on_session_closed(payload: dict) -> None:
    """Mehmon ketdi - o'sha stoldagi «o'tirdi» broni tugadi deb yopiladi."""
    from django.utils import timezone

    from .models import Reservation, ReservationStatus

    Reservation.objects.filter(table_id=payload.get("table_id"), status=ReservationStatus.SEATED).update(
        status=ReservationStatus.DONE, closed_at=timezone.now())