from django.contrib import admin
from django_tenants.admin import TenantAdminMixin

from .models import Domain, Plan, Tenant


@admin.register(Tenant)
class TenantAdmin(TenantAdminMixin, admin.ModelAdmin):
    list_display = ("name", "schema_name", "preset", "plan", "is_active", "created_at")
    search_fields = ("name", "schema_name")


admin.site.register(Domain)
admin.site.register(Plan)
