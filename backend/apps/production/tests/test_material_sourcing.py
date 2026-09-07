"""เบิกวัตถุดิบต้องเบิกจากคลังเก็บเท่านั้น"""

import uuid
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.inventory.models import ISSUE_TO_WO, RECEIPT, StockTransaction
from apps.inventory.services import TxnLine, balance_of, post_transactions
from apps.masterdata.models import Location
from apps.production.models import BackflushException
from conftest import make_work_order, receive, report


def put_stock_in(env, code, qty, location_code, lot="LOT-X"):
    item = env["items"][code]
    return post_transactions(
        client_ref=uuid.uuid4(),
        lines=[
            TxnLine(
                item=item,
                qty=Decimal(qty),
                uom=item.uom_id,
                txn_type=RECEIPT,
                to_location=env["locations"][location_code],
                lot_no=lot if item.is_lot_controlled else "",
                unit_cost=item.standard_cost,
                doc_type="test",
                doc_no="SETUP",
            )
        ],
        posted_at=timezone.now(),
        posted_by=env["user"],
    )


@pytest.mark.django_db(transaction=True)
def test_backflush_never_pulls_material_out_of_the_scrap_location(seeded):
    """ของที่อยู่ในจุดพักของเสียต้องไม่ถูกเบิกกลับเข้าไลน์เงียบ ๆ"""
    env = seeded
    put_stock_in(env, "SFG-CMP-01", "500", "SCRAP", lot="SCRAP-LOT")
    work_order = make_work_order(env, qty="100")

    report(env, work_order, 10, "50")

    scrap_location = env["locations"]["SCRAP"]
    assert not StockTransaction.objects.filter(
        txn_type=ISSUE_TO_WO, from_location=scrap_location
    ).exists(), "เบิกวัตถุดิบออกจากจุดพักของเสีย"
    assert balance_of(env["items"]["SFG-CMP-01"].pk, scrap_location.pk) == Decimal("500.0000")
    # ของไม่พอในคลังเก็บ จึงต้องเข้าคิว exception ไม่ใช่ไปหยิบจากที่อื่นมาแทน
    assert BackflushException.objects.filter(work_order=work_order).exists()


@pytest.mark.django_db(transaction=True)
def test_backflush_never_pulls_material_out_of_the_finished_goods_store(seeded):
    """คลังสินค้าสำเร็จรูปก็เป็นคลังเก็บ แต่ต้องไม่ถูกเลือกเพราะยอดมากกว่า
    ถ้าคลังวัตถุดิบมีของพออยู่แล้ว — เลือกที่ไหนก็ได้ขอแค่เป็นคลังเก็บจริง"""
    env = seeded
    put_stock_in(env, "SFG-CMP-01", "500", "RM-01", lot="RM-LOT")
    put_stock_in(env, "SFG-CMP-01", "9000", "FG-01", lot="FG-LOT")
    work_order = make_work_order(env, qty="100")

    report(env, work_order, 10, "50")

    issues = StockTransaction.objects.filter(txn_type=ISSUE_TO_WO, item__code="SFG-CMP-01")
    assert issues.exists()
    for txn in issues:
        assert txn.from_location.location_type == Location.STOCK


@pytest.mark.django_db(transaction=True)
def test_manual_issue_also_refuses_the_scrap_location(seeded):
    from apps.inventory.services import NegativeStockError
    from apps.production.services import issue_materials

    env = seeded
    put_stock_in(env, "SFG-CMP-01", "500", "SCRAP", lot="SCRAP-LOT")
    put_stock_in(env, "PKG-BOX-01", "500", "SCRAP")
    work_order = make_work_order(env, qty="100")

    with pytest.raises(NegativeStockError):
        issue_materials(work_order, env["user"])
    assert not StockTransaction.objects.filter(txn_type=ISSUE_TO_WO).exists()
