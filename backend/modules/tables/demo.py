"""Demo: ikkita zal, 14 ta stol xarita bo'ylab joylashgan, bir nechtasi band."""
import random

from core.models import Branch, User

from .models import Table, TableSession, Zone, ensure_zones


def seed_demo_tables() -> int:
    if Table.objects.exists():
        return 0
    random.seed(7)
    branch = Branch.objects.filter(deleted_at__isnull=True).first()
    ensure_zones(branch)
    zones = list(Zone.objects.all())
    hall, terrace = zones[0], zones[-1]
    plan = [
        (hall, "1", 2, "round", 8, 12), (hall, "2", 4, "square", 26, 12), (hall, "3", 4, "square", 44, 12),
        (hall, "4", 6, "long", 64, 12), (hall, "5", 2, "round", 8, 38), (hall, "6", 4, "square", 26, 38),
        (hall, "7", 4, "square", 44, 38), (hall, "8", 8, "long", 64, 38), (hall, "9", 4, "square", 8, 64),
        (hall, "10", 6, "long", 30, 64), (hall, "VIP-1", 10, "long", 60, 64),
        (terrace, "T1", 4, "round", 14, 18), (terrace, "T2", 4, "round", 42, 18), (terrace, "T3", 6, "long", 68, 18),
    ]
    for z, no, seats, shape, x, y in plan:
        Table.objects.create(zone=z, branch=branch, number=no, seats=seats, shape=shape, x=x, y=y,
                             size=2 if seats >= 6 else 1)
    waiter = User.objects.order_by("?").first()
    for t in Table.objects.order_by("?")[:3]:
        TableSession.objects.create(table=t, guests=min(t.seats, random.randint(2, 4)), waiter=waiter)
    Table.objects.filter(number="6").update(needs_cleaning=True)
    return Table.objects.count()