import uuid

from django.db import models

from apps.common.fields import AmountField, PercentField, QtyField
from apps.common.models import AuditedModel, DocumentModel, StatusHistory
from apps.masterdata.models import Item, Location, ScrapReason, Uom, WorkCenter
from apps.sales.models import SalesOrderLine

OP_PENDING = "pending"
OP_IN_PROGRESS = "in_progress"
OP_COMPLETED = "completed"
OP_STATUS_CHOICES = [
    (OP_PENDING, "รอผลิต"),
    (OP_IN_PROGRESS, "กำลังผลิต"),
    (OP_COMPLETED, "เสร็จแล้ว"),
]


class WorkOrder(DocumentModel):
    DOC_TYPE = "work_order"

    wo_no = models.CharField(max_length=32, unique=True)
    item = models.ForeignKey(Item, on_delete=models.PROTECT, related_name="work_orders")
    qty_planned = QtyField()
    uom = models.ForeignKey(Uom, on_delete=models.PROTECT, related_name="+")
    qty_completed = QtyField(default=0)
    qty_scrapped = QtyField(default=0)
    due_date = models.DateField()
    source_sales_order_line = models.ForeignKey(
        SalesOrderLine,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="work_orders",
    )
    wip_location = models.ForeignKey(Location, on_delete=models.PROTECT, related_name="+")
    output_location = models.ForeignKey(Location, on_delete=models.PROTECT, related_name="+")
    scrap_location = models.ForeignKey(Location, on_delete=models.PROTECT, related_name="+")

    # ข้อมูลของ snapshot — เก็บไว้สอบย้อนกลับ ไม่ใช่ FK เพื่อกันการ join กลับ
    snapshot_date = models.DateField()
    bom_revision = models.CharField(max_length=16, blank=True)
    routing_revision = models.CharField(max_length=16, blank=True)

    class Meta:
        db_table = "work_orders"
        ordering = ["-due_date", "-id"]
        constraints = [
            models.CheckConstraint(condition=models.Q(qty_planned__gt=0), name="wo_qty_positive"),
        ]

    def __str__(self):
        return self.wo_no

    @property
    def qty_remaining(self):
        return self.qty_planned - self.qty_completed


class WorkOrderStatusHistory(StatusHistory):
    document = models.ForeignKey(
        WorkOrder, on_delete=models.PROTECT, related_name="status_history"
    )

    class Meta(StatusHistory.Meta):
        db_table = "work_order_status_history"
        abstract = False


class WorkOrderMaterial(AuditedModel):
    """สำเนา BOM ณ เวลาที่ออกใบสั่งผลิต (INVARIANT ข้อ 2)

    ทุกค่าที่ใช้คำนวณต้องอยู่ในแถวนี้เอง แถวนี้ต้องยืนอยู่ได้แม้ BOM ต้นฉบับ
    ถูกลบทั้งฉบับ source_bom_* จึงเป็น IntegerField ไม่ใช่ FK โดยตั้งใจ
    """

    work_order = models.ForeignKey(WorkOrder, on_delete=models.PROTECT, related_name="materials")
    line_no = models.PositiveIntegerField()
    component_item = models.ForeignKey(Item, on_delete=models.PROTECT, related_name="+")
    qty_per = QtyField()
    scrap_pct = PercentField(default=0)
    qty_required = QtyField()
    uom = models.ForeignKey(Uom, on_delete=models.PROTECT, related_name="+")
    standard_unit_cost = AmountField(default=0)
    bom_level = models.PositiveSmallIntegerField(default=1)

    source_bom_header_id = models.IntegerField(null=True, blank=True)
    source_bom_line_id = models.IntegerField(null=True, blank=True)
    bom_revision = models.CharField(max_length=16, blank=True)

    class Meta:
        db_table = "work_order_materials"
        ordering = ["work_order_id", "line_no"]
        constraints = [
            models.UniqueConstraint(
                fields=["work_order", "line_no"], name="uniq_wo_material_line"
            )
        ]

    def __str__(self):
        return f"{self.work_order.wo_no}/{self.line_no} {self.component_item.code}"


