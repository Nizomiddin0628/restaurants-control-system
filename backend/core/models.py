"""
Yadro modellari (har tenant sxemasida): foydalanuvchi, rol, a'zolik, filial, audit, OTP.
"""
from __future__ import annotations

import secrets
import uuid

from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models
from django.utils import timezone


class TimeStamped(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class SoftDelete(models.Model):
    deleted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        abstract = True

    def soft_delete(self):
        self.deleted_at = timezone.now()
        self.save(update_fields=["deleted_at"])


# ------------------------------------------------------------------ users
class UserManager(BaseUserManager):
    def create_user(self, phone: str, password: str | None = None, **extra):
        if not phone:
            raise ValueError("Telefon raqam shart")
        user = self.model(phone=self.normalize_phone(phone), **extra)
        user.set_password(password) if password else user.set_unusable_password()
        user.save(using=self._db)
        return user

    def create_superuser(self, phone: str, password: str | None = None, **extra):
        extra.setdefault("is_staff", True)
        extra.setdefault("is_superuser", True)
        return self.create_user(phone, password, **extra)

    @staticmethod
    def normalize_phone(phone: str) -> str:
        digits = "".join(ch for ch in phone if ch.isdigit())
        if len(digits) == 9:
            digits = "998" + digits
        return "+" + digits


class User(AbstractBaseUser, PermissionsMixin, TimeStamped):
    """Telefon raqam = login. Parol ixtiyoriy (OTP bilan kirish asosiy)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    phone = models.CharField(max_length=20, unique=True)
    full_name = models.CharField(max_length=120, blank=True)
    email = models.EmailField(blank=True)
    language = models.CharField(max_length=5, default="uz")
    avatar = models.ImageField(upload_to="avatars/", blank=True)
    pin_hash = models.CharField(max_length=128, blank=True, help_text="Kassa/tasdiqlash PIN (hash)")
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    telegram_id = models.BigIntegerField(null=True, blank=True)
    last_seen_at = models.DateTimeField(null=True, blank=True)
    extra_permissions = models.JSONField(default=list, blank=True,
                                         help_text="Roldan tashqari shaxsiy ruxsatlar (masalan ['ai.use', 'inventory.view'])")

    USERNAME_FIELD = "phone"
    REQUIRED_FIELDS: list[str] = []
    objects = UserManager()

    class Meta:
        ordering = ["full_name"]

    def __str__(self) -> str:
        return self.full_name or self.phone

    # ---- PIN
    def set_pin(self, pin: str):
        from django.contrib.auth.hashers import make_password
        self.pin_hash = make_password(pin)

    def check_pin(self, pin: str) -> bool:
        from django.contrib.auth.hashers import check_password
        return bool(self.pin_hash) and check_password(pin, self.pin_hash)

    # ---- ruxsatlar (rol orqali)
    def tenant_permissions(self) -> set[str]:
        perms: set[str] = set(self.extra_permissions or [])
        for m in self.memberships.select_related("role").filter(is_active=True):
            perms.update(m.role.permissions or [])
        return perms

    def role_permissions(self) -> set[str]:
        perms: set[str] = set()
        for m in self.memberships.select_related("role").filter(is_active=True):
            perms.update(m.role.permissions or [])
        return perms

    def access_level(self) -> int:
        """Ierarxiya darajasi: Superadmin (egasi) 100, Bosh menejer 80, Filial menejeri 60, xodim 10."""
        if self.is_superuser:
            return 1000
        return max([m.role.level for m in self.memberships.select_related("role").filter(is_active=True)] or [0])

    def branch_scope(self) -> set[int] | None:
        """None — barcha filiallar; aks holda ruxsat etilgan filiallar id'lari (a'zoliklardagi filiallar birlashmasi)."""
        if self.is_superuser:
            return None
        ms = list(self.memberships.filter(is_active=True).select_related("role").prefetch_related("branches"))
        if not ms:
            return None
        ids: set[int] = set()
        for m in ms:
            bs = {b.pk for b in m.branches.all()}
            if not bs or m.role.level >= 80:
                return None
            ids |= bs
        return ids

    def has_perm_code(self, code: str) -> bool:
        """`catalog.product.edit` → rolda 'catalog.product.edit' | 'catalog.*' | '*' bo'lsa True."""
        if self.is_superuser:
            return True
        perms = self.tenant_permissions()
        if "*" in perms or code in perms:
            return True
        parts = code.split(".")
        for i in range(1, len(parts)):
            if ".".join(parts[:i]) + ".*" in perms:
                return True
        return False


