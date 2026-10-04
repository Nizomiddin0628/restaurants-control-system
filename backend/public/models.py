"""
Public sxema modellari: tenantlar (restoranlar), domenlar, tariflar.

Har Tenant = alohida PostgreSQL sxemasi (django-tenants). Kod bitta, ma'lumot alohida.
"""
from django.db import models
from django_tenants.models import DomainMixin, TenantMixin

from core.presets import PRESETS


class Plan(models.Model):
    """Tarif: qaysi modullar mavjud, limitlar, oylik narx (so'm)."""

    code = models.SlugField(unique=True)
    name = models.CharField(max_length=80)
    price_per_branch = models.BigIntegerField(default=0, help_text="so'm / filial / oy")
    max_branches = models.PositiveIntegerField(default=1)
    max_devices = models.PositiveIntegerField(default=2)
    allowed_modules = models.JSONField(default=list, help_text="modul kodlari ro'yxati; ['*'] = hammasi")
    is_active = models.BooleanField(default=True)

    def __str__(self) -> str:
        return self.name

    def allows(self, module_code: str) -> bool:
        return "*" in self.allowed_modules or module_code in self.allowed_modules


class Tenant(TenantMixin):
    """Bitta restoran / tarmoq. `schema_name` = PostgreSQL sxemasi."""

    PRESET_CHOICES = [(k, v["name"]) for k, v in PRESETS.items()]

    name = models.CharField(max_length=120)
    slug = models.SlugField(unique=True, help_text="subdomen: <slug>.restopos.uz")
    preset = models.CharField(max_length=32, choices=PRESET_CHOICES, default="fast_food")
    plan = models.ForeignKey(Plan, null=True, blank=True, on_delete=models.SET_NULL)
    enabled_modules = models.JSONField(default=list, help_text="yoqilgan modul kodlari")
    settings = models.JSONField(default=dict, help_text="tenant darajasidagi sozlamalar (tillar, valyuta, soliq rejimi...)")
    owner_phone = models.CharField(max_length=20, blank=True)
    is_active = models.BooleanField(default=True)
    trial_ends_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    # hudud (HQ'da guruhlash, xarita, sotuv hisobotlari)
    region = models.CharField(max_length=60, blank=True, default="", db_index=True, help_text="viloyat / Toshkent shahri")
    district = models.CharField(max_length=60, blank=True, default="", help_text="tuman / shahar")
    address = models.CharField(max_length=200, blank=True, default="")
    # restoranga xos chegaralar (0 — tarif bo'yicha / cheklovsiz): {"branches": 3, "users": 40}
    limits = models.JSONField(default=dict, blank=True)

    auto_create_schema = True   # save() da sxema + migratsiyalar avtomatik
    auto_drop_schema = False    # xavfsizlik: o'chirishda sxema saqlanadi

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return f"{self.name} ({self.schema_name})"

    # ---- modullar
    def module_enabled(self, code: str) -> bool:
        return code in (self.enabled_modules or [])

    def can_enable(self, code: str) -> bool:
        return self.plan is None or self.plan.allows(code)

    def limit(self, key: str) -> int:
        """Restoranga xos chegara (shartnoma) → bo'lmasa tarif chegarasi → 0 (cheklovsiz)."""
        v = int((self.limits or {}).get(key) or 0)
        if v:
            return v
        if key == "branches" and self.plan:
            return self.plan.max_branches
        return 0


class Domain(DomainMixin):
    """Tenantga bog'langan domenlar: lazzat.restopos.uz, lazzat.uz ..."""

    def __str__(self) -> str:
        return self.domain


# ====================================================================== RESTROOS HQ (platforma paneli)
# Barcha restoranlarni bitta joydan ko'rish: statistika, billing, yordam, tizim holati, funksiya bayroqlari.
# Restoran ichiga kirish — faqat egasi vaqtincha ruxsat berganda (SupportAccess), har kirish yoziladi (SupportSession).

class StaffRole(models.TextChoices):
    FOUNDER = "founder", "Asoschi (founder)"
    DEVELOPER = "developer", "Dasturchi (developer)"
    SUPERADMIN = "superadmin", "Bosh administrator"
    SUPPORT = "support", "Texnik yordam"
    SALES = "sales", "Sotuv"
    FINANCE = "finance", "Moliya"


# Butun platforma rahbarlari: har qanday restoranga (egasining ruxsatisiz) kira oladi, tarif/limitlarni boshqaradi
TOP_ROLES = ("founder", "developer", "superadmin")
# Restoran paneliga egasining ruxsatisiz kira oladiganlar (har kirish yoziladi)
DIRECT_ROLES = ("founder", "developer")


