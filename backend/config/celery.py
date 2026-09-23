import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")
app = Celery("restopos")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()

# Muhim: tenant sxemasini vazifa ichida tiklash uchun har vazifa `schema_name` argumentini oladi
# (core.tasks.tenant_task dekoratori).


# ------------------------------------------------------------------ jadval (Celery beat)
# Eslatma: ko'p-tenantli jadval — har tenant uchun sxema nomi bilan chaqiriladi (core.tasks.tenant_task).
from celery.schedules import crontab  # noqa: E402


@app.on_after_finalize.connect
def setup_periodic_tasks(sender, **kwargs):
    from django_tenants.utils import get_tenant_model

    try:
        schemas = list(get_tenant_model().objects.exclude(schema_name="public").values_list("schema_name", flat=True))
    except Exception:  # migratsiyagacha baza bo'sh bo'lishi mumkin
        return
    for schema in schemas:
        sender.add_periodic_task(crontab(hour=6, minute=0), app.signature("tasks.run_recurrences", args=[schema]),
                                 name=f"{schema}: takroriy vazifalar")
        sender.add_periodic_task(crontab(minute=5), app.signature("tasks.escalate_overdue", args=[schema]),
                                 name=f"{schema}: kechikkan vazifalar")
