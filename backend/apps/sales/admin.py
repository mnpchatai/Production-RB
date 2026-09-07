from django.contrib import admin

from apps.common.admin import NoDeleteAdmin

from .models import SalesOrder, SalesOrderLine, SalesOrderStatusHistory


class SalesOrderLineInline(admin.TabularInline):
    model = SalesOrderLine
    extra = 0
    fields = ["line_no", "item", "qty_ordered", "uom", "unit_price", "due_date"]


class SalesOrderStatusHistoryInline(admin.TabularInline):
    model = SalesOrderStatusHistory
    extra = 0
    can_delete = False
    readonly_fields = ["from_status", "to_status", "changed_at", "changed_by", "note"]
    fields = readonly_fields


@admin.register(SalesOrder)
class SalesOrderAdmin(NoDeleteAdmin):
    list_display = ["so_no", "customer", "order_date", "status"]
    list_filter = ["status"]
    search_fields = ["so_no", "customer__name"]
    readonly_fields = ["so_no", "status", "cancelled_at", "cancelled_by", "cancel_reason"]
    inlines = [SalesOrderLineInline, SalesOrderStatusHistoryInline]
