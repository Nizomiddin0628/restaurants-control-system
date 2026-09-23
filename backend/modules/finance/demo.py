"""Demo chiqimlar: ijara, kommunal, marketing — oxirgi 2 oy."""
import random
from datetime import timedelta

from django.utils import timezone

from .models import Expense, ExpenseCategory, ensure_categories


def seed_demo_expenses() -> int:
    if Expense.objects.exists():
        return 0
    ensure_categories()
    random.seed(11)
    cats = {c.code: c for c in ExpenseCategory.objects.all()}
    today = timezone.localdate()
    n = 0
    for m in (0, 1):
        first = (today.replace(day=1) - timedelta(days=1)).replace(day=1) if m else today.replace(day=1)
        for code, amount in [("rent", 12_000_000), ("utilities", 2_400_000), ("software", 490_000), ("tax", 1_800_000)]:
            Expense.objects.create(date=first + timedelta(days=2), category=cats[code], amount=amount, note="Oylik to'lov"); n += 1
        for _ in range(6):
            code = random.choice(["marketing", "packaging", "repair", "delivery", "other"])
            d = first + timedelta(days=random.randint(0, 27))
            if d <= today:
                Expense.objects.create(date=d, category=cats[code], amount=random.choice([150_000, 320_000, 480_000, 900_000]),
                                       note=random.choice(["Instagram reklama", "Stakan va qopqoq", "Konditsioner servisi", "Yandex Go", "Boshqa"])); n += 1
    return n
