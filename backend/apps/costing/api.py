from datetime import date

from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.production.models import WorkOrder

from .services import (
    plan_vs_actual_report,
    sales_orders_at_risk,
    scrap_report,
    stock_ledger,
    wo_status_report,
    work_order_cost,
)


def _status_filter(request):
    raw = request.query_params.get("status")
    return raw.split(",") if raw else None


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def report_wo_status(request):
    return Response(wo_status_report(status_in=_status_filter(request)))


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def report_plan_vs_actual(request):
    return Response(plan_vs_actual_report(status_in=_status_filter(request)))


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def report_scrap(request):
    def parse(name):
        raw = request.query_params.get(name)
        return date.fromisoformat(raw) if raw else None

    return Response(scrap_report(date_from=parse("date_from"), date_to=parse("date_to")))


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def report_so_at_risk(request):
    return Response(sales_orders_at_risk())


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def work_order_cost_detail(request, wo_no):
    order = WorkOrder.objects.select_related("item").get(wo_no=wo_no)
    cost = work_order_cost(order)
    return Response(
        {
            "wo_no": cost.wo_no,
            "material_planned": cost.material_planned,
            "material_actual": cost.material_actual,
            "labor_planned": cost.labor_planned,
            "labor_actual": cost.labor_actual,
            "overhead_planned": cost.overhead_planned,
            "overhead_actual": cost.overhead_actual,
            "total_planned": cost.total_planned,
            "total_actual": cost.total_actual,
            "lines": [
                {
                    "source": line.source,
                    "reference": line.reference,
                    "detail": line.detail,
                    "amount": line.amount,
                }
                for line in cost.lines
            ],
        }
    )


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def stock_trace(request, item_code):
    from apps.masterdata.models import Item

    item = Item.objects.get(code=item_code)
    return Response(stock_ledger(item))
