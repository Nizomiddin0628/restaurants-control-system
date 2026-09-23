"""Ishlab chiqarish muhiti — barcha sirlar muhit o'zgaruvchilaridan."""
import os

from .base import *  # noqa

DEBUG = False
SECRET_KEY = os.environ["DJANGO_SECRET_KEY"]
JWT_SECRET = os.environ["JWT_SECRET"]
ALLOWED_HOSTS = os.environ.get("ALLOWED_HOSTS", "*").split(",")
CSRF_TRUSTED_ORIGINS = os.environ.get("CSRF_TRUSTED_ORIGINS", "").split(",") if os.environ.get("CSRF_TRUSTED_ORIGINS") else []
CORS_ALLOWED_ORIGIN_REGEXES = [r"^https://([a-z0-9-]+\.)?" + os.environ.get("PLATFORM_DOMAIN", "restopos.uz").replace(".", r"\.") + "$"]
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = 31536000

# Media: S3-mos ombor (MinIO / UzCloud object storage)
if os.environ.get("AWS_STORAGE_BUCKET_NAME"):
    STORAGES["default"] = {
        "BACKEND": "storages.backends.s3.S3Storage",
        "OPTIONS": {
            "bucket_name": os.environ["AWS_STORAGE_BUCKET_NAME"],
            "endpoint_url": os.environ.get("AWS_S3_ENDPOINT_URL"),
            "access_key": os.environ.get("AWS_ACCESS_KEY_ID"),
            "secret_key": os.environ.get("AWS_SECRET_ACCESS_KEY"),
            "region_name": os.environ.get("AWS_S3_REGION_NAME", "us-east-1"),
            "default_acl": "public-read",
            "querystring_auth": False,
        },
    }
