from django.contrib import admin

from apps.common.admin import NoDeleteAdmin, ReadOnlyAdmin

from .models import (
    BackflushException,
    ShopFloorReport,
    WorkOrder,
    WorkOrderMaterial,
    WorkOrderOperation,
    WorkOrderStatusHistory,
)


class WorkOrderMaterialInline(admin.TabularInline):
    model = WorkOrderMaterial
    extra = 0
    can_delete = False
    readonly_fields = [
        "line_no",
        "component_item",
        "qty_per",
        "scrap_pct",
        "qty_required",
        "uom",
        "standard_unit_cost",
        "bom_revision",
        "source_bom_line_id",
    ]
    fields = readonly_fields


class WorkOrderOperationInline(admin.TabularInline):
    model = WorkOrderOperation
    extra = 0
    can_delete = False
    readonly_fields = [
        "sequence",
        "work_center",
        "name",
        "setup_minutes",
        "run_minutes_per_unit",
        "labor_rate_per_hour",
        "qty_good",
        "qty_scrap",
        "actual_minutes",
        "status",
    ]
    fields = readonly_fields


class WorkOrderStatusHistoryInline(admin.TabularInline):
    model = WorkOrderStatusHistory
    extra = 0
    can_delete = False
    readonly_fields = ["from_status", "to_status", "changed_at", "changed_by", "note"]
    fields = readonly_fields


@admin.register(WorkOrder)
class WorkOrderAdmin(NoDeleteAdmin):
    list_display = [
        "wo_no",
        "item",
        "qty_planned",
        "qty_completed",
        "qty_scrapped",
        "due_date",
        "status",
    ]
    list_filter = ["status"]
    search_fields = ["wo_no", "item__code"]
    readonly_fields = [
        "wo_no",
        "status",
        "qty_completed",
        "qty_scrapped",
        "bom_revision",
        "routing_revision",
        "snapshot_date",
        "cancelled_at",
        "cancelled_by",
        "cancel_reason",
    ]
    inlines = [WorkOrderMaterialInline, WorkOrderOperationInline, WorkOrderStatusHistoryInline]


@admin.register(ShopFloorReport)
class ShopFloorReportAdmin(ReadOnlyAdmin):
    list_display = [
        "posted_at",
        "work_order",
        "operation",
        "qty_good",
        "qty_scrap",
        "scrap_reason",
        "work_center",
        "shift",
        "has_exception",
    ]
    list_filter = ["work_center", "shift", "has_exception"]
    search_fields = ["work_order__wo_no", "client_ref"]


@admin.register(BackflushException)
class BackflushExceptionAdmin(NoDeleteAdmin):
    list_display = ["work_order", "material", "qty_short", "uom", "resolved_at"]
    list_filter = ["resolved_at"]
    readonly_fields = ["report", "work_order", "material", "qty_short", "uom", "detail"]
