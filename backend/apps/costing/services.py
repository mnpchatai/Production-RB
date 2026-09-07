"""ต้นทุนจริงต่อใบสั่งผลิต และรายงานติดตาม

ทุกยอดรวมต้องกางเป็นรายบรรทัดได้เสมอ ไม่มีตารางสรุปที่เขียนทับได้
"""

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from django.db.models import Case, DecimalField, F, Q, Sum, Value, When

from apps.common.state_machine import CANCELLED, CLOSED, COMPLETED
from apps.inventory.models import (
    CONSUME_FROM_WIP,
    ISSUE_TO_WO,
    RETURN_FROM_WO,
    StockTransaction,
)
from apps.production.models import ShopFloorReport, WorkOrder, WorkOrderOperation
from apps.sales.models import SalesOrderLine

ZERO = Decimal("0")
SIXTY = Decimal(60)


@dataclass
class CostLine:
    source: str
    reference: str
    detail: str
    amount: Decimal


@dataclass
class WorkOrderCost:
    wo_no: str
    material_actual: Decimal = ZERO
    labor_actual: Decimal = ZERO
    overhead_actual: Decimal = ZERO
    material_planned: Decimal = ZERO
    labor_planned: Decimal = ZERO
    overhead_planned: Decimal = ZERO
    lines: list[CostLine] = field(default_factory=list)

    @property
    def total_actual(self):
        return self.material_actual + self.labor_actual + self.overhead_actual

    @property
    def total_planned(self):
        return self.material_planned + self.labor_planned + self.overhead_planned

    @property
    def material_variance(self):
        return self.material_actual - self.material_planned

    @property
    def labor_variance(self):
        return (self.labor_actual + self.overhead_actual) - (
            self.labor_planned + self.overhead_planned
        )


def work_order_cost(work_order):
    """ต้นทุนจริงของใบสั่งผลิตหนึ่งใบ พร้อมรายบรรทัดที่กางกลับไปหาต้นทางได้

    วัตถุดิบ = ธุรกรรมที่เบิกจริง (issue_to_wo) หักคืน (return_from_wo)
    ค่าแรง   = นาทีที่บันทึกจริง x อัตราของ work center ที่ snapshot ไว้ตอนออกใบ
    """
    cost = WorkOrderCost(wo_no=work_order.wo_no)

    txns = (
        StockTransaction.objects.filter(
            doc_type="work_order",
            doc_no=work_order.wo_no,
            txn_type__in=[ISSUE_TO_WO, RETURN_FROM_WO, CONSUME_FROM_WIP],
        )
        .select_related("item", "uom")
        .order_by("posted_at", "txn_no")
    )
    for txn in txns:
        # consume_from_wip เป็นการย้ายมูลค่าออกจาก WIP ไม่ใช่ต้นทุนก้อนใหม่
        if txn.txn_type == CONSUME_FROM_WIP:
            continue
        sign = Decimal(1) if txn.txn_type == ISSUE_TO_WO else Decimal(-1)
        amount = sign * Decimal(txn.total_cost)
        cost.material_actual += amount
        cost.lines.append(
            CostLine(
                source="material",
                reference=txn.txn_no,
                detail=(
                    f"{txn.get_txn_type_display()} {txn.item.code} "
                    f"{txn.qty} {txn.uom.code} @ {txn.unit_cost}"
                ),
                amount=amount,
            )
        )

    for operation in work_order.operations.select_related("work_center").all():
        hours = Decimal(operation.actual_minutes) / SIXTY
        labor = (hours * Decimal(operation.labor_rate_per_hour)).quantize(Decimal("0.0001"))
        overhead = (hours * Decimal(operation.overhead_rate_per_hour)).quantize(
            Decimal("0.0001")
        )
        cost.labor_actual += labor
        cost.overhead_actual += overhead
        if labor or overhead:
            cost.lines.append(
                CostLine(
                    source="labor",
                    reference=f"{work_order.wo_no}/op{operation.sequence:03d}",
                    detail=(
                        f"{operation.name} {operation.actual_minutes} นาที @ "
                        f"{operation.labor_rate_per_hour}/ชม. (+overhead "
                        f"{operation.overhead_rate_per_hour}/ชม.)"
                    ),
                    amount=labor + overhead,
                )
            )

        planned_minutes = Decimal(operation.setup_minutes) + Decimal(
            operation.run_minutes_per_unit
        ) * Decimal(work_order.qty_planned)
        planned_hours = planned_minutes / SIXTY
        cost.labor_planned += planned_hours * Decimal(operation.labor_rate_per_hour)
        cost.overhead_planned += planned_hours * Decimal(operation.overhead_rate_per_hour)

    # ต้นทุนตามแผนมาจาก snapshot ใน WO เท่านั้น ห้ามคำนวณใหม่จาก BOM ปัจจุบัน
    for material in work_order.materials.all():
        cost.material_planned += Decimal(material.qty_required) * Decimal(
            material.standard_unit_cost
        )

    return cost


def wo_status_report(*, status_in=None):
    """รายงาน 1 — สถานะใบสั่งผลิตทั้งหมด แยกตามขั้นตอนที่ค้าง"""
    orders = (
        WorkOrder.objects.exclude(status=CANCELLED)
        .select_related("item")
        .prefetch_related("operations__work_center")
    )
    if status_in:
        orders = orders.filter(status__in=status_in)

    rows = []
    for order in orders:
        pending = [op for op in order.operations.all() if op.status != "completed"]
        current = min(pending, key=lambda op: op.sequence) if pending else None
        rows.append(
            {
                "wo_no": order.wo_no,
                "item_code": order.item.code,
                "status": order.status,
                "qty_planned": order.qty_planned,
                "qty_completed": order.qty_completed,
                "qty_scrapped": order.qty_scrapped,
                "due_date": order.due_date,
                "pending_operation": current.name if current else "",
                "pending_work_center": current.work_center.code if current else "",
                "pending_operation_count": len(pending),
            }
        )
    return sorted(rows, key=lambda r: (r["due_date"], r["wo_no"]))


