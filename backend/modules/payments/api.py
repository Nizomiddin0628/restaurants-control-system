"""To'lov API: Payme Merchant API (JSON-RPC 2.0) va Click SHOP API — rasmiy hujjatlar bo'yicha."""
from __future__ import annotations

import base64
import hashlib
import json
import time
from typing import Optional
from urllib.parse import urlencode

from django.db import transaction
from django.http import JsonResponse
from django.utils import timezone
from ninja import Router, Schema

from core.auth import auth, require_module, require_perm
from core.events import emit
from modules.pos.models import Order, OrderStatus

from .models import Payment, PaymeState, Provider

router = Router(tags=["payments"])


def _cfg(request) -> dict:
    return (request.tenant.settings or {}).get("payments", {}) or {}


def _now_ms() -> int:
    return int(time.time() * 1000)


def _mark_paid(request, order: Order, method: str) -> None:
    if order.status == OrderStatus.PAID:
        return
    order.status, order.payment_method, order.paid_at = OrderStatus.PAID, method, timezone.now()
    order.save(update_fields=["status", "payment_method", "paid_at", "updated_at"])
    emit("pos.order_paid", {
        "order_id": order.pk, "number": order.number, "total": order.total, "cost_total": order.cost_total,
        "payment_method": method, "branch_id": order.branch_id, "customer_phone": order.customer_phone,
        "items": [{"product_id": i.product_id, "name": i.name, "qty": i.qty, "price": i.price} for i in order.items.all()],
        "_tenant": request.tenant,
    }, tenant=request.tenant)


# ------------------------------------------------------------------ sozlamalar va to'lov havolasi
class SettingsIn(Schema):
    payme_merchant_id: str = ""
    payme_key: str = ""
    payme_test: bool = True
    click_service_id: str = ""
    click_merchant_id: str = ""
    click_merchant_user_id: str = ""
    click_secret_key: str = ""


@router.get("/settings", auth=auth)
def get_settings(request):
    require_module(request, "payments"); require_perm(request, "core.settings.view")
    c = _cfg(request)
    return {**{k: c.get(k, "") for k in SettingsIn.__fields__}, "payme_key": "•••" if c.get("payme_key") else "",
            "click_secret_key": "•••" if c.get("click_secret_key") else "",
            "callback_payme": request.build_absolute_uri("/api/v1/payments/payme"),
            "callback_click_prepare": request.build_absolute_uri("/api/v1/payments/click/prepare"),
            "callback_click_complete": request.build_absolute_uri("/api/v1/payments/click/complete")}


@router.put("/settings", auth=auth)
def put_settings(request, data: SettingsIn):
    require_module(request, "payments"); require_perm(request, "core.settings.edit")
    t = request.tenant
    cur = _cfg(request)
    new = data.dict()
    for secret in ("payme_key", "click_secret_key"):     # "•••" kelsa — eskisini saqlaymiz
        if new[secret] in ("", "•••"):
            new[secret] = cur.get(secret, "")
    t.settings = {**(t.settings or {}), "payments": new}
    t.save(update_fields=["settings"])
    return {"ok": True}


class LinkIn(Schema):
    order_id: int
    provider: str
    return_url: str = ""


@router.post("/link", auth=auth)
def payment_link(request, data: LinkIn):
    """Buyurtma uchun to'lov havolasi / QR: kassada mijozga ko'rsatiladi yoki Telegramga yuboriladi."""
    require_module(request, "payments"); require_perm(request, "pos.sell")
    c = _cfg(request)
    o = Order.objects.get(pk=data.order_id)
    if data.provider == Provider.PAYME:
        if not c.get("payme_merchant_id"):
            return {"ok": False, "error": "Payme merchant ID kiritilmagan (Sozlamalar → To'lovlar)."}
        params = f"m={c['payme_merchant_id']};ac.order_id={o.number};a={o.total * 100}"
        if data.return_url:
            params += f";c={data.return_url}"
        host = "https://test.paycom.uz" if c.get("payme_test", True) else "https://checkout.paycom.uz"
        return {"ok": True, "url": f"{host}/{base64.b64encode(params.encode()).decode()}"}
    if data.provider == Provider.CLICK:
        if not c.get("click_service_id"):
            return {"ok": False, "error": "Click service ID kiritilmagan (Sozlamalar → To'lovlar)."}
        q = {"service_id": c["click_service_id"], "merchant_id": c.get("click_merchant_id", ""), "amount": f"{o.total}.00",
             "transaction_param": o.number}
        if data.return_url:
            q["return_url"] = data.return_url
        return {"ok": True, "url": "https://my.click.uz/services/pay?" + urlencode(q)}
    return {"ok": False, "error": "Noma'lum provayder."}


