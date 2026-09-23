"""tenant.created → preset'dagi tema va bo'limlar bilan sayt yaratiladi."""
from core.events import on


@on("tenant.created")
def _create_site(payload: dict):
    from .models import SiteSection, SiteSettings

    s = SiteSettings.get()
    s.title = payload.get("name", "")
    s.theme = {**s.theme, **payload.get("theme", {})}
    s.languages = ["uz", "ru"]
    s.delivery = {"free_from": 80000, "fee": 9000, "eta_min": 25, "eta_max": 35}
    s.save()
    if not SiteSection.objects.exists():
        for i, sec in enumerate(payload.get("sections", [])):
            SiteSection.objects.create(type=sec["type"], title={"uz": sec["props"].get("title", "")}, props=sec.get("props", {}), sort_order=i)
