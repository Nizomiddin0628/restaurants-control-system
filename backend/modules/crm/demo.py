"""Demo: 80 ta mijoz (tug'ilgan kunlari bilan), kassa cheklarining bir qismiga telefon, bonus tarixi, 4 ta aksiya."""
import random
from datetime import date, timedelta

from django.utils import timezone

from .models import BonusTxn, Customer, OrderLink, Promo, TxnKind

MEN = ["Aziz", "Jasur", "Sardor", "Bekzod", "Otabek", "Javohir", "Sherzod", "Ulug'bek", "Doston", "Temur", "Rustam", "Anvar"]
WOMEN = ["Dilnoza", "Malika", "Nigora", "Shahnoza", "Madina", "Zarina", "Kamola", "Feruza", "Gulnora", "Laylo", "Sevara", "Munisa"]
SURN = ["Karimov", "Rahimov", "Toshmatov", "Yusupov", "Aliyev", "Qodirov", "Ergashev", "Nazarov", "Saidov", "Mirzayev"]


def seed_demo_crm(tenant=None) -> int:
    if Customer.objects.exists():
        return 0
    from modules.pos.models import Order, OrderStatus

    from . import services
    random.seed(11)
    cfg = services.conf(tenant) if tenant is not None else services._DEFAULTS
    today = timezone.localdate()
    customers = []
    for i in range(80):
        female = random.random() < .5
        first = random.choice(WOMEN if female else MEN)
        last = random.choice(SURN) + ("a" if female else "")
        if i < 3:                                   # bugun/ertaga tug'ilganlar — ekran bo'sh turmasin
            bd = date(random.randint(1985, 2002), (today + timedelta(days=i)).month, (today + timedelta(days=i)).day)
        else:
            bd = date(random.randint(1975, 2006), random.randint(1, 12), random.randint(1, 28)) if random.random() < .7 else None
        customers.append(Customer.objects.create(phone=f"+99890{7000000 + i * 131:07d}", name=f"{first} {last}", birthday=bd,
                                                 gender="f" if female else "m",
                                                 source=random.choice(["pos", "pos", "telegram", "site"])))
    weights = [min(random.paretovariate(1.2), 6) for _ in customers]   # kam mijoz — ko'p xarid (haqiqatga o'xshash)
    paid = list(Order.objects.filter(status=OrderStatus.PAID).order_by("paid_at"))
    for o in paid:
        if random.random() > .38:
            continue
        c = random.choices(customers, weights=weights)[0]
        lvl = services.level_of(c, cfg)
        o.customer_phone, o.customer_name = c.phone, c.name
        o.save(update_fields=["customer_phone", "customer_name"])
        earned = o.total * lvl["percent"] // 100
        c.orders_count += 1
        c.spent_total += o.total
        c.first_order_at = c.first_order_at or o.paid_at
        c.last_order_at = o.paid_at
        c.balance += earned
        c.save()
        OrderLink.objects.create(order_id=o.pk, customer=c, earned=earned, settled=True)
        BonusTxn.objects.create(customer=c, kind=TxnKind.EARN, amount=earned, order_id=o.pk,
                                note=f"Chek #{o.number} · {lvl['percent']}%", created_at=o.paid_at)
        if c.balance > 20000 and random.random() < .06:   # ba'zan bonus bilan to'lagan
            used = min(c.balance, o.total // 3) // 1000 * 1000
            if used:
                c.balance -= used
                c.save(update_fields=["balance"])
                BonusTxn.objects.create(customer=c, kind=TxnKind.SPEND, amount=-used, order_id=o.pk,
                                        note=f"Chek #{o.number}", created_at=o.paid_at)
    for c in customers:                             # karta birinchi xarid kuni ochilgan bo'lsin
        if c.first_order_at:
            Customer.objects.filter(pk=c.pk).update(created_at=c.first_order_at - timedelta(minutes=5))
    wd = today.weekday()
    Promo.objects.create(name="Happy hour −15%", description="Har kuni 15:00–17:00 butun menyuga", value=15,
                         hour_from=15, hour_to=17, max_discount=40000, used_count=46, discount_total=412000, revenue_total=2_950_000)
    Promo.objects.create(name="Tug'ilgan kun −20%", description="Tug'ilgan kunidan ±3 kun", value=20, audience="birthday",
                         max_discount=60000, used_count=9, discount_total=118000, revenue_total=640_000)
    Promo.objects.create(name="Birinchi buyurtma −10 000", description="Telegram va saytdan yangi mijozlar uchun", kind="fixed",
                         value=10000, audience="new", min_order=50000, used_count=21, discount_total=210000, revenue_total=1_480_000)
    Promo.objects.create(name="LAZZAT10 promokod", description="Instagram reklamasi uchun", code="LAZZAT10", value=10,
                         ends_on=today + timedelta(days=20), weekdays=[(wd + k) % 7 for k in range(7)], used_count=14,
                         discount_total=86000, revenue_total=870_000)
    return len(customers)
