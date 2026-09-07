from django.db import models

from apps.common.fields import AmountField, QtyField
from apps.common.models import AuditedModel, DocumentModel, StatusHistory
from apps.common.state_machine import DRAFT
from apps.masterdata.models import Customer, Item, Uom


class SalesOrder(DocumentModel):
    DOC_TYPE = "sales_order"

    so_no = models.CharField(max_length=32, unique=True)
    customer = models.ForeignKey(Customer, on_delete=models.PROTECT, related_name="sales_orders")
    order_date = models.DateField()
    note = models.TextField(blank=True)

    class Meta:
        db_table = "sales_orders"
        ordering = ["-order_date", "-id"]

    def __str__(self):
        return self.so_no


class SalesOrderLine(AuditedModel):
    sales_order = models.ForeignKey(SalesOrder, on_delete=models.PROTECT, related_name="lines")
    line_no = models.PositiveIntegerField()
    item = models.ForeignKey(Item, on_delete=models.PROTECT, related_name="sales_order_lines")
    qty_ordered = QtyField()
    uom = models.ForeignKey(Uom, on_delete=models.PROTECT, related_name="+")
    unit_price = AmountField(default=0)
    due_date = models.DateField()

    class Meta:
        db_table = "sales_order_lines"
        ordering = ["sales_order_id", "line_no"]
        constraints = [
            models.UniqueConstraint(
                fields=["sales_order", "line_no"], name="uniq_so_line_no"
            ),
            models.CheckConstraint(
                condition=models.Q(qty_ordered__gt=0), name="so_line_qty_positive"
            ),
        ]

    def __str__(self):
        return f"{self.sales_order.so_no}/{self.line_no}"

    @property
    def qty_delivered(self):
        """คำนวณจากธุรกรรมส่งของเสมอ — ไม่มีคอลัมน์ที่เขียนทับได้ (INVARIANT ข้อ 3)"""
        from apps.inventory.services import delivered_qty_for_so_line

        return delivered_qty_for_so_line(self)


class SalesOrderStatusHistory(StatusHistory):
    document = models.ForeignKey(
        SalesOrder, on_delete=models.PROTECT, related_name="status_history"
    )

    class Meta(StatusHistory.Meta):
        db_table = "sales_order_status_history"
        abstract = False


def initial_status():
    return DRAFT