# ------------------------------------------------------------------ roles
class Role(TimeStamped):
    """Egasi o'zi tahrirlaydigan rol: ruxsatlar ro'yxati (matritsa)."""

    code = models.SlugField(max_length=40)
    name = models.CharField(max_length=80)
    permissions = models.JSONField(default=list, help_text="['catalog.*', 'core.settings.view', ...] yoki ['*']")
    is_system = models.BooleanField(default=False, help_text="owner kabi o'chirib bo'lmaydigan rollar")
    requires_pin_for = models.JSONField(default=list, help_text="PIN talab qilinadigan harakatlar")
    level = models.PositiveSmallIntegerField(default=10, help_text="100 Superadmin · 80 Bosh menejer · 60 Filial menejeri · 10 xodim")
    description = models.CharField(max_length=200, blank=True)

    class Meta:
        unique_together = [("code",)]
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class Branch(TimeStamped, SoftDelete):
    """Filial. Ombor, kassa, hodimlar shu obyektga bog'lanadi."""

    name = models.CharField(max_length=120)
    address = models.CharField(max_length=255, blank=True)
    phone = models.CharField(max_length=20, blank=True)
    lat = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    lng = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    working_hours = models.JSONField(default=dict, help_text='{"mon": ["09:00", "02:00"], ...}')
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=0)
    settings = models.JSONField(default=dict)
    disabled_modules = models.JSONField(default=list, help_text="shu filialda o'chirilgan modullar")

    class Meta:
        ordering = ["sort_order", "name"]

    def __str__(self) -> str:
        return self.name


class Membership(TimeStamped):
    """Foydalanuvchi ↔ rol ↔ filiallar. Bo'sh branches = barcha filiallar."""

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="memberships")
    role = models.ForeignKey(Role, on_delete=models.PROTECT, related_name="memberships")
    branches = models.ManyToManyField(Branch, blank=True, related_name="memberships")
    is_active = models.BooleanField(default=True)

    class Meta:
        unique_together = [("user", "role")]


# ------------------------------------------------------------------ audit
class AuditLog(models.Model):
    """Har o'zgarish: kim, qachon, nima, oldingi/keyingi qiymat. Undo uchun asos."""

    id = models.BigAutoField(primary_key=True)
    at = models.DateTimeField(auto_now_add=True, db_index=True)
    actor = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL)
    action = models.CharField(max_length=40)          # create | update | delete | publish | enable_module ...
    model = models.CharField(max_length=80, db_index=True)
    object_id = models.CharField(max_length=64, blank=True)
    before = models.JSONField(null=True, blank=True)
    after = models.JSONField(null=True, blank=True)
    request_id = models.CharField(max_length=40, blank=True)
    ip = models.GenericIPAddressField(null=True, blank=True)

    class Meta:
        ordering = ["-at"]


# ------------------------------------------------------------------ otp
class OtpCode(models.Model):
    """Telefonga yuborilgan bir martalik kod (SMS/Telegram). Dev'da javobda qaytariladi."""

    phone = models.CharField(max_length=20, db_index=True)
    code = models.CharField(max_length=6)
    purpose = models.CharField(max_length=20, default="login")
    created_at = models.DateTimeField(auto_now_add=True)
    used_at = models.DateTimeField(null=True, blank=True)
    attempts = models.PositiveSmallIntegerField(default=0)

    @classmethod
    def issue(cls, phone: str, purpose: str = "login") -> "OtpCode":
        code = f"{secrets.randbelow(10**6):06d}"
        return cls.objects.create(phone=phone, code=code, purpose=purpose)

    def is_valid(self, ttl_seconds: int) -> bool:
        return self.used_at is None and self.attempts < 5 and (timezone.now() - self.created_at).total_seconds() < ttl_seconds


class LoginRequest(models.Model):
    """Telegram orqali kirish: saytda telefon kiritiladi → botga «Kirishni tasdiqlaysizmi?» → «Ha» bosilsa sayt o'zi kiradi."""

    PENDING, OK, NO, USED = "pending", "ok", "no", "used"
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="login_requests")
    status = models.CharField(max_length=10, default=PENDING)
    secret = models.CharField(max_length=64, help_text="brauzerdagi so'rov kaliti (boshqa odam tokenni ololmasin)")
    ip = models.CharField(max_length=64, blank=True)
    device = models.CharField(max_length=160, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    decided_at = models.DateTimeField(null=True, blank=True)

    TTL = 180   # soniya

    class Meta:
        ordering = ["-created_at"]

    @property
    def expired(self) -> bool:
        return (timezone.now() - self.created_at).total_seconds() > self.TTL


class Device(TimeStamped):
    """Ro'yxatdan o'tgan qurilma (kassa, KDS, TV). Token bilan ulanadi, paneldan o'chiriladi."""

    KIND = [("pos", "Kassa"), ("kds", "Oshxona ekrani"), ("tv", "TV"), ("kiosk", "Kiosk")]
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    branch = models.ForeignKey(Branch, on_delete=models.CASCADE, related_name="devices")
    kind = models.CharField(max_length=10, choices=KIND, default="pos")
    name = models.CharField(max_length=80)
    token = models.CharField(max_length=64, unique=True, default=secrets.token_urlsafe)
    is_active = models.BooleanField(default=True)
    last_seen_at = models.DateTimeField(null=True, blank=True)

    def __str__(self) -> str:
        return f"{self.get_kind_display()} · {self.name}"
