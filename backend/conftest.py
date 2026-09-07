import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.core.management import call_command
from django.utils import timezone


@pytest.fixture
def seeded(db):
    """ข้อมูลหลักชุดทดสอบ พร้อมของในคลัง"""
    call_command("seed_demo", "--with-stock")
    return _handles()


@pytest.fixture
def seeded_no_stock(db):
    call_command("seed_demo")
    return _handles()


def _handles():
    from apps.common.models import User
    from apps.masterdata.models import Customer, Item, Location, ScrapReason, Uom, WorkCenter

    return {
        "user": User.objects.get(username="admin"),
        "operator": User.objects.get(username="operator1"),
        "items": {i.code: i for i in Item.objects.all()},
        "uoms": {u.code: u for u in Uom.objects.all()},
        "locations": {loc.code: loc for loc in Location.objects.all()},
        "work_centers": {wc.code: wc for wc in WorkCenter.objects.all()},
        "scrap_reasons": {r.code: r for r in ScrapReason.objects.all()},
        "customers": {c.code: c for c in Customer.objects.all()},
    }


@pytest.fixture
def today():
    return date.today()


def make_work_order(env, *, item_code="FG-RB-001", qty="100", as_of=None, release=True):
    """สร้างใบสั่งผลิตแล้วปล่อยงาน — ตัวช่วยที่ใช้ซ้ำในหลายเทสต์"""
    from apps.common.state_machine import APPROVED, RELEASED, transition
    from apps.production.services import create_work_order

    as_of = as_of or date.today()
    item = env["items"][item_code]
    work_order = create_work_order(
        item=item,
        qty_planned=Decimal(qty),
        uom=item.uom,
        due_date=as_of + timedelta(days=7),
        user=env["user"],
        as_of_date=as_of,
        wip_location=env["locations"]["WIP-RB"],
        output_location=env["locations"]["FG-01"],
        scrap_location=env["locations"]["SCRAP"],
    )
    if release:
        transition(work_order, APPROVED, env["user"])
        transition(work_order, RELEASED, env["user"])
    return work_order


def report(env, work_order, sequence, qty_good, qty_scrap=0, **kwargs):
    from apps.production.services import report_shop_floor

    return report_shop_floor(
        client_ref=kwargs.pop("client_ref", uuid.uuid4()),
        wo_no=work_order.wo_no,
        operation_seq=sequence,
        qty_good=Decimal(qty_good),
        qty_scrap=Decimal(qty_scrap),
        user=env["operator"],
        posted_at=kwargs.pop("posted_at", timezone.now()),
        **kwargs,
    )


def receive(env, code, qty, lot="LOT-A", location="RM-01"):
    """รับของเข้าคลังเพื่อตั้งต้นสถานการณ์"""
    import uuid as _uuid
    from decimal import Decimal as _Decimal

    from apps.inventory.models import RECEIPT
    from apps.inventory.services import TxnLine, post_transactions

    item = env["items"][code]
    return post_transactions(
        client_ref=_uuid.uuid4(),
        lines=[
            TxnLine(
                item=item,
                qty=_Decimal(qty),
                uom=item.uom_id,
                txn_type=RECEIPT,
                to_location=env["locations"][location],
                lot_no=lot if item.is_lot_controlled else "",
                unit_cost=item.standard_cost,
                doc_type="test",
                doc_no="SETUP",
            )
        ],
        posted_at=timezone.now(),
        posted_by=env["user"],
    )


def assert_view_matches_ledger():
    """วิวยอดคงเหลือต้องตรงกับผลรวมที่คำนวณเองทุกคีย์ — เรียกท้ายทุกสถานการณ์"""
    from apps.inventory.models import StockBalance, StockTransaction
    from apps.inventory.services import rebuild_balance

    keys = set()
    for txn in StockTransaction.objects.all():
        if txn.from_location_id:
            keys.add((txn.item_id, txn.from_location_id, txn.lot_no))
        if txn.to_location_id:
            keys.add((txn.item_id, txn.to_location_id, txn.lot_no))

    rows = {
        (row.item_id, row.location_id, row.lot_no): row.qty_on_hand
        for row in StockBalance.objects.all()
    }
    for key in keys:
        expected = rebuild_balance(*key)
        assert rows.get(key, Decimal(0)) == expected, f"ยอดไม่ตรงที่ {key}"
    return rows


def assert_cost_drills_down(work_order):
    """ต้นทุนรวมต้องเท่ากับผลรวมของรายบรรทัดที่กางกลับไปหาต้นทางได้"""
    from apps.costing.services import work_order_cost

    cost = work_order_cost(work_order)
    material_lines = sum(
        (line.amount for line in cost.lines if line.source == "material"), Decimal(0)
    )
    labor_lines = sum((line.amount for line in cost.lines if line.source == "labor"), Decimal(0))
    assert cost.material_actual == material_lines
    assert cost.labor_actual + cost.overhead_actual == labor_lines
    for line in cost.lines:
        assert line.reference, "ต้นทุนก้อนนี้ไม่มีเลขที่อ้างอิงกลับไปหาต้นทาง"
    return cost
