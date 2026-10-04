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
    amount = models.BigIntegerField(default=0, help_text="so'm")
    status = models.CharField(max_length=10, choices=InvoiceStatus.choices, default=InvoiceStatus.PENDING)
    due_date = models.DateField(null=True, blank=True)
    paid_at = models.DateTimeField(null=True, blank=True)
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


class Ticket(models.Model):
    number = models.PositiveIntegerField(unique=True, editable=False)
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="tickets")
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
    updated_at = models.DateTimeField(auto_now=True)

    DEFAULT_INCLUDES = ["Server va zaxira nusxa (har kuni)", "Domen va SSL (https)", "Barcha modullar va yangilanishlar",
                        "Telegram bot va restoran sayti", "Qo'llab-quvvatlash (Telegram, telefon)", "Ma'lumotlar xavfsizligi va alohida baza"]

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
