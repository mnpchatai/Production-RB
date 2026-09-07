"""สถานการณ์ 6 — แก้ BOM ระหว่างที่ใบสั่งผลิตเดิมยังไม่ปิด"""

from datetime import date
from decimal import Decimal

import pytest
from django.db.models import Sum

from apps.bom.models import ACTIVE, BomHeader, BomLine
from apps.inventory.models import ISSUE_TO_WO, StockTransaction
from conftest import assert_view_matches_ledger, make_work_order, receive, report


@pytest.mark.django_db(transaction=True)
def test_open_work_order_keeps_its_original_recipe(seeded):
    env = seeded
    receive(env, "SFG-CMP-01", "1000", lot="SFG-LOT-1")

    old_order = make_work_order(env, qty="100")
    report(env, old_order, 10, "50")

    issued_before = StockTransaction.objects.filter(
        doc_no=old_order.wo_no, txn_type=ISSUE_TO_WO, item__code="SFG-CMP-01"
    ).aggregate(total=Sum("qty_base"))["total"]

    # ฝ่ายวิศวกรรมออกสูตรใหม่ที่ใช้ยางผสมมากขึ้นเท่าตัว
    old_bom = BomHeader.objects.get(item__code="FG-RB-001", revision="A")
    old_bom.effective_to = date.today()
    old_bom.save()
    new_bom = BomHeader.objects.create(
        item=env["items"]["FG-RB-001"],
        revision="B",
        effective_from=date.today(),
        status=ACTIVE,
    )
    BomLine.objects.create(
        bom=new_bom,
        sequence=10,
        component_item=env["items"]["SFG-CMP-01"],
        qty_per=Decimal("0.5000"),
        uom=env["uoms"]["KG"],
        scrap_pct=Decimal(0),
    )
    BomLine.objects.create(
        bom=new_bom,
        sequence=20,
        component_item=env["items"]["PKG-BOX-01"],
        qty_per=Decimal("1.0000"),
        uom=env["uoms"]["PC"],
        scrap_pct=Decimal(0),
    )

    # ใบเดิมผลิตต่อ ต้องยังตัดตามสูตรเดิม
    report(env, old_order, 10, "50")
    issued_after = StockTransaction.objects.filter(
        doc_no=old_order.wo_no, txn_type=ISSUE_TO_WO, item__code="SFG-CMP-01"
    ).aggregate(total=Sum("qty_base"))["total"]

    assert issued_after == issued_before * 2, "ใบเดิมเปลี่ยนไปใช้สูตรใหม่"
    assert old_order.materials.get(component_item__code="SFG-CMP-01").qty_per == Decimal("0.2500")
    assert old_order.bom_revision == "A"

    # ใบใหม่ต้องใช้สูตรใหม่
    new_order = make_work_order(env, qty="100")
    assert new_order.bom_revision == "B"
    assert new_order.materials.get(component_item__code="SFG-CMP-01").qty_required == Decimal(
        "50.0000"
    )

    assert_view_matches_ledger()
