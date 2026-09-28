"""
Google Gemini mijozi (REST, `models/{model}:generateContent`).

Kalit tartibi: restoran sozlamasi (modules.ai.api_key) → server .env GEMINI_API_KEY.
Model tartibi: sozlama/.env GEMINI_MODEL → MODELS ro'yxati. Bepul tarifda limit har model uchun alohida,
shuning uchun bitta model «limit tugadi» (429) yoki «topilmadi» (404) desa — keyingisi sinab ko'riladi.
Xatolar foydalanuvchiga tushunarli o'zbekcha matn bilan qaytadi (AiError).
"""
from __future__ import annotations

import base64
import json
import logging
import os
import time

import requests

log = logging.getLogger("ai")
URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
STREAM_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:streamGenerateContent?alt=sse"
MODELS = ["gemini-3.8-flash", "gemini-3.5-flash", "gemini-3.5-flash-lite", "gemini-3.1-flash-lite"]


class AiError(Exception):
    """Foydalanuvchiga ko'rsatiladigan xato (o'zbekcha)."""


def conf(tenant) -> dict:
    return (((getattr(tenant, "settings", None) or {}).get("modules") or {}).get("ai") or {})


def api_key(tenant) -> str | None:
    return (conf(tenant).get("api_key") or "").strip() or os.environ.get("GEMINI_API_KEY", "").strip() or None


def key_source(tenant) -> str | None:
    if (conf(tenant).get("api_key") or "").strip():
        return "restoran"
    return "server" if os.environ.get("GEMINI_API_KEY", "").strip() else None


def models(tenant) -> list[str]:
    first = [m for m in ((conf(tenant).get("model") or "").strip(), os.environ.get("GEMINI_MODEL", "").strip()) if m]
    out: list[str] = []
    for m in [*first, *MODELS]:
        if m not in out:
            out.append(m)
    return out


def _friendly(status: int, body: str) -> str:
    b = body.lower()
    if "api_key_invalid" in b or "api key not valid" in b:
        return "AI kaliti noto'g'ri. «AI Kotib» sahifasida kalitni qayta kiriting."
    if status == 429 or "resource_exhausted" in b or "quota" in b:
        return "AI'ning bugungi bepul limiti tugadi. Ertaga qayta urinib ko'ring yoki pullik tarifga o'ting."
    if status == 403 or "permission" in b or "location" in b:
        return "AI kalitiga ruxsat yo'q (hudud yoki loyiha sozlamasi). Kalitni tekshiring."
    if status >= 500:
        return "Google AI vaqtincha ishlamayapti. Birozdan keyin qayta urinib ko'ring."
    return f"AI xatosi ({status})."


def _skip_model(status: int, body: str) -> bool:
    """Shu modelni o'tkazib, keyingisini sinash kerakmi (model yo'q / limiti tugagan / band)."""
    b = body.lower()
    return status in (404, 429, 503) or (status == 400 and ("not found" in b or "not supported" in b or "is not available" in b))


THINK = {"thinkingLevel": "low"}   # tezlik: modelning uzoq «o'ylash»ini qisqartiradi (qo'llamasa — o'zi olib tashlanadi)


class Stopped(Exception):
    """Foydalanuvchi «⏹ To'xtatish»ni bosdi."""


def _merge(acc: list[dict], new: list[dict]) -> None:
    """Oqim bo'laklarini bitta javobga yig'ish: ketma-ket matnlar qo'shiladi, funksiya chaqiruvlari alohida qoladi."""
    for p in new:
        if "text" in p and acc and "text" in acc[-1] and bool(acc[-1].get("thought")) == bool(p.get("thought")) and "functionCall" not in acc[-1]:
            acc[-1]["text"] += p["text"]
            if p.get("thoughtSignature") and not acc[-1].get("thoughtSignature"):
                acc[-1]["thoughtSignature"] = p["thoughtSignature"]
        else:
            acc.append(dict(p))