class PlatformStaff(models.Model):
    """Platforma jamoasi a'zosi (public sxemadagi core.User)."""

    user = models.OneToOneField("core.User", on_delete=models.CASCADE, related_name="platform_staff")
    role = models.CharField(max_length=12, choices=StaffRole.choices, default=StaffRole.SUPPORT)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return f"{self.user} ({self.role})"


class TenantStat(models.Model):
    """Kunlik yig'ma: bir restoranning bir kunlik savdosi va o'sha kundagi holat (xodimlar, filiallar…)."""

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="stats")
    date = models.DateField(db_index=True)
    revenue = models.BigIntegerField(default=0)
    orders = models.PositiveIntegerField(default=0)
    cost = models.BigIntegerField(default=0, help_text="tannarx yig'indisi (food cost uchun)")
    employees = models.PositiveIntegerField(default=0)
    branches = models.PositiveIntegerField(default=0)
    customers = models.PositiveIntegerField(default=0)
    users = models.PositiveIntegerField(default=0)
    top_products = models.JSONField(default=list, blank=True, help_text='[{"name": "Choy", "qty": 120}] — shu kun')
    collected_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [("tenant", "date")]
        ordering = ["-date"]


class Contract(models.Model):
    """Restoran bilan shartnoma: tarif, oylik narx, to'lov kuni, bepul davr, yuridik ma'lumot, maxsus shartlar.
    Billing shu yerdan hisoblanadi; shartnomasiz (saytdan o'zi ro'yxatdan o'tgan) restoran — sayt narxlari bo'yicha."""

    BASE, AI = "base", "ai"
    TARIFFS = [(BASE, "Dastur"), (AI, "Dastur + AI Kotib")]
    CURRENCIES = [("USD", "$"), ("UZS", "so'm")]

    tenant = models.OneToOneField(Tenant, on_delete=models.CASCADE, related_name="contract")
    number = models.CharField(max_length=30, unique=True)
    signed_at = models.DateField(null=True, blank=True)
    tariff = models.CharField(max_length=8, choices=TARIFFS, default=BASE)
    price = models.PositiveIntegerField(default=100, help_text="oylik narx (shartnoma bo'yicha)")
    currency = models.CharField(max_length=3, choices=CURRENCIES, default="USD")
    included_branches = models.PositiveIntegerField(default=1, help_text="narx ichidagi filiallar")
    extra_branch_price = models.PositiveIntegerField(default=0, help_text="har qo'shimcha filial uchun oyiga")
    billing_day = models.PositiveSmallIntegerField(default=5, help_text="har oy nechanchi sanada to'laydi (1–28)")
    paid_from = models.DateField(null=True, blank=True, help_text="shu sanadan pullik (undan oldin — bepul davr)")
    company = models.CharField(max_length=160, blank=True, help_text="yuridik nom (MChJ / YaTT)")
    inn = models.CharField(max_length=20, blank=True, help_text="STIR")
    contact_name = models.CharField(max_length=120, blank=True)
    contact_phone = models.CharField(max_length=20, blank=True)
    terms = models.TextField(blank=True, help_text="maxsus kelishuvlar (chegirma, qo'shimcha ish, muddatlar)")
    manager = models.ForeignKey("PlatformStaff", null=True, blank=True, on_delete=models.SET_NULL, related_name="contracts", help_text="mas'ul menejer")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.number} — {self.tenant.name}"

    @classmethod
    def next_number(cls) -> str:
        from django.utils import timezone
        y = timezone.localdate().year
        n = cls.objects.filter(number__startswith=f"RP-{y}-").count() + 1
        while cls.objects.filter(number=f"RP-{y}-{n:04d}").exists():
            n += 1
        return f"RP-{y}-{n:04d}"

    def monthly(self, branches: int) -> int:
        return self.price + max(0, branches - self.included_branches) * self.extra_branch_price


class InvoiceStatus(models.TextChoices):
    PENDING = "pending", "Kutilmoqda"
    PAID = "paid", "To'langan"
    OVERDUE = "overdue", "Muddati o'tgan"
    CANCELLED = "cancelled", "Bekor qilingan"


class Invoice(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="invoices")
    period = models.DateField(help_text="oyning 1-sanasi")
    plan_name = models.CharField(max_length=80, blank=True)
    branches = models.PositiveIntegerField(default=1)
    amount = models.BigIntegerField(default=0)
    currency = models.CharField(max_length=3, default="UZS")
    status = models.CharField(max_length=10, choices=InvoiceStatus.choices, default=InvoiceStatus.PENDING)
    due_date = models.DateField(null=True, blank=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    method = models.CharField(max_length=12, blank=True, help_text="naqd / karta / bank / payme / click")
    note = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("tenant", "period")]
        ordering = ["-period", "tenant__name"]


class TicketStatus(models.TextChoices):
    OPEN = "open", "Ochilgan"
    PROGRESS = "progress", "Jarayonda"
    WAITING = "waiting", "Mijoz kutilmoqda"
    CLOSED = "closed", "Yopilgan"


