"""สถานการณ์ 2 — ผลิตได้ไม่ครบแล้วปิดงาน ยอดค้างต้องหายไปจากแผน"""

from decimal import Decimal

import pytest

from apps.common.state_machine import CLOSED
from apps.inventory.services import balance_of
from apps.production.services import short_close_work_order
from conftest import assert_cost_drills_down, assert_view_matches_ledger, make_work_order, receive, report


@pytest.mark.django_db(transaction=True)
def test_closing_early_removes_remaining_qty_from_the_plan(seeded):
    env = seeded
    receive(env, "SFG-CMP-01", "500", lot="SFG-LOT-1")
    work_order = make_work_order(env, qty="100")

    report(env, work_order, 10, "60")
    report(env, work_order, 20, "60")
    report(env, work_order, 30, "60")

    short_close_work_order(work_order, env["user"], "ลูกค้ายกเลิกส่วนที่เหลือ")
    work_order.refresh_from_db()

    assert work_order.status == CLOSED
    assert work_order.qty_completed == Decimal("60.0000")
    assert work_order.qty_remaining == Decimal("40.0000")
    assert all(op.status == "completed" for op in work_order.operations.all())
    assert work_order.status_history.filter(to_status=CLOSED).exists()

    # ยอดค้างต้องไม่โผล่ในรายงานงานที่ยังต้องทำอีก
    from apps.costing.services import wo_status_report

    open_rows = [
        row for row in wo_status_report() if row["wo_no"] == work_order.wo_no and row["status"] != CLOSED
    ]
    assert open_rows == []

    # WIP ต้องถูกเคลียร์ ไม่ค้างวัตถุดิบของใบที่ปิดไปแล้ว
    assert balance_of(env["items"]["SFG-CMP-01"].pk, env["locations"]["WIP-RB"].pk) == Decimal(0)
    assert balance_of(env["items"]["PKG-BOX-01"].pk, env["locations"]["WIP-RB"].pk) == Decimal(0)
    assert balance_of(
        env["items"]["FG-RB-001"].pk, env["locations"]["FG-01"].pk, work_order.wo_no
    ) == Decimal("60.0000")

    assert_view_matches_ledger()
    assert_cost_drills_down(work_order)
