from django.contrib import admin

from .models import AuditLog, Branch, Device, Membership, Role, User

admin.site.register(User)
admin.site.register(Role)
admin.site.register(Branch)
admin.site.register(Membership)
admin.site.register(Device)


@admin.register(AuditLog)
class AuditAdmin(admin.ModelAdmin):
    list_display = ("at", "actor", "action", "model", "object_id")
    list_filter = ("action", "model")
