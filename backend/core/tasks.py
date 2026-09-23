"""Celery yordamchilari: vazifa ichida tenant sxemasini tiklash."""
from functools import wraps

from celery import shared_task
from django_tenants.utils import schema_context


def tenant_task(**celery_kwargs):
    """
    @tenant_task(queue="critical")
    def send_fiscal(schema_name, receipt_id): ...
    Chaqirish: send_fiscal.delay(request.tenant.schema_name, receipt.id)
    """
    def deco(fn):
        @shared_task(**celery_kwargs)
        @wraps(fn)
        def wrapper(schema_name, *args, **kwargs):
            with schema_context(schema_name):
                return fn(schema_name, *args, **kwargs)
        return wrapper
    return deco


@tenant_task(queue="default")
def ping(schema_name: str) -> str:
    return f"pong from {schema_name}"
