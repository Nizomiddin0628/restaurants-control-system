"""
Zakup (xarid) — restoranning «og'riqli» joyi: kimdan, qayerdan, qanchaga olamiz va bozorchi pulni qanday sarfladi.

  Market        — bozor / ulgurji baza / ishlab chiqaruvchi ombori: bozorchi yuk oladigan joylar ro'yxati.
  SupplierInfo  — inventory.Supplier ga qo'shimcha: turi, toifalar, bozori, Telegram, yetkazib beradimi, to'lov sharti.
  SupplierPrice — narx tarixi (qo'lda, buyurtmadan, bozorlikdan) → narx solishtirish.
  Order/Line    — ta'minotchiga buyurtma: qoralama → yuborildi → tasdiqlandi → qabul qilindi (omborga kirim) / bekor.
  Payment       — ta'minotchiga to'lov → qarzdorlik.
  Trip/Item/Expense — bozorlik: bozorchiga avans, u nima oldi (chek rasmi bilan), taksi/hammol xarajati, qaytgan pul.
"""
from __future__ import annotations

from django.db import models
from django.utils import timezone

from core.models import Branch, TimeStamped, User

# toifalar: kod, nomi, emoji
CATEGORIES = [
    ("meat", "Go'sht", "🥩"), ("poultry", "Tovuq", "🍗"), ("veg", "Sabzavot", "🥕"), ("fruit", "Meva", "🍎"),
    ("dairy", "Sut mahsulotlari", "🥛"), ("oil", "Yog' va moylar", "🫒"), ("grain", "Don, un, guruch", "🌾"),
    ("spice", "Ziravorlar", "🌶️"), ("drinks", "Ichimliklar", "🥤"), ("bread", "Non va shirinlik", "🍞"),
    ("pack", "Qadoqlash", "📦"), ("clean", "Tozalash vositalari", "🧴"), ("other", "Boshqa", "➕"),
]
CAT_CODES = [c[0] for c in CATEGORIES]


class MarketKind(models.TextChoices):
    BAZAAR = "bazaar", "Dehqon bozori"
    WHOLESALE = "wholesale", "Ulgurji baza"
    PRODUCER = "producer", "Ishlab chiqaruvchi ombori"
    CASHCARRY = "cashcarry", "Supermarket / Cash&Carry"
    ONLINE = "online", "Onlayn / yetkazib berish"


class Market(TimeStamped):
    name = models.CharField(max_length=120)
    kind = models.CharField(max_length=10, choices=MarketKind.choices, default=MarketKind.BAZAAR)
    city = models.CharField(max_length=60, default="Toshkent")
    district = models.CharField(max_length=80, blank=True)
    address = models.CharField(max_length=200, blank=True)
    landmark = models.CharField(max_length=160, blank=True, help_text="mo'ljal")
    lat = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    lng = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    hours = models.CharField(max_length=80, blank=True, help_text="05:00–18:00")
    days = models.CharField(max_length=80, blank=True, help_text="har kuni / dushanbadan tashqari")
    categories = models.JSONField(default=list, blank=True)
    tips = models.TextField(blank=True, help_text="bozorchi uchun maslahat: qachon borish, qayerda arzon, parking…")
    phone = models.CharField(max_length=20, blank=True)
    is_builtin = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["-is_active", "name"]

    def __str__(self) -> str:
        return self.name


class SupplierKind(models.TextChoices):
    COMPANY = "company", "Kompaniya"
    BAZAAR = "bazaar", "Bozor sotuvchisi"
    FARMER = "farmer", "Fermer"
    PRODUCER = "producer", "Ishlab chiqaruvchi"


class PayTerms(models.TextChoices):
    CASH = "cash", "Naqd, darhol"
    TRANSFER = "transfer", "O'tkazma"
    CREDIT = "credit", "Nasiya (keyin to'lash)"