@router.get("/", auth=auth)
def list_payments(request, limit: int = 100):
    require_module(request, "payments"); require_perm(request, "finance.view")
    return [{"id": p.id, "order_number": p.order.number, "provider": p.provider, "external_id": p.external_id, "amount": p.amount,
             "state": p.state, "created_at": p.created_at, "perform_time": p.perform_time} for p in Payment.objects.select_related("order")[:limit]]


# ------------------------------------------------------------------ PAYME Merchant API
class PaymeError(Exception):
    def __init__(self, code: int, message: str, data: str | None = None):
        self.code, self.message, self.data = code, message, data


def _payme_auth(request, cfg: dict) -> None:
    hdr = request.headers.get("Authorization", "")
    ok = False
    if hdr.startswith("Basic "):
        try:
            login, _, pwd = base64.b64decode(hdr[6:]).decode().partition(":")
            ok = login == "Paycom" and pwd and pwd == cfg.get("payme_key")
        except Exception:
            ok = False
    if not ok:
        raise PaymeError(-32504, "Ruxsat yo'q (login/parol)")


def _payme_order(params: dict) -> Order:
    acc = params.get("account") or {}
    try:
        number = int(str(acc.get("order_id", "")).strip())
    except ValueError:
        raise PaymeError(-31050, "Buyurtma topilmadi", "order_id") from None
    o = Order.objects.filter(number=number).first()
    if not o:
        raise PaymeError(-31050, "Buyurtma topilmadi", "order_id")
    return o


def _payme_amount_ok(o: Order, params: dict) -> None:
    if int(params.get("amount", 0)) != o.total * 100:
        raise PaymeError(-31001, "Summa noto'g'ri")


def _payme_tx(params: dict) -> Payment:
    p = Payment.objects.filter(provider=Provider.PAYME, external_id=str(params.get("id"))).select_related("order").first()
    if not p:
        raise PaymeError(-31003, "Tranzaksiya topilmadi")
    return p


