"""Audit yozuvi yordamchisi — API xizmatlari har o'zgarishda chaqiradi."""
from django.forms.models import model_to_dict

from .models import AuditLog


def snapshot(instance) -> dict | None:
    if instance is None:
        return None
    from django.db.models.fields.files import FieldFile

    data = model_to_dict(instance)
    for k, v in list(data.items()):
        if isinstance(v, FieldFile):
            data[k] = v.name or None
        elif isinstance(v, (list, tuple)):
            data[k] = [getattr(x, "pk", x) if not isinstance(x, (str, int, float, bool, dict)) else x for x in v]
        elif not isinstance(v, (str, int, float, bool, dict, type(None))):
            data[k] = str(v)
    return data


def record(request, action: str, instance=None, *, before=None, after=None, model: str | None = None, object_id=None):
    user = getattr(request, "auth", None)
    if user is not None and not hasattr(user, "pk"):
        user = None
    AuditLog.objects.create(
        actor=user,
        action=action,
        model=model or (instance.__class__.__name__ if instance is not None else ""),
        object_id=str(object_id or (getattr(instance, "pk", "") or "")),
        before=before,
        after=after if after is not None else snapshot(instance),
        request_id=getattr(request, "request_id", ""),
        ip=request.META.get("REMOTE_ADDR"),
    )
