"""ข้อมูลตัวอย่างสำหรับทดสอบ — รันซ้ำได้โดยไม่พัง (idempotent)

โครงยึดตามสายการผลิตยางขึ้นรูป: ชั่งเคมี -> ตียาง -> ฉีดยาง -> อบตู้อบ -> อบ HCM
"""

import uuid
from datetime import date, timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.bom.models import ACTIVE, BomHeader, BomLine, RoutingHeader, RoutingOperation
from apps.common.models import DocumentSequence, Role, User
from apps.inventory.models import RECEIPT
from apps.inventory.services import TxnLine, post_transactions
from apps.masterdata.models import (
    Customer,
    Item,
    Location,
    ScrapReason,
    Uom,
    UomConversion,
    Warehouse,
    WorkCenter,
    WorkCenterRate,
)

SEQUENCES = [
    ("sales_order", "SO", "yearly", 5),
    ("work_order", "WO", "yearly", 5),
    ("stock_txn", "ST", "monthly", 6),
]

ROLES = [
    ("sales", "ฝ่ายขาย"),
    ("planner", "ฝ่ายวางแผน"),
    ("supervisor", "หัวหน้ากะ"),
    ("operator", "พนักงานหน้างาน"),
    ("cost_accountant", "ฝ่ายบัญชีต้นทุน"),
]

UOMS = [("KG", "กิโลกรัม"), ("G", "กรัม"), ("TON", "ตัน"), ("PC", "ชิ้น")]
CONVERSIONS = [("KG", "G", "1000"), ("TON", "KG", "1000")]

ITEMS = [
    ("FG-RB-001", "ยางขึ้นรูป RB-001", Item.FG, "PC", True, "0", "10"),
    ("SFG-CMP-01", "ยางผสมสูตร CMP-01", Item.SFG, "KG", True, "0", "5"),
    ("RM-NR-01", "ยางดิบธรรมชาติ", Item.RM, "KG", True, "62.5000", "0"),
    ("RM-CB-01", "ผงคาร์บอนแบล็ค", Item.RM, "KG", True, "28.0000", "0"),
    ("RM-SUL-01", "ผงกำมะถัน", Item.RM, "KG", True, "45.0000", "0"),
    ("PKG-BOX-01", "กล่องบรรจุ", Item.PKG, "PC", False, "12.0000", "0"),
]

WORK_CENTERS = [
    ("CHEM", "ชั่งเคมี", "120.0000", "60.0000"),
    ("MIX", "ตียาง", "180.0000", "150.0000"),
    ("INJ", "ฉีดยาง", "220.0000", "260.0000"),
    ("OVEN", "อบตู้อบ", "140.0000", "180.0000"),
    ("HCM", "อบ HCM", "160.0000", "200.0000"),
]

SCRAP_REASONS = [
    ("SR01", "ยางไม่สุก"),
    ("SR02", "ผิวไม่เรียบ"),
    ("SR03", "ขนาดไม่ได้"),
    ("SR04", "ฟองอากาศ"),
    ("SR05", "สีเพี้ยน"),
    ("SR06", "เครื่องขัดข้อง"),
    ("SR07", "ชั่งสารผิด"),
    ("SR08", "อื่น ๆ"),
]


