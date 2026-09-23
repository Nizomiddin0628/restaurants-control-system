"""Eskiz.uz SMS API (https://eskiz.uz) — token olish + yuborish. Alfa-nom tasdig'i 1–2 oy oladi."""
from __future__ import annotations

import os
import time

import requests


class EskizClient:
    BASE = "https://notify.eskiz.uz/api"

    def __init__(self, email: str, password: str, sender: str = "4546"):
        self.email, self.password, self.sender = email, password, sender
        self._token: str | None = None
        self._token_at = 0.0

    @classmethod
    def from_env(cls) -> "EskizClient":
        return cls(os.environ["ESKIZ_EMAIL"], os.environ["ESKIZ_PASSWORD"], os.environ.get("ESKIZ_SENDER", "4546"))

    def token(self) -> str:
        if self._token and time.time() - self._token_at < 20 * 3600:
            return self._token
        r = requests.post(f"{self.BASE}/auth/login", data={"email": self.email, "password": self.password}, timeout=15)
        r.raise_for_status()
        self._token = r.json()["data"]["token"]
        self._token_at = time.time()
        return self._token

    def send(self, phone: str, text: str) -> bool:
        r = requests.post(f"{self.BASE}/message/sms/send",
                          headers={"Authorization": f"Bearer {self.token()}"},
                          data={"mobile_phone": phone.lstrip("+"), "message": text, "from": self.sender}, timeout=15)
        return r.status_code == 200
