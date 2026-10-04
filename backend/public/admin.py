from django.contrib import admin
from django_tenants.admin import TenantAdminMixin

from .models import Domain, Lead, Plan, SiteOffer, Tenant


@admin.register(Tenant)
class TenantAdmin(TenantAdminMixin, admin.ModelAdmin):
    list_display = ("name", "schema_name", "preset", "plan", "is_active", "created_at")
    search_fields = ("name", "schema_name")


admin.site.register(Domain)
admin.site.register(Plan)


@admin.register(Lead)
class LeadAdmin(admin.ModelAdmin):
    list_display = ("created_at", "name", "phone", "business", "status", "source")
    list_filter = ("status", "source")
    search_fields = ("name", "phone", "business")


admin.site.register(SiteOffer)
