"""สถานการณ์ 3 — ผลิตเกินแผนภายในเกณฑ์ที่ยอมรับได้ และเกินเกณฑ์ต้องถูกปฏิเสธ"""

from decimal import Decimal

import pytest

from apps.production.models import ShopFloorReport
from apps.production.services import OverProductionError
from conftest import assert_view_matches_ledger, make_work_order, receive, report


@pytest.mark.django_db(transaction=True)
def test_over_production_within_tolerance_is_accepted(seeded):
    env = seeded
    receive(env, "SFG-CMP-01", "500", lot="SFG-LOT-1")
    work_order = make_work_order(env, qty="100")  # เกณฑ์ 10% -> รับได้ถึง 110

    report(env, work_order, 10, "105")
    report(env, work_order, 20, "105")
    report(env, work_order, 30, "105")

    work_order.refresh_from_db()
    assert work_order.qty_completed == Decimal("105.0000")
    assert_view_matches_ledger()


@pytest.mark.django_db(transaction=True)
def test_over_production_beyond_tolerance_is_rejected(seeded):
    env = seeded
    receive(env, "SFG-CMP-01", "500", lot="SFG-LOT-1")
    work_order = make_work_order(env, qty="100")

    report(env, work_order, 10, "105")
    report(env, work_order, 20, "105")
    report(env, work_order, 30, "105")
    before = ShopFloorReport.objects.count()

    with pytest.raises(OverProductionError):
        report(env, work_order, 30, "10")  # 115 > 110

    assert ShopFloorReport.objects.count() == before, "บันทึกที่ต้องถูกปฏิเสธยังถูกเก็บไว้"
    work_order.refresh_from_db()
    assert work_order.qty_completed == Decimal("105.0000")


@pytest.mark.django_db(transaction=True)
def test_tolerance_comes_from_master_data_not_a_constant(seeded):
    env = seeded
    item = env["items"]["FG-RB-001"]
    item.over_production_tolerance_pct = Decimal("0")
    item.save()

    receive(env, "SFG-CMP-01", "500", lot="SFG-LOT-1")
    work_order = make_work_order(env, qty="100")
    report(env, work_order, 10, "100")
    report(env, work_order, 20, "100")
    report(env, work_order, 30, "100")

    with pytest.raises(OverProductionError):
        report(env, work_order, 30, "1")
