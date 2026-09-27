"""JWT autentifikatsiya (Django Ninja uchun) va ruxsat tekshiruvlari."""
from __future__ import annotations

from datetime import datetime, timedelta
from datetime import timezone as dt_tz

import jwt
from django.conf import settings
from ninja.errors import HttpError
from ninja.security import HttpBearer

from .models import User


def issue_token(user: User, schema_name: str) -> str:
    now = datetime.now(dt_tz.utc)
    payload = {
        "sub": str(user.pk), "sch": schema_name,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=settings.JWT_ACCESS_MINUTES)).timestamp()),
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm="HS256")


class JWTAuth(HttpBearer):
    def authenticate(self, request, token: str):
        try:
            payload = jwt.decode(token, settings.JWT_SECRET, algorithms=["HS256"])
        except jwt.PyJWTError:
            return None
        tenant = getattr(request, "tenant", None)
        if tenant is not None and getattr(tenant, "is_active", True) is False:   # HQ to'xtatgan (masalan, to'lov)
            raise HttpError(403, "Restoran obunasi vaqtincha to'xtatilgan. Platforma bilan bog'laning.")
        schema = getattr(tenant, "schema_name", "public")
        if payload.get("sch") != schema:      # boshqa tenant tokeni bu yerda ishlamaydi
            return None
        try:
            user = User.objects.get(pk=payload["sub"], is_active=True)
        except (User.DoesNotExist, ValueError, KeyError):
            return None
        request.user = user
        return user


auth = JWTAuth()


def require_perm(request, code: str):
    user = request.auth
    if user is None or not user.has_perm_code(code):
        raise HttpError(403, f"Ruxsat yo'q: {code}")


def require_module(request, code: str):
    tenant = getattr(request, "tenant", None)
    if tenant is None or not tenant.module_enabled(code):
        raise HttpError(404, f"Modul yoqilmagan: {code}")
