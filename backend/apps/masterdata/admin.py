from django.contrib import admin

from .models import (
    Customer,
    Item,
    Location,
    ScrapReason,
    Uom,
    UomConversion,
    Warehouse,
    WorkCenter,
    WorkCenterRate,
)


@admin.register(Uom)
class UomAdmin(admin.ModelAdmin):
    list_display = ["code", "name", "is_active"]


@admin.register(UomConversion)
class UomConversionAdmin(admin.ModelAdmin):
    list_display = ["from_uom", "to_uom", "factor"]
    list_select_related = ["from_uom", "to_uom"]


@admin.register(Item)
class ItemAdmin(admin.ModelAdmin):
    list_display = [
        "code",
        "name",
        "item_type",
        "uom",
        "is_lot_controlled",
        "allow_negative",
        "standard_cost",
        "is_active",
    ]
    list_filter = ["item_type", "is_lot_controlled", "allow_negative", "is_active"]
    search_fields = ["code", "name"]


@admin.register(Warehouse)
class WarehouseAdmin(admin.ModelAdmin):
    list_display = ["code", "name", "is_active"]


@admin.register(Location)
class LocationAdmin(admin.ModelAdmin):
    list_display = ["warehouse", "code", "name", "location_type", "is_active"]
    list_filter = ["warehouse", "location_type"]


class WorkCenterRateInline(admin.TabularInline):
    model = WorkCenterRate
    extra = 0
    fields = ["labor_rate_per_hour", "overhead_rate_per_hour", "effective_from", "effective_to"]


@admin.register(WorkCenter)
class WorkCenterAdmin(admin.ModelAdmin):
    list_display = ["code", "name", "wip_location", "is_active"]
    inlines = [WorkCenterRateInline]


@admin.register(ScrapReason)
class ScrapReasonAdmin(admin.ModelAdmin):
    list_display = ["display_order", "code", "name", "work_center", "is_active"]
    ordering = ["display_order"]


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ["code", "name", "is_active"]
