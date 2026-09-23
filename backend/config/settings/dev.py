"""Dasturchi muhiti."""
from .base import *  # noqa

DEBUG = True
OTP_DEV_ECHO = True          # OTP kodi API javobida qaytadi — SMS shart emas
CORS_ALLOW_ALL_ORIGINS = True
CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
CELERY_TASK_ALWAYS_EAGER = True   # fon vazifalar darhol, brokersiz
STORAGES["staticfiles"] = {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
