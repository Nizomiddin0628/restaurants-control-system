"""SMS drayveri: Eskiz.uz (prod) yoki konsol (dev). Almashtiriladigan interfeys."""
import logging
import os

log = logging.getLogger("sms")


def send_sms(phone: str, text: str) -> bool:
    provider = os.environ.get("SMS_PROVIDER", "console")
    if provider == "eskiz":
        from .eskiz import EskizClient
        return EskizClient.from_env().send(phone, text)
    log.info("[SMS→%s] %s", phone, text)
    return True


def send_otp(phone: str, code: str) -> bool:
    return send_sms(phone, f"RestoPOS: kirish kodi {code}. 5 daqiqa amal qiladi.")
