"""Demo: lavozimlar, xodim kartalari, bu hafta smenalari, davomat, joriy oy oyligi."""
import random
from datetime import datetime, time, timedelta

from django.utils import timezone

from core.models import Branch, Membership

from .models import Attendance, Employee, Payslip, Position, ShiftPlan, month_start

POS = [("Menejer", "Boshqaruv", "monthly", 6_000_000), ("Kassir", "Kassa", "shift", 180_000), ("Oshpaz", "Oshxona", "monthly", 5_000_000),
       ("Ofitsiant", "Zal", "hourly", 22_000), ("Buxgalter", "Boshqaruv", "monthly", 4_500_000), ("Marketolog", "Boshqaruv", "monthly", 4_000_000)]
ROLE2POS = {"manager": "Menejer", "cashier": "Kassir", "cook": "Oshpaz", "accountant": "Buxgalter", "marketer": "Marketolog", "courier": "Ofitsiant"}


def seed_demo_hr() -> int:
    if Employee.objects.exists():
        return 0
    random.seed(3)
    positions = {n: Position.objects.get_or_create(name=n, defaults={"department": d, "default_salary_type": st, "default_rate": r, "sort_order": i})[0]
                 for i, (n, d, st, r) in enumerate(POS)}
    branch = Branch.objects.filter(deleted_at__isnull=True).first()
    n = 0
    today = timezone.localdate()
    for m in Membership.objects.select_related("user", "role").exclude(role__code="owner"):
        pos = positions.get(ROLE2POS.get(m.role.code, "Ofitsiant"))
        e = Employee.objects.create(user=m.user, position=pos, branch=branch, salary_type=pos.default_salary_type,
                                    rate=pos.default_rate, hire_date=today - timedelta(days=random.randint(40, 700)))
        # bu hafta va o'tgan hafta smenalari
        for d in range(-7, 7):
            day = today + timedelta(days=d)
            if day.weekday() == random.randint(0, 6):
                continue
            ShiftPlan.objects.create(employee=e, branch=branch, date=day, start=time(9, 0), end=time(18, 0) if pos.name != "Kassir" else time(23, 0))
        # o'tgan kunlar davomati
        for d in range(-7, 0):
            day = today + timedelta(days=d)
            if not ShiftPlan.objects.filter(employee=e, date=day).exists():
                continue
            late = random.choice([0, 0, 0, 12, 25])
            cin = timezone.make_aware(datetime.combine(day, time(9, late)))
            Attendance.objects.create(employee=e, branch=branch, check_in=cin, check_out=cin + timedelta(hours=9), late_minutes=late)
        n += 1
    # bugun smenada bo'lganlar
    for e in Employee.objects.all()[:4]:
        Attendance.objects.create(employee=e, branch=branch, check_in=timezone.now() - timedelta(hours=3))
    # joriy oy oyligi (qoralama)
    for e in Employee.objects.all():
        s = Payslip(employee=e, period=month_start(today), salary_type=e.salary_type, rate=e.rate, hours=160, shifts=22, sales_base=0)
        s.compute()
        s.save()
    return n