def _payme_dispatch(request, method: str, params: dict) -> dict:
    if method == "CheckPerformTransaction":
        o = _payme_order(params); _payme_amount_ok(o, params)
        if o.status != OrderStatus.OPEN:
            raise PaymeError(-31050, "Buyurtma allaqachon to'langan yoki bekor qilingan", "order_id")
        return {"allow": True, "detail": {"receipt_type": 0, "items": [
            {"title": i.name, "price": i.price * 100, "count": i.qty, "code": (i.product.ikpu_code if i.product_id and i.product else "") or "",
             "vat_percent": 0, "package_code": ""} for i in o.items.select_related("product")]}}

    if method == "CreateTransaction":
        o = _payme_order(params); _payme_amount_ok(o, params)
        existing = Payment.objects.filter(provider=Provider.PAYME, external_id=str(params["id"])).first()
        if existing:
            if existing.state != PaymeState.CREATED:
                raise PaymeError(-31008, "Tranzaksiyani bajarib bo'lmaydi")
            return {"create_time": existing.create_time, "transaction": str(existing.pk), "state": existing.state}
        if o.status != OrderStatus.OPEN or Payment.objects.filter(order=o, provider=Provider.PAYME, state=PaymeState.CREATED).exists():
            raise PaymeError(-31050, "Buyurtma bo'yicha boshqa tranzaksiya bor", "order_id")
        p = Payment.objects.create(order=o, provider=Provider.PAYME, external_id=str(params["id"]), amount=o.total,
                                   state=PaymeState.CREATED, create_time=int(params.get("time") or _now_ms()), raw=params)
        return {"create_time": p.create_time, "transaction": str(p.pk), "state": p.state}

    if method == "PerformTransaction":
        p = _payme_tx(params)
        if p.state == PaymeState.CREATED:
            with transaction.atomic():
                p.state, p.perform_time = PaymeState.PERFORMED, _now_ms()
                p.save()
                _mark_paid(request, p.order, "payme")
        elif p.state != PaymeState.PERFORMED:
            raise PaymeError(-31008, "Tranzaksiyani bajarib bo'lmaydi")
        return {"transaction": str(p.pk), "perform_time": p.perform_time, "state": p.state}

    if method == "CancelTransaction":
        p = _payme_tx(params)
        reason = int(params.get("reason") or 0)
        if p.state == PaymeState.CREATED:
            p.state = PaymeState.CANCELLED
        elif p.state == PaymeState.PERFORMED:
            p.state = PaymeState.CANCELLED_AFTER_PERFORM
            o = p.order
            o.status, o.cancelled_at, o.cancel_reason = OrderStatus.CANCELLED, timezone.now(), f"Payme qaytarish ({reason})"
            o.save(update_fields=["status", "cancelled_at", "cancel_reason", "updated_at"])
            emit("pos.order_cancelled", {"order_id": o.pk, "number": o.number}, tenant=request.tenant)
        if not p.cancel_time:
            p.cancel_time, p.reason = _now_ms(), reason
            p.save()
        return {"transaction": str(p.pk), "cancel_time": p.cancel_time, "state": p.state}

    if method == "CheckTransaction":
        p = _payme_tx(params)
        return {"create_time": p.create_time, "perform_time": p.perform_time, "cancel_time": p.cancel_time,
                "transaction": str(p.pk), "state": p.state, "reason": p.reason}

    if method == "GetStatement":
        qs = Payment.objects.filter(provider=Provider.PAYME, create_time__gte=int(params.get("from", 0)),
                                    create_time__lte=int(params.get("to", _now_ms()))).select_related("order")
        return {"transactions": [{"id": p.external_id, "time": p.create_time, "amount": p.amount * 100,
                                  "account": {"order_id": str(p.order.number)}, "create_time": p.create_time,
                                  "perform_time": p.perform_time, "cancel_time": p.cancel_time, "transaction": str(p.pk),
                                  "state": p.state, "reason": p.reason} for p in qs]}
    raise PaymeError(-32601, "Metod topilmadi")


@router.post("/payme", auth=None)
def payme_endpoint(request):
    """Payme Merchant API — JSON-RPC 2.0 (barcha metodlar bitta URLda)."""
    try:
        body = json.loads(request.body or b"{}")
    except json.JSONDecodeError:
        return JsonResponse({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "JSON xato"}})
    rid = body.get("id")
    try:
        require_module(request, "payments")
        cfg = _cfg(request)
        _payme_auth(request, cfg)
        result = _payme_dispatch(request, body.get("method", ""), body.get("params") or {})
        return JsonResponse({"jsonrpc": "2.0", "id": rid, "result": result})
    except PaymeError as e:
        err = {"code": e.code, "message": {"uz": e.message, "ru": e.message, "en": e.message}}
        if e.data:
            err["data"] = e.data
        return JsonResponse({"jsonrpc": "2.0", "id": rid, "error": err})
    except Exception as e:  # noqa: BLE001
        return JsonResponse({"jsonrpc": "2.0", "id": rid, "error": {"code": -32400, "message": str(e)}})


