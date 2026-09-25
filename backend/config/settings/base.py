"""
RestoPOS — asosiy sozlamalar (barcha muhitlar uchun umumiy).

Multi-tenant: django-tenants (har restoran = alohida PostgreSQL sxemasi, bitta kod).
"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent

# .env (repo ildizida yoki backend/ ichida) — bo'lsa o'qiladi, muhit o'zgaruvchilari ustun turadi
try:
    from dotenv import load_dotenv
    for _env in (BASE_DIR.parent / ".env", BASE_DIR / ".env"):
        if _env.exists():
            load_dotenv(_env, override=False)
except ImportError:  # pragma: no cover
    pass

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "dev-only-secret-change-me")
DEBUG = False
ALLOWED_HOSTS = ["*"]  # domenlar django-tenants Domain jadvalida tekshiriladi

# ------------------------------------------------------------------ apps
# public sxemada yashaydigan ilovalar (tenant ro'yxati, tariflar, platforma foydalanuvchilari)
SHARED_APPS = [
    "django_tenants",
    "public",
    "django.contrib.contenttypes",
    "django.contrib.auth",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.admin",
    "corsheaders",
    "simple_history",
    "core",
    "website",
]

# har tenant sxemasida yashaydigan ilovalar (restoran ma'lumotlari)
TENANT_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.auth",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.admin",
    "simple_history",
    "core",
    # modullar — har biri yoqiladigan/o'chiriladigan birlik (core/modules.py registri)
    "modules.catalog",
    "modules.cms",
    "modules.tasks",
    "modules.inventory",
    "modules.pos",
    "modules.payments",
    "modules.hr",
    "modules.finance",
    "modules.kds",
    "modules.tables",
    "modules.reservations",
    "modules.training",
    "modules.telegram",
]

INSTALLED_APPS = SHARED_APPS + [a for a in TENANT_APPS if a not in SHARED_APPS]

TENANT_MODEL = "public.Tenant"
TENANT_DOMAIN_MODEL = "public.Domain"
PUBLIC_SCHEMA_URLCONF = "config.urls_public"
# noma'lum domen (IP, healthcheck) → 404 emas, platforma sayti (public sxema)
SHOW_PUBLIC_IF_NO_TENANT_FOUND = True
ROOT_URLCONF = "config.urls"

AUTH_USER_MODEL = "core.User"

MIDDLEWARE = [
    "django_tenants.middleware.main.TenantMainMiddleware",  # BIRINCHI: domen → tenant → search_path
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "core.middleware.IdempotencyMiddleware",
    "core.middleware.RequestIdMiddleware",
]

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "website" / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

# ------------------------------------------------------------------ database
DATABASES = {
    "default": {
        "ENGINE": "django_tenants.postgresql_backend",
        "NAME": os.environ.get("POSTGRES_DB", "restopos"),
        "USER": os.environ.get("POSTGRES_USER", "restopos"),
        "PASSWORD": os.environ.get("POSTGRES_PASSWORD", "restopos"),
        "HOST": os.environ.get("POSTGRES_HOST", "localhost"),
        "PORT": os.environ.get("POSTGRES_PORT", "5432"),
        "CONN_MAX_AGE": 60,
    }
}
DATABASE_ROUTERS = ("django_tenants.routers.TenantSyncRouter",)
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ------------------------------------------------------------------ cache / redis
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": REDIS_URL,
        "KEY_FUNCTION": "django_tenants.cache.make_key",
        "REVERSE_KEY_FUNCTION": "django_tenants.cache.reverse_key",
    }
}

# ------------------------------------------------------------------ celery
CELERY_BROKER_URL = os.environ.get("CELERY_BROKER_URL", REDIS_URL)
CELERY_RESULT_BACKEND = os.environ.get("CELERY_RESULT_BACKEND", REDIS_URL)
CELERY_TASK_DEFAULT_QUEUE = "default"
CELERY_TASK_QUEUES = {
    "critical": {"exchange": "critical"},  # fiskal chek, to'lov callback
    "default": {"exchange": "default"},    # push, SMS, import
    "bulk": {"exchange": "bulk"},          # hisobot, stat.uz, eksport
}
CELERY_TASK_ACKS_LATE = True
CELERY_WORKER_PREFETCH_MULTIPLIER = 1

# ------------------------------------------------------------------ i18n
LANGUAGE_CODE = "uz"
LANGUAGES = [("uz", "O'zbekcha"), ("ru", "Русский"), ("en", "English")]
TIME_ZONE = "Asia/Tashkent"
USE_I18N = True
USE_TZ = True

# ------------------------------------------------------------------ static / media
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "website" / "static"]
STORAGES = {
    "default": {"BACKEND": "django_tenants.files.storage.TenantFileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"
MULTITENANT_RELATIVE_MEDIA_ROOT = "%s"  # media/<schema>/...

# ------------------------------------------------------------------ auth / api
JWT_SECRET = os.environ.get("JWT_SECRET", SECRET_KEY)
JWT_ACCESS_MINUTES = int(os.environ.get("JWT_ACCESS_MINUTES", "720"))
OTP_TTL_SECONDS = 300
OTP_DEV_ECHO = False  # dev.py da True: OTP kodi javobda qaytariladi (SMS shart emas)

CORS_ALLOW_ALL_ORIGINS = False
CORS_ALLOWED_ORIGIN_REGEXES = [r"^https?://([a-z0-9-]+\.)?localhost(:\d+)?$"]
CORS_ALLOW_CREDENTIALS = True

NINJA_PAGINATION_PER_PAGE = 50

# ------------------------------------------------------------------ platform
PLATFORM_DOMAIN = os.environ.get("PLATFORM_DOMAIN", "localhost")
PLATFORM_NAME = "RestoPOS"
VITE_DEV = os.environ.get("VITE_DEV") == "1"      # 1 → /admin Vite dev-serverdan (HMR) yuklanadi
VITE_URL = os.environ.get("VITE_URL", "http://localhost:5173")

# ------------------------------------------------------------------ logging
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"std": {"format": "%(asctime)s %(levelname)s [%(name)s] %(message)s"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "std"}},
    "root": {"handlers": ["console"], "level": "INFO"},
}