class WorkOrderOperation(AuditedModel):
    """สำเนา Routing ณ เวลาที่ออกใบสั่งผลิต (INVARIANT ข้อ 2)"""

    work_order = models.ForeignKey(WorkOrder, on_delete=models.PROTECT, related_name="operations")
    sequence = models.PositiveIntegerField()
    work_center = models.ForeignKey(WorkCenter, on_delete=models.PROTECT, related_name="+")
    name = models.CharField(max_length=128)
    setup_minutes = QtyField(default=0)
    run_minutes_per_unit = QtyField(default=0)
    labor_rate_per_hour = AmountField(default=0)
    overhead_rate_per_hour = AmountField(default=0)

    qty_good = QtyField(default=0)
    qty_scrap = QtyField(default=0)
    actual_minutes = QtyField(default=0)
    status = models.CharField(max_length=16, choices=OP_STATUS_CHOICES, default=OP_PENDING)

    source_routing_header_id = models.IntegerField(null=True, blank=True)
    source_routing_operation_id = models.IntegerField(null=True, blank=True)
    routing_revision = models.CharField(max_length=16, blank=True)

    class Meta:
        db_table = "work_order_operations"
        ordering = ["work_order_id", "sequence"]
        constraints = [
            models.UniqueConstraint(
                fields=["work_order", "sequence"], name="uniq_wo_operation_sequence"
            )
        ]

    def __str__(self):
        return f"{self.work_order.wo_no}/{self.sequence:03d} {self.name}"

    @property
    def is_last(self):
        return not (
            WorkOrderOperation.objects.filter(
                work_order_id=self.work_order_id, sequence__gt=self.sequence
            ).exists()
        )


class ShopFloorReport(AuditedModel):
    """บันทึกผลหน้างานหนึ่งครั้ง — client_ref ทำให้ยิงซ้ำไม่เกิดผลซ้ำ

    ฟิลด์ที่ระบบเติมเอง (posted_by, work_center, shift) ห้ามรับจาก client
    """

    client_ref = models.UUIDField(unique=True, default=uuid.uuid4)
    work_order = models.ForeignKey(WorkOrder, on_delete=models.PROTECT, related_name="reports")
    operation = models.ForeignKey(
        WorkOrderOperation, on_delete=models.PROTECT, related_name="reports"
    )
    qty_good = QtyField(default=0)
    qty_scrap = QtyField(default=0)
    scrap_reason = models.ForeignKey(
        ScrapReason, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    # ระบบเติมเอง
    posted_at = models.DateTimeField(db_index=True)
    posted_by = models.ForeignKey(
        "common.User", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    work_center = models.ForeignKey(WorkCenter, on_delete=models.PROTECT, related_name="+")
    shift = models.CharField(max_length=8, blank=True)
    has_exception = models.BooleanField(default=False)

    class Meta:
        db_table = "shop_floor_reports"
        ordering = ["-posted_at", "-id"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(qty_good__gte=0) & models.Q(qty_scrap__gte=0),
                name="shop_floor_qty_non_negative",
            ),
            models.CheckConstraint(
                condition=models.Q(qty_good__gt=0) | models.Q(qty_scrap__gt=0),
                name="shop_floor_qty_not_all_zero",
            ),
        ]

    def __str__(self):
        return f"{self.work_order.wo_no} op{self.operation.sequence} {self.client_ref}"


class BackflushException(AuditedModel):
    """วัตถุดิบที่ตัดไม่ได้เพราะของไม่พอ — เข้าคิวให้ฝ่ายวางแผนตามแก้

    การมีตารางนี้คือเหตุผลที่ "หน้างานไม่ถูกบล็อก" กับ "ยอดสต็อกไม่ติดลบ"
    อยู่ด้วยกันได้ ยอดที่ตัดค้างมองเห็นได้ ไม่ได้หายไปเงียบ ๆ
    """

    report = models.ForeignKey(
        ShopFloorReport, on_delete=models.PROTECT, related_name="backflush_exceptions"
    )
    work_order = models.ForeignKey(WorkOrder, on_delete=models.PROTECT, related_name="+")
    material = models.ForeignKey(WorkOrderMaterial, on_delete=models.PROTECT, related_name="+")
    qty_short = QtyField()
    uom = models.ForeignKey(Uom, on_delete=models.PROTECT, related_name="+")
    detail = models.TextField(blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolved_by = models.ForeignKey(
        "common.User", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )

    class Meta:
        db_table = "backflush_exceptions"
        ordering = ["resolved_at", "-id"]

    def __str__(self):
        return f"{self.work_order.wo_no} {self.material.component_item.code} ขาด {self.qty_short}"