def plan_vs_actual_report(*, status_in=None):
    """รายงาน 2 — เทียบต้นทุนตามแผนกับต้นทุนจริง แยกวัตถุดิบ/ค่าแรง"""
    orders = WorkOrder.objects.exclude(status=CANCELLED).select_related("item")
    if status_in:
        orders = orders.filter(status__in=status_in)

    rows = []
    for order in orders:
        cost = work_order_cost(order)
        rows.append(
            {
                "wo_no": order.wo_no,
                "item_code": order.item.code,
                "status": order.status,
                "material_planned": cost.material_planned,
                "material_actual": cost.material_actual,
                "material_variance": cost.material_variance,
                "labor_planned": cost.labor_planned + cost.overhead_planned,
                "labor_actual": cost.labor_actual + cost.overhead_actual,
                "labor_variance": cost.labor_variance,
                "total_planned": cost.total_planned,
                "total_actual": cost.total_actual,
            }
        )
    return rows


def scrap_report(*, date_from=None, date_to=None):
    """รายงาน 3 — ของเสียแยกตามสาเหตุและ work center"""
    qs = ShopFloorReport.objects.filter(qty_scrap__gt=0)
    if date_from:
        qs = qs.filter(posted_at__date__gte=date_from)
    if date_to:
        qs = qs.filter(posted_at__date__lte=date_to)
    return list(
        qs.values(
            "work_center__code",
            "work_center__name",
            "scrap_reason__code",
            "scrap_reason__name",
        )
        .annotate(qty_scrap=Sum("qty_scrap"), report_count=Sum(Value(1)))
        .order_by("-qty_scrap")
    )


def sales_orders_at_risk(*, as_of=None):
    """รายงาน 4 — ใบสั่งขายที่เสี่ยงส่งไม่ทัน

    เกณฑ์: เวลาที่เหลือตาม routing ของงานที่ยังไม่เสร็จ มากกว่าเวลาที่เหลือถึงกำหนดส่ง
    แสดงจำนวนวันที่ขาดด้วย เพื่อให้ฝ่ายวางแผนเรียงลำดับได้
    """
    as_of = as_of or date.today()
    minutes_per_working_day = Decimal(8 * 60)

    lines = (
        SalesOrderLine.objects.exclude(sales_order__status=CANCELLED)
        .select_related("sales_order", "item", "sales_order__customer")
        .prefetch_related("work_orders__operations")
    )

    rows = []
    for line in lines:
        open_orders = [
            wo
            for wo in line.work_orders.all()
            if wo.status not in (COMPLETED, CLOSED, CANCELLED)
        ]
        if not open_orders:
            continue
        remaining_minutes = ZERO
        for order in open_orders:
            outstanding = max(order.qty_planned - order.qty_completed, ZERO)
            for operation in order.operations.all():
                if operation.status == "completed":
                    continue
                remaining_minutes += Decimal(operation.setup_minutes) + Decimal(
                    operation.run_minutes_per_unit
                ) * outstanding

        days_needed = remaining_minutes / minutes_per_working_day
        days_left = Decimal((line.due_date - as_of).days)
        shortfall = days_needed - days_left
        if shortfall > 0:
            rows.append(
                {
                    "so_no": line.sales_order.so_no,
                    "customer": line.sales_order.customer.name,
                    "line_no": line.line_no,
                    "item_code": line.item.code,
                    "due_date": line.due_date,
                    "days_left": days_left,
                    "days_needed": days_needed.quantize(Decimal("0.01")),
                    "days_short": shortfall.quantize(Decimal("0.01")),
                    "work_orders": [wo.wo_no for wo in open_orders],
                }
            )
    return sorted(rows, key=lambda r: -r["days_short"])


def stock_ledger(item, *, location=None):
    """ไล่ธุรกรรมของ item เรียงตามเวลา พร้อมยอดสะสมทีละบรรทัด (ใช้กับ /trace-stock)"""
    qs = StockTransaction.objects.filter(item=item).select_related(
        "uom", "from_location", "to_location"
    )
    if location is not None:
        qs = qs.filter(Q(from_location=location) | Q(to_location=location))

    signed = Case(
        When(from_location__isnull=False, then=-F("qty_base")),
        default=F("qty_base"),
        output_field=DecimalField(max_digits=18, decimal_places=4),
    )
    rows = []
    running = ZERO
    for txn in qs.annotate(signed=signed).order_by("posted_at", "txn_no"):
        # ธุรกรรมสองขาต้องนับสองบรรทัด
        moves = []
        if txn.from_location_id is not None:
            moves.append((txn.from_location, -Decimal(txn.qty_base)))
        if txn.to_location_id is not None:
            moves.append((txn.to_location, Decimal(txn.qty_base)))
        for loc, delta in moves:
            if location is not None and loc.pk != (
                location if isinstance(location, int) else location.pk
            ):
                continue
            running += delta
            rows.append(
                {
                    "posted_at": txn.posted_at,
                    "txn_no": txn.txn_no,
                    "txn_type": txn.txn_type,
                    "doc": f"{txn.doc_type} {txn.doc_no}".strip(),
                    "location": str(loc),
                    "lot_no": txn.lot_no,
                    "delta": delta,
                    "running": running,
                }
            )
    return rows
