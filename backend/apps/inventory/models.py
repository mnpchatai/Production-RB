from django.db import models

from apps.common.fields import AmountField, QtyField
from apps.common.models import AuditedModel
from apps.masterdata.models import Item, Location, Uom

RECEIPT = "receipt"
ISSUE_TO_WO = "issue_to_wo"
RETURN_FROM_WO = "return_from_wo"
WO_OUTPUT = "wo_output"
TRANSFER = "transfer"
ADJUSTMENT = "adjustment"
DELIVERY = "delivery"
SCRAP = "scrap"
CONSUME_FROM_WIP = "consume_from_wip"

TXN_TYPE_CHOICES = [
    (RECEIPT, "รับเข้า"),
    (ISSUE_TO_WO, "เบิกเข้าใบสั่งผลิต"),
    (RETURN_FROM_WO, "คืนจากใบสั่งผลิต"),
    (WO_OUTPUT, "รับผลผลิตเข้าคลัง"),
    (TRANSFER, "โอนย้าย"),
    (ADJUSTMENT, "ปรับปรุงยอด"),
    (DELIVERY, "ส่งของ"),
    (SCRAP, "ตัดของเสีย"),
    (CONSUME_FROM_WIP, "ตัดวัตถุดิบออกจาก WIP ตอนปิดงาน"),
]

# ทิศทางของแต่ละชนิดธุรกรรม — บังคับด้วย CheckConstraint ที่ฐานข้อมูล
# wo_output เป็นการ "สร้าง" สินค้าขึ้นมาจากกระบวนการผลิต จึงมีแต่ขาเข้า
# วัตถุดิบที่ค้างใน WIP ถูกตัดออกด้วย consume_from_wip ตอนปิดใบสั่งผลิต
INFLOW_ONLY = [RECEIPT, WO_OUTPUT]
OUTFLOW_ONLY = [DELIVERY, CONSUME_FROM_WIP]
BOTH_SIDES = [ISSUE_TO_WO, RETURN_FROM_WO, TRANSFER, SCRAP]


