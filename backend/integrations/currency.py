"""O'zbekiston Markaziy banki valyuta kurslari — ochiq API (kalit shart emas). 6 soat keshlanadi."""
from __future__ import annotations

import json
import logging
import urllib.request

from django.core.cache import cache

log = logging.getLogger("integrations.currency")
CBU_URL = "https://cbu.uz/uz/arkhiv-kursov-valyut/json/"


def get_rates() -> dict:
    cached = cache.get("cbu_rates")
    if cached:
        return cached
    try:
        with urllib.request.urlopen(CBU_URL, timeout=8) as r:
            data = json.loads(r.read().decode())
        rates = {row["Ccy"]: {"rate": float(row["Rate"]), "diff": float(row.get("Diff") or 0), "date": row["Date"], "name": row.get("CcyNm_UZ")}
                 for row in data if row.get("Ccy") in ("USD", "EUR", "RUB", "KZT", "CNY", "TRY")}
        out = {"ok": True, "source": "cbu.uz", "rates": rates}
        cache.set("cbu_rates", out, 6 * 3600)
        return out
    except Exception as e:  # tarmoq yo'q — bo'sh, lekin xato emas
        log.warning("CBU kurslarini olib bo'lmadi: %s", e)
        return {"ok": False, "source": "cbu.uz", "error": str(e), "rates": {}}