class SupplierInfo(TimeStamped):
    supplier = models.OneToOneField("inventory.Supplier", on_delete=models.CASCADE, related_name="info")
    kind = models.CharField(max_length=10, choices=SupplierKind.choices, default=SupplierKind.COMPANY)
    categories = models.JSONField(default=list, blank=True)
    market = models.ForeignKey(Market, null=True, blank=True, on_delete=models.SET_NULL, related_name="suppliers")
    contact_name = models.CharField(max_length=120, blank=True)
    telegram = models.CharField(max_length=64, blank=True, help_text="@username yoki telefon")
    address = models.CharField(max_length=200, blank=True)
    delivers = models.BooleanField(default=False)
    min_order = models.CharField(max_length=60, blank=True, help_text="masalan: 20 kg dan")
    terms = models.CharField(max_length=10, choices=PayTerms.choices, default=PayTerms.CASH)
    credit_days = models.PositiveSmallIntegerField(default=0)
    photo_url = models.URLField(max_length=500, blank=True)


class PriceSource(models.TextChoices):
    MANUAL = "manual", "Qo'lda"
    ORDER = "order", "Buyurtma"
    TRIP = "trip", "Bozorlik"


class SupplierPrice(models.Model):
    supplier = models.ForeignKey("inventory.Supplier", null=True, blank=True, on_delete=models.CASCADE, related_name="prices")
    market = models.ForeignKey(Market, null=True, blank=True, on_delete=models.SET_NULL, related_name="prices")
    ingredient = models.ForeignKey("inventory.Ingredient", on_delete=models.CASCADE, related_name="market_prices")
    price = models.BigIntegerField(help_text="so'm / bazaviy birlik")
    date = models.DateField(default=timezone.localdate, db_index=True)
    source = models.CharField(max_length=8, choices=PriceSource.choices, default=PriceSource.MANUAL)
    note = models.CharField(max_length=120, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date", "-id"]
        indexes = [models.Index(fields=["ingredient", "date"])]


class OrderStatus(models.TextChoices):
    DRAFT = "draft", "Qoralama"
    SENT = "sent", "Yuborildi"
    CONFIRMED = "confirmed", "Tasdiqlandi"
    RECEIVED = "received", "Qabul qilindi"
    CANCELLED = "cancelled", "Bekor qilindi"


class Order(TimeStamped):
    number = models.PositiveIntegerField(unique=True, editable=False)
    supplier = models.ForeignKey("inventory.Supplier", on_delete=models.PROTECT, related_name="orders")
    branch = models.ForeignKey(Branch, null=True, blank=True, on_delete=models.SET_NULL)
    status = models.CharField(max_length=10, choices=OrderStatus.choices, default=OrderStatus.DRAFT, db_index=True)
    expected_date = models.DateField(null=True, blank=True)
    note = models.CharField(max_length=240, blank=True)
    total = models.BigIntegerField(default=0)
    created_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    sent_at = models.DateTimeField(null=True, blank=True)
    received_at = models.DateTimeField(null=True, blank=True)
    purchase_id = models.PositiveIntegerField(null=True, blank=True, help_text="inventory.Purchase (omborga kirim)")
    rating = models.PositiveSmallIntegerField(null=True, blank=True, help_text="1–5: sifat va o'z vaqtida")
    rating_note = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def save(self, *args, **kwargs):
        if not self.number:
            last = Order.objects.order_by("-number").values_list("number", flat=True).first()
            self.number = (last or 100) + 1
        super().save(*args, **kwargs)


class OrderLine(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="lines")
    ingredient = models.ForeignKey("inventory.Ingredient", on_delete=models.PROTECT)
    qty = models.DecimalField(max_digits=12, decimal_places=3)
    price = models.BigIntegerField(default=0)
    received_qty = models.DecimalField(max_digits=12, decimal_places=3, null=True, blank=True)


class PayMethod(models.TextChoices):
    CASH = "cash", "Naqd"
    CARD = "card", "Karta"
    TRANSFER = "transfer", "O'tkazma"


class Payment(TimeStamped):
    supplier = models.ForeignKey("inventory.Supplier", on_delete=models.CASCADE, related_name="payments")
    order = models.ForeignKey(Order, null=True, blank=True, on_delete=models.SET_NULL, related_name="payments")
    amount = models.BigIntegerField()
    date = models.DateField(default=timezone.localdate)
    method = models.CharField(max_length=10, choices=PayMethod.choices, default=PayMethod.CASH)
    note = models.CharField(max_length=160, blank=True)
    created_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")

    class Meta:
        ordering = ["-date", "-id"]


# ------------------------------------------------------------------ bozorlik (bozorchi hisoboti)
class TripStatus(models.TextChoices):
    PLANNED = "planned", "Rejada"
    ACTIVE = "active", "Bozorda"
    CLOSED = "closed", "Hisob yopildi"
    CANCELLED = "cancelled", "Bekor"


class Trip(TimeStamped):
    number = models.PositiveIntegerField(unique=True, editable=False)
    date = models.DateField(default=timezone.localdate, db_index=True)
    buyer = models.ForeignKey(User, on_delete=models.PROTECT, related_name="market_trips")
    branch = models.ForeignKey(Branch, null=True, blank=True, on_delete=models.SET_NULL)
    market = models.ForeignKey(Market, null=True, blank=True, on_delete=models.SET_NULL, related_name="trips")
    status = models.CharField(max_length=10, choices=TripStatus.choices, default=TripStatus.ACTIVE, db_index=True)
    advance = models.BigIntegerField(default=0, help_text="bozorchiga berilgan pul")
    returned = models.BigIntegerField(default=0, help_text="bozordan keyin qaytarilgan pul")
    note = models.CharField(max_length=240, blank=True)
    overhead_to_cost = models.BooleanField(default=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    closed_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    purchase_id = models.PositiveIntegerField(null=True, blank=True)
    created_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")

    class Meta:
        ordering = ["-date", "-number"]

    def save(self, *args, **kwargs):
        if not self.number:
            last = Trip.objects.order_by("-number").values_list("number", flat=True).first()
            self.number = (last or 0) + 1
        super().save(*args, **kwargs)


class TripItem(TimeStamped):
    trip = models.ForeignKey(Trip, on_delete=models.CASCADE, related_name="items")
    ingredient = models.ForeignKey("inventory.Ingredient", null=True, blank=True, on_delete=models.SET_NULL)
    name = models.CharField(max_length=120)
    unit = models.CharField(max_length=8, default="kg")
    planned_qty = models.DecimalField(max_digits=12, decimal_places=3, default=0, help_text="ro'yxatdagi (reja)")
    qty = models.DecimalField(max_digits=12, decimal_places=3, default=0, help_text="haqiqatda olingan")
    price = models.BigIntegerField(default=0, help_text="1 birlik narxi")
    total = models.BigIntegerField(default=0)
    seller = models.CharField(max_length=120, blank=True)
    photo = models.ImageField(upload_to="procurement/receipts/%Y/%m/", blank=True)

    class Meta:
        ordering = ["id"]


class ExpenseKind(models.TextChoices):
    TAXI = "taxi", "Taksi / transport"
    PORTER = "porter", "Hammol / yuk ortish"
    FUEL = "fuel", "Yoqilg'i"
    FEE = "fee", "Bozor to'lovi / joy"
    PACK = "pack", "Qop, paket, idish"
    FOOD = "food", "Ovqat"
    OTHER = "other", "Boshqa"


class TripExpense(TimeStamped):
    trip = models.ForeignKey(Trip, on_delete=models.CASCADE, related_name="expenses")
    kind = models.CharField(max_length=8, choices=ExpenseKind.choices, default=ExpenseKind.TAXI)
    amount = models.BigIntegerField()
    note = models.CharField(max_length=160, blank=True)
    photo = models.ImageField(upload_to="procurement/receipts/%Y/%m/", blank=True)

    class Meta:
        ordering = ["id"]