class TicketPriority(models.TextChoices):
    LOW = "low", "Past"
    NORMAL = "normal", "O'rta"
    HIGH = "high", "Yuqori"
    CRITICAL = "critical", "Kritik"


class TicketKind(models.TextChoices):
    BUG = "bug", "Xato (ishlamayapti)"
    QUESTION = "question", "Savol / yordam"
    FEATURE = "feature", "Taklif / yangi funksiya"
    TASK = "task", "Ichki vazifa"


# Javob/tuzatish muddati (SLA): muhimlik → soat
SLA_HOURS = {"critical": 4, "high": 24, "normal": 72, "low": 168}


class Ticket(models.Model):
    number = models.PositiveIntegerField(unique=True, editable=False)
    tenant = models.ForeignKey(Tenant, null=True, blank=True, on_delete=models.CASCADE, related_name="tickets", help_text="bo'sh — ichki vazifa")
    kind = models.CharField(max_length=10, choices=TicketKind.choices, default=TicketKind.BUG)
    due_at = models.DateTimeField(null=True, blank=True, help_text="hal qilish muddati (SLA)")
    sort = models.FloatField(default=0, help_text="doskadagi tartib (kichigi — yuqorida)")
    branch_name = models.CharField(max_length=120, blank=True)
    author_name = models.CharField(max_length=120, blank=True)
    author_phone = models.CharField(max_length=20, blank=True)
    subject = models.CharField(max_length=200)
    body = models.TextField(blank=True)
    priority = models.CharField(max_length=8, choices=TicketPriority.choices, default=TicketPriority.NORMAL)
    status = models.CharField(max_length=8, choices=TicketStatus.choices, default=TicketStatus.OPEN, db_index=True)
    assigned = models.ForeignKey(PlatformStaff, null=True, blank=True, on_delete=models.SET_NULL, related_name="tickets")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    closed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def save(self, *args, **kwargs):
        if not self.number:
            last = Ticket.objects.order_by("-number").values_list("number", flat=True).first()
            self.number = (last or 10400) + 1
        if self.due_at is None:
            from datetime import timedelta

            from django.utils import timezone
            self.due_at = (self.created_at or timezone.now()) + timedelta(hours=SLA_HOURS.get(self.priority, 72))
        super().save(*args, **kwargs)


class TicketMessage(models.Model):
    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name="messages")
    from_staff = models.BooleanField(default=False)
    author_name = models.CharField(max_length=120, blank=True)
    body = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]


class SupportAccess(models.Model):
    """Egasi bergan vaqtinchalik ruxsat: shu vaqtgacha platforma yordami restoran paneliga kira oladi."""

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="support_grants")
    granted_by = models.CharField(max_length=120, blank=True)
    until = models.DateTimeField()
    reason = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]


class SupportSession(models.Model):
    """Har bir kirish: kim, qachon, nima uchun. Restoran egasi o'z panelida ko'radi."""

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="support_sessions")
    staff = models.ForeignKey(PlatformStaff, null=True, on_delete=models.SET_NULL, related_name="sessions")
    staff_name = models.CharField(max_length=120, blank=True)
    reason = models.CharField(max_length=200, blank=True)
    started_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-started_at"]


class HqAudit(models.Model):
    staff = models.ForeignKey(PlatformStaff, null=True, on_delete=models.SET_NULL)
    staff_name = models.CharField(max_length=120, blank=True)
    action = models.CharField(max_length=60)
    tenant = models.ForeignKey(Tenant, null=True, blank=True, on_delete=models.SET_NULL)
    detail = models.JSONField(default=dict, blank=True)
    at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-at"]


class FeatureFlag(models.Model):
    """Funksiya bayrog'i: yangi imkoniyatni avval bir nechta restoranda sinash (beta), keyin hammaga."""

    code = models.SlugField(unique=True)
    name = models.CharField(max_length=120)
    description = models.CharField(max_length=300, blank=True)
    enabled_all = models.BooleanField(default=False)
    tenants = models.JSONField(default=list, blank=True, help_text="beta: tenant id'lari")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["code"]

    def on_for(self, tenant) -> bool:
        return self.enabled_all or tenant.pk in (self.tenants or [])


class Release(models.Model):
    version = models.CharField(max_length=20)
    title = models.CharField(max_length=160)
    notes = models.TextField(blank=True)
    is_published = models.BooleanField(default=False)
    published_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


