"""Celery vazifalari: takroriy ishlarni ochish va kechikkanlarni eskalatsiya qilish.

Beat jadvali (config/celery.py):
    tasks.run_recurrences  — har kuni 06:00
    tasks.escalate_overdue — har soatda
"""
from core.tasks import tenant_task

from . import services


@tenant_task(queue="default", name="tasks.run_recurrences")
def run_recurrences(schema_name: str) -> int:
    return services.run_recurrences()


@tenant_task(queue="default", name="tasks.escalate_overdue")
def escalate_overdue(schema_name: str) -> int:
    return services.escalate_overdue()
