from django.db import models

from apps.common.fields import AmountField, PercentField, RateField
from apps.common.models import AuditedModel


class Uom(AuditedModel):
    code = models.CharField(max_length=16, unique=True)
    name = models.CharField(max_length=64)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "uoms"
        ordering = ["code"]

    def __str__(self):
        return self.code


class UomConversion(AuditedModel):
    """1 from_uom = factor to_uom — ทิศย้อนกลับคำนวณเป็น 1/factor ให้เอง"""

    from_uom = models.ForeignKey(Uom, on_delete=models.PROTECT, related_name="conversions_from")
    to_uom = models.ForeignKey(Uom, on_delete=models.PROTECT, related_name="conversions_to")
    factor = RateField()

    class Meta:
        db_table = "uom_conversions"
        constraints = [
            models.UniqueConstraint(fields=["from_uom", "to_uom"], name="uniq_uom_pair"),
            models.CheckConstraint(condition=models.Q(factor__gt=0), name="uom_factor_positive"),
            models.CheckConstraint(
                condition=~models.Q(from_uom=models.F("to_uom")), name="uom_pair_distinct"
            ),
        ]

    def __str__(self):
        return f"1 {self.from_uom} = {self.factor} {self.to_uom}"


class Item(AuditedModel):
    FG = "FG"
    SFG = "SFG"
    RM = "RM"
    PKG = "PKG"
    TYPE_CHOICES = [
        (FG, "สินค้าสำเร็จรูป"),
        (SFG, "กึ่งสำเร็จรูป"),
        (RM, "วัตถุดิบ"),
        (PKG, "บรรจุภัณฑ์"),
    ]

    code = models.CharField(max_length=64, unique=True)
    name = models.CharField(max_length=255)
    item_type = models.CharField(max_length=8, choices=TYPE_CHOICES, db_index=True)
    uom = models.ForeignKey(Uom, on_delete=models.PROTECT, related_name="items")
    is_lot_controlled = models.BooleanField(default=True)
    is_serial_controlled = models.BooleanField(default=False)
    allow_negative = models.BooleanField(
        default=False,
        help_text="ปล่อยให้ยอดคงเหลือติดลบได้หรือไม่ — ตั้ง true เฉพาะกรณีที่จำเป็นจริง",
    )
    standard_cost = AmountField(default=0)
    over_production_tolerance_pct = PercentField(
        default=10, help_text="ผลิตเกินแผนได้ไม่เกินกี่เปอร์เซ็นต์"
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "items"
        ordering = ["code"]

    def __str__(self):
        return f"{self.code} {self.name}"


class Warehouse(AuditedModel):
    code = models.CharField(max_length=32, unique=True)
    name = models.CharField(max_length=128)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "warehouses"
        ordering = ["code"]

    def __str__(self):
        return self.code


class Location(AuditedModel):
    STOCK = "stock"
    WIP = "wip"
    SCRAP = "scrap"
    IN_TRANSIT = "in_transit"
    TYPE_CHOICES = [
        (STOCK, "คลังเก็บ"),
        (WIP, "งานระหว่างผลิต"),
        (SCRAP, "ของเสีย"),
        (IN_TRANSIT, "ระหว่างขนย้าย"),
    ]

    warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT, related_name="locations")
    code = models.CharField(max_length=32)
    name = models.CharField(max_length=128)
    location_type = models.CharField(max_length=16, choices=TYPE_CHOICES, default=STOCK)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "locations"
        ordering = ["warehouse__code", "code"]
        constraints = [
            models.UniqueConstraint(fields=["warehouse", "code"], name="uniq_warehouse_location")
        ]

    def __str__(self):
        return f"{self.warehouse.code}/{self.code}"


class WorkCenter(AuditedModel):
    code = models.CharField(max_length=32, unique=True)
    name = models.CharField(max_length=128)
    wip_location = models.ForeignKey(
        Location, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "work_centers"
        ordering = ["code"]

    def __str__(self):
        return f"{self.code} {self.name}"


class WorkCenterRate(AuditedModel):
    """อัตราค่าแรงและ overhead แบบมีช่วงเวลามีผล

    ห้ามเก็บอัตราเป็นคอลัมน์เดียวบน work_centers เพราะการแก้อัตราวันนี้
    จะทำให้ต้นทุนของใบสั่งผลิตที่ปิดไปแล้วเปลี่ยนย้อนหลัง
    """

    work_center = models.ForeignKey(WorkCenter, on_delete=models.PROTECT, related_name="rates")
    labor_rate_per_hour = AmountField(default=0)
    overhead_rate_per_hour = AmountField(default=0)
    effective_from = models.DateField()
    effective_to = models.DateField(null=True, blank=True)

    class Meta:
        db_table = "work_center_rates"
        ordering = ["work_center__code", "effective_from"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(effective_to__isnull=True)
                | models.Q(effective_to__gt=models.F("effective_from")),
                name="wc_rate_period_valid",
            )
        ]


class ScrapReason(AuditedModel):
    code = models.CharField(max_length=32, unique=True)
    name = models.CharField(max_length=128)
    work_center = models.ForeignKey(
        WorkCenter,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="scrap_reasons",
        help_text="ว่างไว้ = ใช้ได้ทุกหน่วยงาน",
    )
    display_order = models.PositiveSmallIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "scrap_reasons"
        ordering = ["display_order", "code"]

    def __str__(self):
        return f"{self.code} {self.name}"


class Customer(AuditedModel):
    code = models.CharField(max_length=32, unique=True)
    name = models.CharField(max_length=255)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "customers"
        ordering = ["code"]

    def __str__(self):
        return f"{self.code} {self.name}"