# ------------------------------------------------------------------ CLICK SHOP API
def _click_sign(cfg: dict, d: dict, with_prepare: bool) -> str:
    parts = [str(d.get("click_trans_id", "")), str(d.get("service_id", "")), cfg.get("click_secret_key", ""), str(d.get("merchant_trans_id", ""))]
    if with_prepare:
        parts.append(str(d.get("merchant_prepare_id", "")))
    parts += [str(d.get("amount", "")), str(d.get("action", "")), str(d.get("sign_time", ""))]
    return hashlib.md5("".join(parts).encode()).hexdigest()


def _click_resp(d: dict, error: int, note: str, **extra) -> JsonResponse:
    return JsonResponse({"click_trans_id": d.get("click_trans_id"), "merchant_trans_id": d.get("merchant_trans_id"),
                         "error": error, "error_note": note, **extra})


def _click_order(d: dict) -> Optional[Order]:
    try:
        return Order.objects.filter(number=int(str(d.get("merchant_trans_id", "")).strip())).first()
    except ValueError:
        return None


@router.post("/click/prepare", auth=None)
def click_prepare(request):
    d = request.POST.dict() if request.POST else json.loads(request.body or b"{}")
    try:
        require_module(request, "payments")
    except Exception:
        return _click_resp(d, -8, "Modul yoqilmagan")
    cfg = _cfg(request)
    if _click_sign(cfg, d, False) != str(d.get("sign_string", "")).lower():
        return _click_resp(d, -1, "SIGN CHECK FAILED!")
    if str(d.get("action")) != "0":
        return _click_resp(d, -3, "Action not found")
    o = _click_order(d)
    if not o:
        return _click_resp(d, -5, "Buyurtma topilmadi")
    if o.status == OrderStatus.PAID:
        return _click_resp(d, -4, "Allaqachon to'langan")
    if o.status == OrderStatus.CANCELLED:
        return _click_resp(d, -9, "Buyurtma bekor qilingan")
    try:
        if abs(float(d.get("amount", 0)) - o.total) > 0.01:
            return _click_resp(d, -2, "Summa noto'g'ri")
    except ValueError:
        return _click_resp(d, -2, "Summa noto'g'ri")
    p, _ = Payment.objects.get_or_create(provider=Provider.CLICK, external_id=str(d.get("click_trans_id")),
                                         defaults={"order": o, "amount": o.total, "state": 1, "create_time": _now_ms(), "raw": d})
    p.prepare_id = p.pk
    p.save(update_fields=["prepare_id"])
    return _click_resp(d, 0, "Success", merchant_prepare_id=p.pk)


@router.post("/click/complete", auth=None)
def click_complete(request):
    d = request.POST.dict() if request.POST else json.loads(request.body or b"{}")
    try:
        require_module(request, "payments")
    except Exception:
        return _click_resp(d, -8, "Modul yoqilmagan")
    cfg = _cfg(request)
    if _click_sign(cfg, d, True) != str(d.get("sign_string", "")).lower():
        return _click_resp(d, -1, "SIGN CHECK FAILED!")
    if str(d.get("action")) != "1":
        return _click_resp(d, -3, "Action not found")
    p = Payment.objects.filter(provider=Provider.CLICK, external_id=str(d.get("click_trans_id"))).select_related("order").first()
    if not p or str(p.prepare_id) != str(d.get("merchant_prepare_id")):
        return _click_resp(d, -6, "Tranzaksiya topilmadi")
    if str(d.get("error", "0")) not in ("0", "0.0"):
        p.state = -1; p.save(update_fields=["state"])
        return _click_resp(d, -9, "Bekor qilindi", merchant_confirm_id=p.pk)
    if p.order.status == OrderStatus.PAID and p.state == 2:
        return _click_resp(d, -4, "Allaqachon to'langan", merchant_confirm_id=p.pk)
    with transaction.atomic():
        p.state, p.perform_time = 2, _now_ms()
        p.save(update_fields=["state", "perform_time"])
        _mark_paid(request, p.order, "click")
    return _click_resp(d, 0, "Success", merchant_confirm_id=p.pk)
