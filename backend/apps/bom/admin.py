from django.contrib import admin

from .models import BomHeader, BomLine, RoutingHeader, RoutingOperation


class BomLineInline(admin.TabularInline):
    model = BomLine
    fk_name = "bom"
    extra = 0
    fields = ["sequence", "component_item", "qty_per", "uom", "scrap_pct", "alternate_of_line"]


@admin.register(BomHeader)
class BomHeaderAdmin(admin.ModelAdmin):
    list_display = ["item", "revision", "status", "effective_from", "effective_to"]
    list_filter = ["status"]
    search_fields = ["item__code"]
    inlines = [BomLineInline]


class RoutingOperationInline(admin.TabularInline):
    model = RoutingOperation
    extra = 0
    fields = ["sequence", "work_center", "name", "setup_minutes", "run_minutes_per_unit"]


@admin.register(RoutingHeader)
class RoutingHeaderAdmin(admin.ModelAdmin):
    list_display = ["item", "revision", "status", "effective_from", "effective_to"]
    search_fields = ["item__code"]
    inlines = [RoutingOperationInline]
