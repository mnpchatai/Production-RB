from rest_framework import serializers, viewsets

from .models import Item, Location, ScrapReason, Uom, WorkCenter


class UomSerializer(serializers.ModelSerializer):
    class Meta:
        model = Uom
        fields = ["id", "code", "name"]


class ItemSerializer(serializers.ModelSerializer):
    uom_code = serializers.CharField(source="uom.code", read_only=True)

    class Meta:
        model = Item
        fields = [
            "id",
            "code",
            "name",
            "item_type",
            "uom",
            "uom_code",
            "is_lot_controlled",
            "allow_negative",
            "standard_cost",
        ]


class LocationSerializer(serializers.ModelSerializer):
    warehouse_code = serializers.CharField(source="warehouse.code", read_only=True)

    class Meta:
        model = Location
        fields = ["id", "code", "name", "location_type", "warehouse", "warehouse_code"]


class WorkCenterSerializer(serializers.ModelSerializer):
    class Meta:
        model = WorkCenter
        fields = ["id", "code", "name"]


class ScrapReasonSerializer(serializers.ModelSerializer):
    class Meta:
        model = ScrapReason
        fields = ["id", "code", "name", "work_center", "display_order"]


class ItemViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Item.objects.select_related("uom").filter(is_active=True)
    serializer_class = ItemSerializer


class LocationViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Location.objects.select_related("warehouse").filter(is_active=True)
    serializer_class = LocationSerializer


class WorkCenterViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = WorkCenter.objects.filter(is_active=True)
    serializer_class = WorkCenterSerializer


class ScrapReasonViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = ScrapReasonSerializer

    def get_queryset(self):
        qs = ScrapReason.objects.filter(is_active=True)
        work_center = self.request.query_params.get("work_center")
        if work_center:
            qs = qs.filter(work_center__code=work_center) | qs.filter(work_center__isnull=True)
        # หน้าจอหน้างานแสดงได้ไม่เกิน 8 ปุ่ม
        return qs.order_by("display_order", "code")[:8]