def generate(tenant, contents: list[dict], *, system: str | None = None, tools: list[dict] | None = None,
             temperature: float = 0.3, max_tokens: int = 4096, timeout: int = 90, fast: bool | str = True,
             on_text=None, stop=None, prefer: list[str] | None = None) -> dict:
    """Bitta chaqiruv. Natija: {"model", "data", "ms"}. Xato — AiError, to'xtatilsa — Stopped.
    on_text(delta) berilsa — javob oqim (stream) bilan keladi: matn tayyor bo'lgani sari uzatiladi.
    stop() True qaytarsa — oqim darhol uziladi (token tejaladi)."""
    key = api_key(tenant)
    if not key:
        raise AiError("AI kaliti kiritilmagan. Panelda «AI Kotib» sahifasiga Gemini API kalitini qo'ying.")
    gen: dict = {"temperature": temperature, "maxOutputTokens": max_tokens}
    if fast:
        gen["thinkingConfig"] = {"thinkingLevel": fast} if isinstance(fast, str) else dict(THINK)
    body: dict = {"contents": contents, "generationConfig": gen}
    if system:
        body["systemInstruction"] = {"parts": [{"text": system}]}
    if tools:
        body["tools"] = tools
    last = "AI javob bermadi."
    order = models(tenant)
    if prefer:
        order = [m for m in prefer if m in order] + [m for m in order if m not in prefer]
    headers = {"x-goog-api-key": key, "Content-Type": "application/json"}
    for m in order:
        t0 = time.monotonic()
        for attempt in (1, 2):
            url = (STREAM_URL if on_text else URL).format(model=m)
            try:
                r = requests.post(url, json=body, timeout=timeout, headers=headers, stream=bool(on_text))
            except requests.RequestException as e:
                log.warning("gemini %s tarmoq xatosi: %s", m, e)
                last = "AI serveriga ulanib bo'lmadi (internet). Birozdan keyin qayta urinib ko'ring."
                r = None
                break
            if r.status_code == 400 and attempt == 1 and "thinking" in r.text.lower() and "thinkingConfig" in gen:
                gen.pop("thinkingConfig", None)          # bu model «thinkingLevel»ni bilmaydi — usiz qayta
                continue
            break
        if r is None:
            continue
        if r.status_code >= 400:
            text = r.text[:600]
            log.warning("gemini %s → %s %s", m, r.status_code, text[:200])
            last = _friendly(r.status_code, text)
            if _skip_model(r.status_code, text):
                continue
            raise AiError(last)
        if not on_text:
            data = r.json()
        else:
            data = _read_stream(r, on_text, stop)
        if not data.get("candidates"):
            fb = (data.get("promptFeedback") or {}).get("blockReason")
            raise AiError("AI bu so'rovga javob bermadi" + (f" ({fb})" if fb else "") + ". Boshqacha so'rab ko'ring.")
        return {"model": m, "data": data, "ms": int((time.monotonic() - t0) * 1000)}
    raise AiError(last)


def _read_stream(r, on_text, stop) -> dict:
    """SSE oqimi: har bo'lakdagi matn darhol on_text'ga; oxirida bitta javob (generateContent ko'rinishida)."""
    acc: list[dict] = []
    usage: dict = {}
    finish = None
    feedback = None
    try:
        for raw in r.iter_lines(decode_unicode=True):
            if stop and stop():
                raise Stopped()
            if not raw or not raw.startswith("data:"):
                continue
            try:
                chunk = json.loads(raw[5:].strip())
            except ValueError:
                continue
            usage = chunk.get("usageMetadata") or usage
            feedback = chunk.get("promptFeedback") or feedback
            cand = (chunk.get("candidates") or [{}])[0]
            finish = cand.get("finishReason") or finish
            ps = (cand.get("content") or {}).get("parts") or []
            _merge(acc, ps)
            delta = "".join(p.get("text", "") for p in ps if "text" in p and not p.get("thought"))
            if delta:
                on_text(delta)
    except requests.RequestException as e:
        raise AiError("AI bilan aloqa uzildi. Qayta urinib ko'ring.") from e
    finally:
        r.close()
    if not acc and feedback:
        return {"promptFeedback": feedback}
    return {"candidates": [{"content": {"role": "model", "parts": acc}, "finishReason": finish}], "usageMetadata": usage}


def parts(data: dict) -> list[dict]:
    try:
        return (data["candidates"][0].get("content") or {}).get("parts") or []
    except (KeyError, IndexError, TypeError):
        return []


def text_of(data: dict) -> str:
    """Javob matni (modelning «o'ylash» qismlarisiz)."""
    return "".join(p.get("text", "") for p in parts(data) if "text" in p and not p.get("thought")).strip()


def calls_of(data: dict) -> list[dict]:
    return [p["functionCall"] for p in parts(data) if "functionCall" in p]


def tokens_of(data: dict) -> int:
    return int((data.get("usageMetadata") or {}).get("totalTokenCount") or 0)


TRANSCRIBE_PROMPT = (
    "Bu — restoran rahbari yoki menejerining ovozli xabari (o'zbek, rus yoki aralash tilda). "
    "Uni so'zma-so'z, imlo xatosiz matnga aylantiring. Ismlar, raqamlar, vaqt va summalarni aniq yozing. "
    "Faqat aytilgan matnni qaytaring — izoh, sarlavha yoki tarjima qo'shmang. "
    "Hech narsa tushunib bo'lmasa, faqat [tushunarsiz] deb yozing."
)


def transcribe(tenant, audio: bytes, mime: str = "audio/ogg") -> dict:
    """Ovoz → matn. Natija: {"text", "model", "ms", "tokens"}."""
    res = generate(tenant, [{"role": "user", "parts": [
        {"text": TRANSCRIBE_PROMPT},
        {"inline_data": {"mime_type": mime, "data": base64.b64encode(audio).decode()}},
    ]}], temperature=0.0, max_tokens=2048, timeout=60, fast="minimal")
    return {"text": text_of(res["data"]), "model": res["model"], "ms": res["ms"], "tokens": tokens_of(res["data"])}
