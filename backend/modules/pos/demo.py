"""Demo: so'nggi 30 kunlik savdo (hisobotlar bo'sh ko'rinmasin)."""
import random
from datetime import timedelta

from django.utils import timezone

from core.models import Branch, User
from modules.catalog.models import Product

from .models import CashShift, Order, OrderItem, OrderStatus, PayMethod


def seed_demo_orders(days: int = 30, per_day: tuple[int, int] = (55, 80)) -> int:
    if Order.objects.exists():
        return 0
    random.seed(7)
    products = list(Product.objects.filter(deleted_at__isnull=True, is_active=True))
    if not products:
        return 0
    branch = Branch.objects.filter(deleted_at__isnull=True).first()
    cashier = User.objects.filter(memberships__role__code__in=["cashier", "owner"]).first()
    now = timezone.now()
    n = 0
    for d in range(days, -1, -1):
        day = now - timedelta(days=d)
        shift = CashShift.objects.create(branch=branch, opened_by=cashier, opened_at=day.replace(hour=9, minute=0),
                                         closed_at=None if d == 0 else day.replace(hour=23, minute=0), cash_start=200_000)
        weekend = day.weekday() >= 5
        for k in range(random.randint(*per_day) + (per_day[0] // 3 if weekend else 0)):
            hour = random.choices(range(10, 23), weights=[2, 3, 6, 8, 6, 4, 4, 5, 7, 9, 8, 5, 2])[0]
            at = day.replace(hour=hour, minute=random.randint(0, 59))
            if at > now:
                continue
            o = Order.objects.create(branch=branch, shift=shift, cashier=cashier, status=OrderStatus.PAID,
                                     type=random.choice(["takeaway", "takeaway", "dine_in", "delivery"]),
                                     payment_method=random.choices([m.value for m in PayMethod], weights=[45, 30, 10, 10, 4, 1])[0],
                                     paid_at=at)
            for p in random.sample(products, k=random.randint(1, 3)):
                OrderItem.objects.create(order=o, product=p, name=p.name.get("uz") or str(p), qty=random.randint(1, 2),
                                         price=p.price, cost=p.cost)
            o.recalc()
            o.save()
            Order.objects.filter(pk=o.pk).update(created_at=at)
            n += 1
        shift.cash_end = shift.cash_start + shift.totals()["by_method"].get("cash", 0) - (random.choice([0, 0, 5000]))
        shift.save()
    return n
