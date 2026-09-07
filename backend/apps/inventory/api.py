from rest_framework import serializers, viewsets

from .models import StockBalance, StockTransaction


class StockBalanceSerializer(serializers.ModelSerializer):
    item_code = serializers.CharField(source="item.code", read_only=True)
    item_name = serializers.CharField(source="item.name", read_only=True)
    location_code = serializers.CharField(source="location.code", read_only=True)
    warehouse_code = serializers.CharField(source="location.warehouse.code", read_only=True)

    class Meta:
        model = StockBalance
        fields = [
            "item",
            "item_code",
            "item_name",
            "location",
            "location_code",
            "warehouse_code",
            "lot_no",
            "qty_on_hand",
        ]


class StockTransactionSerializer(serializers.ModelSerializer):
    item_code = serializers.CharField(source="item.code", read_only=True)
    uom_code = serializers.CharField(source="uom.code", read_only=True)

    class Meta:
        model = StockTransaction
        fields = [
            "txn_no",
            "txn_type",
            "doc_type",
            "doc_no",
            "item",
            "item_code",
            "lot_no",
            "from_location",
            "to_location",
            "qty",
            "uom",
            "uom_code",
            "qty_base",
            "unit_cost",
            "total_cost",
            "posted_at",
            "is_auto_backflush",
        ]


class StockBalanceViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = StockBalanceSerializer

    def get_queryset(self):
        qs = StockBalance.objects.select_related("item", "location", "location__warehouse")
        item = self.request.query_params.get("item_code")
        if item:
            qs = qs.filter(item__code=item)
        location = self.request.query_params.get("location_code")
        if location:
            qs = qs.filter(location__code=location)
        if self.request.query_params.get("nonzero") == "1":
            qs = qs.exclude(qty_on_hand=0)
        return qs


class StockTransactionViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = StockTransactionSerializer

    def get_queryset(self):
        qs = StockTransaction.objects.select_related("item", "uom")
        item = self.request.query_params.get("item_code")
        if item:
            qs = qs.filter(item__code=item)
        doc_no = self.request.query_params.get("doc_no")
        if doc_no:
            qs = qs.filter(doc_no=doc_no)
        return qs.order_by("posted_at", "txn_no")
