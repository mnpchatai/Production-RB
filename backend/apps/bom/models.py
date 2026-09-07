from django.db import models

from apps.common.fields import PercentField, QtyField
from apps.common.models import AuditedModel
from apps.masterdata.models import Item, Uom, WorkCenter

DRAFT = "draft"
ACTIVE = "active"
OBSOLETE = "obsolete"
STATUS_CHOICES = [(DRAFT, "ร่าง"), (ACTIVE, "ใช้งาน"), (OBSOLETE, "เลิกใช้")]


class EffectiveDatedHeader(AuditedModel):
    """หัวเอกสารที่มีช่วงเวลามีผล — effective_from <= วันที่ < effective_to"""

    revision = models.CharField(max_length=16)
    effective_from = models.DateField()
    effective_to = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=DRAFT)

    class Meta:
        abstract = True


class BomHeader(EffectiveDatedHeader):
    item = models.ForeignKey(Item, on_delete=models.PROTECT, related_name="boms")

    class Meta:
        db_table = "bom_headers"
        ordering = ["item__code", "-effective_from"]
        constraints = [
            models.UniqueConstraint(fields=["item", "revision"], name="uniq_bom_item_revision"),
            models.CheckConstraint(
                condition=models.Q(effective_to__isnull=True)
                | models.Q(effective_to__gt=models.F("effective_from")),
                name="bom_period_valid",
            ),
        ]

    def __str__(self):
        return f"BOM {self.item.code} rev {self.revision}"


class BomLine(AuditedModel):
    bom = models.ForeignKey(BomHeader, on_delete=models.CASCADE, related_name="lines")
    sequence = models.PositiveIntegerField(default=10)
    component_item = models.ForeignKey(Item, on_delete=models.PROTECT, related_name="used_in_boms")
    qty_per = QtyField(help_text="ปริมาณต่อสินค้าแม่ 1 หน่วยนับหลัก")
    uom = models.ForeignKey(Uom, on_delete=models.PROTECT, related_name="+")
    scrap_pct = PercentField(default=0)
    alternate_of_line = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.CASCADE, related_name="alternates"
    )

    class Meta:
        db_table = "bom_lines"
        ordering = ["bom_id", "sequence", "id"]
        constraints = [
            models.CheckConstraint(condition=models.Q(qty_per__gt=0), name="bom_line_qty_positive"),
            models.CheckConstraint(
                condition=models.Q(scrap_pct__gte=0) & models.Q(scrap_pct__lt=100),
                name="bom_line_scrap_pct_range",
            ),
        ]

    def __str__(self):
        return f"{self.component_item.code} x {self.qty_per} {self.uom.code}"


class RoutingHeader(EffectiveDatedHeader):
    item = models.ForeignKey(Item, on_delete=models.PROTECT, related_name="routings")

    class Meta:
        db_table = "routing_headers"
        ordering = ["item__code", "-effective_from"]
        constraints = [
            models.UniqueConstraint(
                fields=["item", "revision"], name="uniq_routing_item_revision"
            ),
            models.CheckConstraint(
                condition=models.Q(effective_to__isnull=True)
                | models.Q(effective_to__gt=models.F("effective_from")),
                name="routing_period_valid",
            ),
        ]

    def __str__(self):
        return f"Routing {self.item.code} rev {self.revision}"


class RoutingOperation(AuditedModel):
    routing = models.ForeignKey(RoutingHeader, on_delete=models.CASCADE, related_name="operations")
    sequence = models.PositiveIntegerField()
    work_center = models.ForeignKey(WorkCenter, on_delete=models.PROTECT, related_name="operations")
    name = models.CharField(max_length=128)
    setup_minutes = QtyField(default=0)
    run_minutes_per_unit = QtyField(default=0)

    class Meta:
        db_table = "routing_operations"
        ordering = ["routing_id", "sequence"]
        constraints = [
            models.UniqueConstraint(
                fields=["routing", "sequence"], name="uniq_routing_sequence"
            )
        ]

    def __str__(self):
        return f"{self.sequence:03d} {self.name}"