class Command(BaseCommand):
    help = "สร้างข้อมูลตัวอย่างสำหรับทดสอบ — รันซ้ำได้"

    def add_arguments(self, parser):
        parser.add_argument(
            "--with-stock",
            action="store_true",
            help="รับวัตถุดิบเข้าคลังให้ด้วย เพื่อให้เริ่มผลิตได้ทันที",
        )
        parser.add_argument(
            "--with-orders",
            action="store_true",
            help="สร้างใบสั่งขายและใบสั่งผลิตที่ปล่อยงานแล้ว เพื่อให้หน้าจอมีของให้ดู",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        admin = self._users()
        self._sequences(admin)
        uoms = self._uoms(admin)
        warehouses, locations = self._locations(admin)
        items = self._items(admin, uoms)
        work_centers = self._work_centers(admin, locations)
        self._scrap_reasons(admin, work_centers)
        self._customers(admin)
        self._bom(admin, items, uoms)
        self._routing(admin, items, work_centers)
        if options["with_stock"]:
            self._opening_stock(admin, items, locations)
        if options["with_orders"]:
            self._orders(admin, items, locations)

        self.stdout.write(
            self.style.SUCCESS(
                "สร้างข้อมูลตัวอย่างเรียบร้อย — "
                f"{Item.objects.count()} items, "
                f"{Warehouse.objects.count()} warehouses, "
                f"{WorkCenter.objects.count()} work centers"
            )
        )
        self.stdout.write("ผู้ใช้ทดสอบ: admin / operator1 (รหัสผ่าน demo1234)")

    def _users(self):
        roles = {
            code: Role.objects.get_or_create(code=code, defaults={"name": name})[0]
            for code, name in ROLES
        }
        admin, created = User.objects.get_or_create(
            username="admin",
            defaults={"is_staff": True, "is_superuser": True, "email": "admin@example.com"},
        )
        if created:
            admin.set_password("demo1234")
            admin.save()
        operator, created = User.objects.get_or_create(
            username="operator1", defaults={"employee_code": "EMP-001"}
        )
        if created:
            operator.set_password("demo1234")
            operator.save()
        operator.roles.set([roles["operator"]])
        planner, created = User.objects.get_or_create(username="planner1")
        if created:
            planner.set_password("demo1234")
            planner.save()
        planner.roles.set([roles["planner"]])
        return admin

    def _sequences(self, user):
        for doc_type, prefix, reset_rule, padding in SEQUENCES:
            DocumentSequence.objects.get_or_create(
                doc_type=doc_type,
                defaults={
                    "prefix": prefix,
                    "reset_rule": reset_rule,
                    "padding": padding,
                    "created_by": user,
                    "updated_by": user,
                },
            )

    def _uoms(self, user):
        uoms = {}
        for code, name in UOMS:
            uoms[code] = Uom.objects.get_or_create(
                code=code, defaults={"name": name, "created_by": user, "updated_by": user}
            )[0]
        for from_code, to_code, factor in CONVERSIONS:
            UomConversion.objects.get_or_create(
                from_uom=uoms[from_code],
                to_uom=uoms[to_code],
                defaults={
                    "factor": Decimal(factor),
                    "created_by": user,
                    "updated_by": user,
                },
            )
        return uoms

    def _locations(self, user):
        warehouses = {}
        for code, name in [("WH-RM", "คลังวัตถุดิบ"), ("WH-FG", "คลังสินค้าสำเร็จรูป")]:
            warehouses[code] = Warehouse.objects.get_or_create(
                code=code, defaults={"name": name, "created_by": user, "updated_by": user}
            )[0]

        specs = [
            ("WH-RM", "RM-01", "ชั้นวางวัตถุดิบ", Location.STOCK),
            ("WH-RM", "WIP-RB", "งานระหว่างผลิตแผนก RB", Location.WIP),
            ("WH-RM", "SCRAP", "จุดพักของเสีย", Location.SCRAP),
            ("WH-FG", "FG-01", "ชั้นวางสินค้าสำเร็จรูป", Location.STOCK),
        ]
        locations = {}
        for wh_code, code, name, location_type in specs:
            locations[code] = Location.objects.get_or_create(
                warehouse=warehouses[wh_code],
                code=code,
                defaults={
                    "name": name,
                    "location_type": location_type,
                    "created_by": user,
                    "updated_by": user,
                },
            )[0]
        return warehouses, locations

    def _items(self, user, uoms):
        items = {}
        for code, name, item_type, uom_code, lot, cost, tolerance in ITEMS:
            items[code] = Item.objects.get_or_create(
                code=code,
                defaults={
                    "name": name,
                    "item_type": item_type,
                    "uom": uoms[uom_code],
                    "is_lot_controlled": lot,
                    "standard_cost": Decimal(cost),
                    "over_production_tolerance_pct": Decimal(tolerance),
                    "created_by": user,
                    "updated_by": user,
                },
            )[0]
        return items

    def _work_centers(self, user, locations):
        work_centers = {}
        for code, name, labor, overhead in WORK_CENTERS:
            work_center = WorkCenter.objects.get_or_create(
                code=code,
                defaults={
                    "name": name,
                    "wip_location": locations["WIP-RB"],
                    "created_by": user,
                    "updated_by": user,
                },
            )[0]
            WorkCenterRate.objects.get_or_create(
                work_center=work_center,
                effective_from=date(2020, 1, 1),
                defaults={
                    "labor_rate_per_hour": Decimal(labor),
                    "overhead_rate_per_hour": Decimal(overhead),
                    "created_by": user,
                    "updated_by": user,
                },
            )
            work_centers[code] = work_center
        return work_centers

    def _scrap_reasons(self, user, work_centers):
        for order, (code, name) in enumerate(SCRAP_REASONS, start=1):
            ScrapReason.objects.get_or_create(
                code=code,
                defaults={
                    "name": name,
                    "display_order": order,
                    "created_by": user,
                    "updated_by": user,
                },
            )

    def _customers(self, user):
        for code, name in [("C-001", "บริษัท ตัวอย่างอุตสาหกรรม จำกัด"), ("C-002", "ร้านค้าส่ง ก.")]:
            Customer.objects.get_or_create(
                code=code, defaults={"name": name, "created_by": user, "updated_by": user}
            )

    def _bom(self, user, items, uoms):
        specs = [
            ("SFG-CMP-01", "A", [("RM-NR-01", "0.7000", "KG", "2"), ("RM-CB-01", "0.2500", "KG", "1"), ("RM-SUL-01", "0.0500", "KG", "0")]),
            ("FG-RB-001", "A", [("SFG-CMP-01", "0.2500", "KG", "3"), ("PKG-BOX-01", "1.0000", "PC", "0")]),
        ]
        for item_code, revision, lines in specs:
            header, created = BomHeader.objects.get_or_create(
                item=items[item_code],
                revision=revision,
                defaults={
                    "effective_from": date(2020, 1, 1),
                    "status": ACTIVE,
                    "created_by": user,
                    "updated_by": user,
                },
            )
            if not created:
                continue
            BomLine.objects.bulk_create(
                [
                    BomLine(
                        bom=header,
                        sequence=(index + 1) * 10,
                        component_item=items[component],
                        qty_per=Decimal(qty),
                        uom=uoms[uom_code],
                        scrap_pct=Decimal(scrap),
                        created_by=user,
                        updated_by=user,
                    )
                    for index, (component, qty, uom_code, scrap) in enumerate(lines)
                ]
            )

    def _routing(self, user, items, work_centers):
        specs = [
            (
                "SFG-CMP-01",
                [(10, "CHEM", "ชั่งเคมี", "10", "0.5"), (20, "MIX", "ตียาง", "15", "1.2")],
            ),
            (
                "FG-RB-001",
                [
                    (10, "INJ", "ฉีดยาง", "20", "0.8"),
                    (20, "OVEN", "อบตู้อบ", "15", "1.5"),
                    (30, "HCM", "อบ HCM", "10", "1.0"),
                ],
            ),
        ]
        for item_code, operations in specs:
            header, created = RoutingHeader.objects.get_or_create(
                item=items[item_code],
                revision="A",
                defaults={
                    "effective_from": date(2020, 1, 1),
                    "status": ACTIVE,
                    "created_by": user,
                    "updated_by": user,
                },
            )
            if not created:
                continue
            RoutingOperation.objects.bulk_create(
                [
                    RoutingOperation(
                        routing=header,
                        sequence=sequence,
                        work_center=work_centers[wc_code],
                        name=name,
                        setup_minutes=Decimal(setup),
                        run_minutes_per_unit=Decimal(run),
                        created_by=user,
                        updated_by=user,
                    )
                    for sequence, wc_code, name, setup, run in operations
                ]
            )

    def _orders(self, user, items, locations):
        from apps.common.state_machine import APPROVED, CONFIRMED, RELEASED, transition
        from apps.production.models import WorkOrder
        from apps.production.services import create_work_order
        from apps.sales.services import create_sales_order

        if WorkOrder.objects.exists():
            return

        today = date.today()
        customer = Customer.objects.get(code="C-001")
        order = create_sales_order(
            customer=customer,
            order_date=today,
            user=user,
            lines=[
                {
                    "item": items["FG-RB-001"],
                    "qty_ordered": Decimal("500"),
                    "uom": items["FG-RB-001"].uom,
                    "unit_price": Decimal("48.0000"),
                    "due_date": today + timedelta(days=10),
                }
            ],
        )
        transition(order, CONFIRMED, user, note="ยืนยันจากลูกค้า")
        so_line = order.lines.first()

        # ใบสั่งผลิตยางผสม (SFG) และใบสั่งผลิตสินค้าสำเร็จรูป (FG)
        for item_code, qty, sales_line in [
            ("SFG-CMP-01", Decimal("200"), None),
            ("FG-RB-001", Decimal("500"), so_line),
        ]:
            item = items[item_code]
            work_order = create_work_order(
                item=item,
                qty_planned=qty,
                uom=item.uom,
                due_date=today + timedelta(days=7),
                user=user,
                as_of_date=today,
                wip_location=locations["WIP-RB"],
                output_location=locations["FG-01"],
                scrap_location=locations["SCRAP"],
                source_sales_order_line=sales_line,
            )
            transition(work_order, APPROVED, user, note="อนุมัติแผน")
            transition(work_order, RELEASED, user, note="ปล่อยงานเข้าไลน์")

    def _opening_stock(self, user, items, locations):
        from apps.inventory.models import StockTransaction

        if StockTransaction.objects.filter(txn_type=RECEIPT).exists():
            return
        today = timezone.now()
        lot = f"LOT-{date.today():%Y%m}"
        lines = [
            TxnLine(
                item=items[code],
                qty=Decimal(qty),
                uom=items[code].uom_id,
                txn_type=RECEIPT,
                to_location=locations["RM-01"],
                lot_no=lot if items[code].is_lot_controlled else "",
                unit_cost=items[code].standard_cost,
                doc_type="opening",
                doc_no="OPENING-001",
            )
            for code, qty in [
                ("RM-NR-01", "5000"),
                ("RM-CB-01", "2000"),
                ("RM-SUL-01", "400"),
                ("PKG-BOX-01", "3000"),
            ]
        ]
        post_transactions(
            client_ref=uuid.uuid5(uuid.NAMESPACE_URL, "seed/opening-stock"),
            lines=lines,
            posted_at=today - timedelta(days=1),
            posted_by=user,
        )
