"""
Yadro middleware'lari: so'rov id (loglar uchun) va idempotentlik (takror yozuvlarga qarshi).
"""
from __future__ import annotations

import hashlib
import json
import uuid

from django.core.cache import cache
from django.http import HttpResponse

IDEMPOTENT_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
IDEMPOTENCY_TTL = 60 * 60 * 24  # 24 soat


class RequestIdMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.request_id = request.headers.get("X-Request-Id") or uuid.uuid4().hex[:16]
        response = self.get_response(request)
        response["X-Request-Id"] = request.request_id
        return response


class IdempotencyMiddleware:
    """
    Mijoz `Idempotency-Key` sarlavhasini yuborsa, o'sha kalit bilan takror so'rov birinchi javobni qaytaradi.
    Kalit tenant + yo'l + foydalanuvchi/qurilma bo'yicha ajratiladi. Kassa offline sinxroni shunga tayanadi.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        key = request.headers.get("Idempotency-Key")
        if not key or request.method not in IDEMPOTENT_METHODS:
            return self.get_response(request)

        schema = getattr(getattr(request, "tenant", None), "schema_name", "public")
        actor = request.headers.get("Authorization", "")[-24:]
        cache_key = "idem:" + hashlib.sha256(f"{schema}|{actor}|{request.path}|{key}".encode()).hexdigest()

        cached = cache.get(cache_key)
        if cached:
            resp = HttpResponse(cached["body"], status=cached["status"], content_type=cached["content_type"])
            resp["Idempotent-Replayed"] = "true"
            return resp

        response = self.get_response(request)
        if 200 <= response.status_code < 300 and hasattr(response, "content"):
            cache.set(cache_key, {
                "body": response.content, "status": response.status_code,
                "content_type": response.get("Content-Type", "application/json"),
            }, IDEMPOTENCY_TTL)
        return response


def json_or_none(value):
    try:
        return json.loads(value)
    except Exception:
        return None
