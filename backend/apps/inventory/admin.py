from django.contrib import admin

from apps.common.admin import ReadOnlyAdmin

from .models import StockBalance, StockTransaction


@admin.register(StockTransaction)
class StockTransactionAdmin(ReadOnlyAdmin):
    list_display = [
        "posted_at",
        "txn_no",
        "txn_type",
        "item",
        "lot_no",
        "from_location",
        "to_location",
        "qty",
        "uom",
        "qty_base",
        "doc_no",
    ]
    list_filter = ["txn_type", "is_auto_backflush"]
    search_fields = ["txn_no", "item__code", "doc_no", "lot_no", "client_ref"]
    date_hierarchy = "posted_at"


@admin.register(StockBalance)
class StockBalanceAdmin(ReadOnlyAdmin):
    list_display = ["item", "location", "lot_no", "qty_on_hand"]
    search_fields = ["item__code", "lot_no"]
