import uuid

from django.db import transaction
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.common.api import StrictSerializer
from apps.common.state_machine import CANCELLED, CLOSED, COMPLETED, IN_PROGRESS, RELEASED
from apps.inventory.services import NegativeStockError
from apps.masterdata.models import ScrapReason

from .models import ShopFloorReport, WorkOrder, WorkOrderOperation
from .services import OverProductionError, ShopFloorError, report_shop_floor


class WorkOrderOperationSerializer(serializers.ModelSerializer):
    work_center_code = serializers.CharField(source="work_center.code", read_only=True)
    work_center_name = serializers.CharField(source="work_center.name", read_only=True)

    class Meta:
        model = WorkOrderOperation
        fields = [
            "sequence",
            "name",
            "work_center",
            "work_center_code",
            "work_center_name",
            "status",
            "qty_good",
            "qty_scrap",
            "setup_minutes",
            "run_minutes_per_unit",
            "actual_minutes",
        ]


class WorkOrderSerializer(serializers.ModelSerializer):
    item_code = serializers.CharField(source="item.code", read_only=True)
    item_name = serializers.CharField(source="item.name", read_only=True)
    uom_code = serializers.CharField(source="uom.code", read_only=True)
    operations = WorkOrderOperationSerializer(many=True, read_only=True)
    qty_remaining = serializers.DecimalField(max_digits=18, decimal_places=4, read_only=True)

    class Meta:
        model = WorkOrder
        fields = [
            "id",
            "wo_no",
            "item",
            "item_code",
            "item_name",
            "qty_planned",
            "qty_completed",
            "qty_scrapped",
            "qty_remaining",
            "uom",
            "uom_code",
            "due_date",
            "status",
            "bom_revision",
            "routing_revision",
            "operations",
        ]


class WorkOrderViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = WorkOrderSerializer
    lookup_field = "wo_no"
    lookup_value_regex = "[^/]+"

    def get_queryset(self):
        qs = (
            WorkOrder.objects.select_related("item", "uom")
            .prefetch_related("operations__work_center")
            .exclude(status=CANCELLED)
        )
        status_param = self.request.query_params.get("status")
        if status_param:
            qs = qs.filter(status__in=status_param.split(","))
        work_center = self.request.query_params.get("work_center")
        if work_center:
            qs = qs.filter(operations__work_center__code=work_center).distinct()
        return qs

    @action(detail=False, methods=["get"], url_path="open")
    def open_orders(self, request):
        """ใบสั่งงานที่หน้างานยังต้องทำ — ใช้เป็นรายการตั้งต้นของแท็บเล็ต"""
        qs = self.get_queryset().filter(status__in=[RELEASED, IN_PROGRESS])
        return Response(self.get_serializer(qs, many=True).data)


class ShopFloorReportSerializer(StrictSerializer):
    """สัญญาของ POST /api/shop-floor/report

    ฟิลด์ที่ไม่อยู่ในนี้จะถูกปฏิเสธด้วย 400 ไม่ใช่ ignore เงียบ ๆ —
    user, work_center, shift, เวลามาตรฐาน และต้นทุน ระบบเติมเองทั้งหมด
    """

    client_ref = serializers.UUIDField()
    wo_no = serializers.CharField(max_length=32)
    operation_seq = serializers.IntegerField(min_value=0)
    qty_good = serializers.DecimalField(max_digits=18, decimal_places=4, min_value=0)
    qty_scrap = serializers.DecimalField(
        max_digits=18, decimal_places=4, min_value=0, required=False, default=0
    )
    scrap_reason_code = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    started_at = serializers.DateTimeField(required=False, allow_null=True)
    finished_at = serializers.DateTimeField(required=False, allow_null=True)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def shop_floor_report(request):
    serializer = ShopFloorReportSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data

    reason = None
    code = data.get("scrap_reason_code")
    if code:
        reason = ScrapReason.objects.filter(code=code, is_active=True).first()
        if reason is None:
            return Response(
                {"scrap_reason_code": f"ไม่รู้จักรหัสสาเหตุ {code}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

    try:
        with transaction.atomic():
            report = report_shop_floor(
                client_ref=data["client_ref"],
                wo_no=data["wo_no"],
                operation_seq=data["operation_seq"],
                qty_good=data["qty_good"],
                qty_scrap=data.get("qty_scrap") or 0,
                scrap_reason=reason,
                started_at=data.get("started_at"),
                finished_at=data.get("finished_at"),
                user=request.user,
            )
    except WorkOrder.DoesNotExist:
        return Response(
            {"wo_no": f"ไม่พบใบสั่งผลิต {data['wo_no']}"}, status=status.HTTP_404_NOT_FOUND
        )
    except WorkOrderOperation.DoesNotExist:
        return Response(
            {"operation_seq": f"ใบสั่งผลิตนี้ไม่มีขั้นตอนที่ {data['operation_seq']}"},
            status=status.HTTP_404_NOT_FOUND,
        )
    except OverProductionError as exc:
        return Response({"qty_good": str(exc)}, status=status.HTTP_409_CONFLICT)
    except (ShopFloorError, NegativeStockError) as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

    exceptions = [
        {
            "item_code": row.material.component_item.code,
            "qty_short": row.qty_short,
            "detail": row.detail,
        }
        for row in report.backflush_exceptions.select_related("material__component_item")
    ]
    return Response(
        {
            "client_ref": str(report.client_ref),
            "wo_no": report.work_order.wo_no,
            "operation_seq": report.operation.sequence,
            "qty_good": report.qty_good,
            "qty_scrap": report.qty_scrap,
            "shift": report.shift,
            "work_center": report.work_center.code,
            "posted_at": report.posted_at,
            "has_exception": report.has_exception,
            "backflush_exceptions": exceptions,
            "work_order_status": report.work_order.status,
            "qty_completed": report.work_order.qty_completed,
        },
        status=status.HTTP_201_CREATED,
    )