class SiteOffer(models.Model):
    """Platforma saytidagi taklif va narxlar — HQ panelidan o'zgartiriladi (bitta yozuv)."""

    currency = models.CharField(max_length=8, default="$")
    base_price = models.PositiveIntegerField(default=100, help_text="Dastur — oyiga")
    ai_price = models.PositiveIntegerField(default=150, help_text="Dastur + AI Kotib — oyiga")
    price_note = models.CharField(max_length=120, default="bitta restoran uchun, oyiga")
    trial_days = models.PositiveIntegerField(default=30)
    free_setup = models.BooleanField(default=True, help_text="Ulash va sozlash bepul (aksiya)")
    setup_note = models.CharField(max_length=200, default="Hozir ulash, menyuni kiritish va xodimlarni o'rgatish — bepul")
    includes = models.JSONField(default=list, blank=True, help_text="narx ichida nimalar bor (ro'yxat)")
    phone = models.CharField(max_length=40, blank=True, default="")
    telegram = models.CharField(max_length=60, blank=True, default="", help_text="masalan: restopos_uz (@ siz)")
    ai_chat = models.BooleanField(default=True, help_text="Saytda AI maslahatchi yoqilgan")
    ai_key = models.CharField(max_length=200, blank=True, default="", help_text="Gemini API kaliti (saytdagi AI uchun); bo'sh — .env yoki restoran kaliti")
    lead_chat = models.CharField(max_length=40, blank=True, default="", help_text="Arizalar yuboriladigan Telegram chat ID (botga /id yozing)")
    price_note_ru = models.CharField(max_length=120, blank=True, default="")
    setup_note_ru = models.CharField(max_length=200, blank=True, default="")
    includes_ru = models.JSONField(default=list, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    DEFAULT_INCLUDES = ["Server va zaxira nusxa (har kuni)", "Domen va SSL (https)", "Barcha modullar va yangilanishlar",
                        "Telegram bot va restoran sayti", "Qo'llab-quvvatlash (Telegram, telefon)", "Ma'lumotlar xavfsizligi va alohida baza"]
    DEFAULT_INCLUDES_RU = ["Сервер и резервные копии (ежедневно)", "Домен и SSL (https)", "Все модули и обновления",
                           "Telegram-бот и сайт ресторана", "Поддержка (Telegram, телефон)", "Безопасность данных и отдельная база"]
    DEFAULT_PRICE_NOTE_RU, DEFAULT_SETUP_NOTE_RU = "за один ресторан, в месяц", "Сейчас подключение, ввод меню и обучение сотрудников — бесплатно"

    def localized(self, lang: str) -> dict:
        """Saytda ko'rsatiladigan matnlar tanlangan tilda (RU bo'sh bo'lsa — standart ruscha)."""
        if lang == "ru":
            return {"price_note": self.price_note_ru or self.DEFAULT_PRICE_NOTE_RU, "setup_note": self.setup_note_ru or self.DEFAULT_SETUP_NOTE_RU,
                    "includes": self.includes_ru or list(self.DEFAULT_INCLUDES_RU)}
        return {"price_note": self.price_note, "setup_note": self.setup_note, "includes": self.includes or []}

    def __str__(self) -> str:
        return f"Taklif: {self.currency}{self.base_price} / {self.currency}{self.ai_price}"

    @classmethod
    def get(cls) -> "SiteOffer":
        o = cls.objects.order_by("pk").first()
        if o is None:
            o = cls.objects.create(includes=list(cls.DEFAULT_INCLUDES))
        return o


class Lead(models.Model):
    """Saytdan kelgan mijoz (AI maslahatchi yoki forma orqali)."""

    NEW, CONTACTED, WON, LOST = "new", "contacted", "won", "lost"
    STATUS = [(NEW, "Yangi"), (CONTACTED, "Bog'lanildi"), (WON, "Mijoz bo'ldi"), (LOST, "Rad etdi")]
    name = models.CharField(max_length=120, blank=True)
    phone = models.CharField(max_length=40)
    business = models.CharField(max_length=160, blank=True, help_text="restoran nomi / turi / filiallar")
    note = models.TextField(blank=True)
    source = models.CharField(max_length=20, default="ai_chat")
    status = models.CharField(max_length=12, choices=STATUS, default=NEW, db_index=True)
    ip = models.CharField(max_length=64, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-id"]

    def __str__(self) -> str:
        return f"{self.name or '—'} {self.phone}"


class ChatSession(models.Model):
    """Saytdagi AI maslahatchi bilan suhbat (mehmon) — sotuv jamoasi o'qib, bog'lanadi."""

    sid = models.CharField(max_length=40, unique=True)
    ip = models.CharField(max_length=64, blank=True)
    ua = models.CharField(max_length=200, blank=True)
    messages = models.JSONField(default=list, blank=True, help_text="[{role: me|ai, text, at}]")
    count = models.PositiveIntegerField(default=0)
    lead = models.ForeignKey(Lead, null=True, blank=True, on_delete=models.SET_NULL, related_name="chats")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True, db_index=True)

    class Meta:
        ordering = ["-updated_at"]

    def __str__(self) -> str:
        return f"{self.sid} ({self.count})"
