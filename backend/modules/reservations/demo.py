"""Demo: bugungi va ertangi bronlar + navbatda ikki mehmon."""
import random
from datetime import timedelta

from django.utils import timezone

from modules.tables.models import Table

from .models import Reservation, ReservationStatus, WaitlistEntry

NAMES = ["Akmal Rasulov", "Dilnoza Karimova", "Jasur Xolmatov", "Nigora Yusupova", "Sardor Aliyev",
         "Kamola Tosheva", "Bekzod Ismoilov", "Malika Nazarova"]
OCCASIONS = ["", "tug'ilgan kun", "ish uchrashuvi", "", "oilaviy"]


def seed_demo_reservations() -> int:
    if Reservation.objects.exists():
        return 0
    random.seed(11)
    tables = list(Table.objects.filter(is_active=True))
    if not tables:
        return 0
    now = timezone.localtime()
    base = now.replace(hour=12, minute=0, second=0, microsecond=0)
    n = 0
    for i, name in enumerate(NAMES):
        day = 0 if i < 5 else 1
        at = base + timedelta(days=day, hours=i % 5 * 2, minutes=30 * (i % 2))
        st = ReservationStatus.CONFIRMED if i % 3 else ReservationStatus.NEW
        Reservation.objects.create(
            guest_name=name, phone=f"+9989{random.randint(0, 9)}{random.randint(1000000, 9999999)}",
            guests=random.choice([2, 2, 4, 4, 6]), table=random.choice(tables), starts_at=at,
            duration_minutes=90, status=st, source=random.choice(["phone", "hall", "telegram"]),
            occasion=random.choice(OCCASIONS),
        )
        n += 1
    WaitlistEntry.objects.create(guest_name="Oybek", phone="+998901112233", guests=3, quoted_minutes=15)
    WaitlistEntry.objects.create(guest_name="Zilola", guests=2, quoted_minutes=25)
    return n