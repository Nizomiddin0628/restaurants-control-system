from django import template

register = template.Library()


@register.filter
def t(value, lang="uz"):
    """{{ product.name|t:lang }} — 3 tilli JSON'dan matn; bo'sh bo'lsa uz → ru → en."""
    if isinstance(value, dict):
        return value.get(lang) or value.get("uz") or value.get("ru") or value.get("en") or ""
    return value or ""


@register.filter
def money(value):
    """36000 → 36 000"""
    try:
        return f"{int(value):,}".replace(",", " ")
    except (TypeError, ValueError):
        return value


@register.filter
def get(d, key):
    return (d or {}).get(key)


@register.filter
def split(value, sep="|"):
    return [v.strip() for v in str(value).split(sep) if v.strip()]