class StockTransaction(AuditedModel):
    """แกนกลางของระบบ — ยอดคงเหลือทุกยอดคำนวณจากตารางนี้เท่านั้น

    ธุรกรรมเป็น append-only ไม่มีการแก้ไขหรือลบ การกลับรายการทำด้วยการ
    ลงธุรกรรมตรงข้าม
    """

    txn_no = models.CharField(max_length=32, unique=True)
    txn_type = models.CharField(max_length=24, choices=TXN_TYPE_CHOICES, db_index=True)

    doc_type = models.CharField(max_length=32, blank=True, db_index=True)
    doc_no = models.CharField(max_length=32, blank=True, db_index=True)
    doc_line_id = models.IntegerField(null=True, blank=True)

    item = models.ForeignKey(Item, on_delete=models.PROTECT, related_name="stock_transactions")
    lot_no = models.CharField(max_length=64, blank=True, db_index=True)
    serial_no = models.CharField(max_length=64, blank=True, db_index=True)

    from_location = models.ForeignKey(
        Location, null=True, blank=True, on_delete=models.PROTECT, related_name="outgoing"
    )
    to_location = models.ForeignKey(
        Location, null=True, blank=True, on_delete=models.PROTECT, related_name="incoming"
    )

    # qty/uom = ค่าที่ผู้ใช้กรอกจริง ห้ามแก้ให้เป็นหน่วยอื่น (INVARIANT ข้อ 4)
    qty = QtyField()
    uom = models.ForeignKey(Uom, on_delete=models.PROTECT, related_name="+")
    # qty_base = ค่าเดียวกันในหน่วยนับหลักของ item คำนวณครั้งเดียวตอนลงธุรกรรม
    # เป็นค่าที่ derive ได้เสมอจาก qty/uom — ไม่ใช่ยอดคงเหลือที่เขียนทับได้
    qty_base = QtyField()

    unit_cost = AmountField(default=0)
    total_cost = AmountField(default=0)

    posted_at = models.DateTimeField(db_index=True)
    posted_by = models.ForeignKey(
        "common.User", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )

    client_ref = models.UUIDField(db_index=True)
    client_seq = models.PositiveSmallIntegerField(default=1)
    is_auto_backflush = models.BooleanField(default=False)

    class Meta:
        db_table = "stock_transactions"
        ordering = ["posted_at", "txn_no"]
        indexes = [
            models.Index(fields=["item", "from_location", "lot_no"], name="stx_item_from_lot"),
            models.Index(fields=["item", "to_location", "lot_no"], name="stx_item_to_lot"),
            models.Index(fields=["doc_type", "doc_no"], name="stx_doc"),
        ]
        constraints = [
            # INVARIANT ข้อ 8 — ยิงซ้ำด้วย client_ref เดิมต้องไม่เกิดธุรกรรมซ้ำ
            models.UniqueConstraint(
                fields=["client_ref", "client_seq"], name="uniq_client_ref_seq"
            ),
            models.CheckConstraint(condition=models.Q(qty__gt=0), name="stock_txn_qty_positive"),
            models.CheckConstraint(
                condition=models.Q(qty_base__gt=0), name="stock_txn_qty_base_positive"
            ),
            models.CheckConstraint(
                condition=~models.Q(from_location=models.F("to_location")),
                name="stock_txn_locations_distinct",
            ),
            # ทิศทางของแต่ละ txn_type บังคับที่ฐานข้อมูล ไม่ปล่อยให้ service จำเอง
            models.CheckConstraint(
                condition=(
                    (
                        models.Q(txn_type__in=INFLOW_ONLY)
                        & models.Q(from_location__isnull=True)
                        & models.Q(to_location__isnull=False)
                    )
                    | (
                        models.Q(txn_type__in=OUTFLOW_ONLY)
                        & models.Q(from_location__isnull=False)
                        & models.Q(to_location__isnull=True)
                    )
                    | (
                        models.Q(txn_type=ADJUSTMENT)
                        & (
                            (
                                models.Q(from_location__isnull=True)
                                & models.Q(to_location__isnull=False)
                            )
                            | (
                                models.Q(from_location__isnull=False)
                                & models.Q(to_location__isnull=True)
                            )
                        )
                    )
                    | (
                        models.Q(txn_type__in=BOTH_SIDES)
                        & models.Q(from_location__isnull=False)
                        & models.Q(to_location__isnull=False)
                    )
                ),
                name="stock_txn_direction_valid",
            ),
        ]

    def __str__(self):
        return f"{self.txn_no} {self.txn_type} {self.item.code} {self.qty} {self.uom.code}"

    def delete(self, *args, **kwargs):
        raise RuntimeError(
            "ห้ามลบธุรกรรมสต็อก — กลับรายการด้วยการลงธุรกรรมตรงข้ามเท่านั้น"
        )


class StockBalance(models.Model):
    """วิวยอดคงเหลือ — สร้างจาก stock_transactions เท่านั้น (INVARIANT ข้อ 3)

    managed = False เพราะเป็น VIEW ไม่ใช่ตาราง เขียนไม่ได้โดยธรรมชาติ
    ล็อกวิวไม่ได้ — ต้องล็อกแถว items ก่อนอ่าน ดู inventory.services.lock_items
    """

    id = models.TextField(primary_key=True)
    item = models.ForeignKey(Item, on_delete=models.DO_NOTHING, related_name="+")
    location = models.ForeignKey(Location, on_delete=models.DO_NOTHING, related_name="+")
    lot_no = models.CharField(max_length=64)
    qty_on_hand = QtyField()

    class Meta:
        managed = False
        db_table = "stock_balances"
        ordering = ["item_id", "location_id", "lot_no"]

    def __str__(self):
        return f"{self.item_id}@{self.location_id} {self.lot_no}: {self.qty_on_hand}"
