from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import DocumentSequence, DocumentSequenceCounter, Role, User


class NoDeleteAdmin(admin.ModelAdmin):
    """เอกสารไม่มี hard delete (INVARIANT ข้อ 1) — ปิดปุ่มลบใน admin ด้วย"""

    def has_delete_permission(self, request, obj=None):
        return False


class ReadOnlyAdmin(NoDeleteAdmin):
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = ["username", "employee_code", "is_staff", "is_active"]
    fieldsets = BaseUserAdmin.fieldsets + (
        ("การผลิต", {"fields": ("employee_code", "roles", "default_work_center")}),
    )


@admin.register(Role)
class RoleAdmin(admin.ModelAdmin):
    list_display = ["code", "name"]


@admin.register(DocumentSequence)
class DocumentSequenceAdmin(NoDeleteAdmin):
    list_display = ["doc_type", "prefix", "reset_rule", "padding"]


@admin.register(DocumentSequenceCounter)
class DocumentSequenceCounterAdmin(ReadOnlyAdmin):
    list_display = ["sequence", "period", "next_number"]
