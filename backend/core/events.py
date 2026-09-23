"""
Hodisa shinasi — modullar bir-birini to'g'ridan-to'g'ri chaqirmaydi.
`emit("order.paid", {...})` → yoqilgan modullardagi `@on("order.paid")` tinglovchilar ishlaydi.
Prod'da og'ir tinglovchilar Celery vazifasiga o'tadi (core.tasks.tenant_task).
"""
from __future__ import annotations

import logging
from collections import defaultdict
from typing import Callable

log = logging.getLogger("events")
_handlers: dict[str, list[Callable]] = defaultdict(list)


def on(event: str):
    def deco(fn: Callable):
        _handlers[event].append(fn)
        return fn
    return deco


def emit(event: str, payload: dict | None = None, *, tenant=None) -> int:
    payload = payload or {}
    enabled = set(getattr(tenant, "enabled_modules", []) or []) if tenant is not None else None
    ran = 0
    for fn in list(_handlers.get(event, [])):
        module = getattr(fn, "__module__", "")
        # modules.<code>.* tinglovchisi faqat modul yoqilgan bo'lsa ishlaydi
        if enabled is not None and module.startswith("modules."):
            code = module.split(".")[1]
            if code not in enabled:
                continue
        try:
            fn(payload)
            ran += 1
        except Exception:  # bir tinglovchi xatosi boshqalarini to'xtatmaydi
            log.exception("event handler failed: %s -> %s", event, fn)
    return ran
