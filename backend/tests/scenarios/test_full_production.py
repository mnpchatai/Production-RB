"""สถานการณ์ 1 — ผลิตครบตามแผน จบทุกขั้นตอน"""

from decimal import Decimal

import pytest

from apps.common.state_machine import CLOSED, COMPLETED, IN_PROGRESS, transition
from apps.inventory.services import balance_of
from apps.production.services import close_work_order, recalculate_progress
from conftest import assert_cost_drills_down, assert_view_matches_ledger, make_work_order, receive, report


@pytest.mark.django_db(transaction=True)
def test_produce_full_quantity_through_every_operation(seeded):
    env = seeded
    receive(env, "SFG-CMP-01", "500", lot="SFG-LOT-1")

    work_order = make_work_order(env, qty="100")
    sfg_before = balance_of(env["items"]["SFG-CMP-01"].pk, env["locations"]["RM-01"].pk)

    report(env, work_order, 10, "100")
    work_order.refresh_from_db()
    assert work_order.status == IN_PROGRESS

    report(env, work_order, 20, "100")
    report(env, work_order, 30, "100")

    work_order.refresh_from_db()
    assert work_order.qty_completed == Decimal("100.0000")
    assert recalculate_progress(work_order)[0] == work_order.qty_completed

    transition(work_order, COMPLETED, env["user"])
    close_work_order(work_order, env["user"])
    work_order.refresh_from_db()
    assert work_order.status == CLOSED

    # สินค้าสำเร็จรูปเข้าคลัง
    assert balance_of(
        env["items"]["FG-RB-001"].pk, env["locations"]["FG-01"].pk, work_order.wo_no
    ) == Decimal("100.0000")

    # วัตถุดิบถูกตัดตามแผน แล้ว WIP ถูกเคลียร์ตอนปิดงาน
    expected_sfg = (Decimal(100) * Decimal("0.25") / (Decimal(97) / Decimal(100))).quantize(
        Decimal("0.0001")
    )
    sfg_after = balance_of(env["items"]["SFG-CMP-01"].pk, env["locations"]["RM-01"].pk)
    assert sfg_before - sfg_after == expected_sfg
    assert balance_of(env["items"]["SFG-CMP-01"].pk, env["locations"]["WIP-RB"].pk) == Decimal(0)
    assert balance_of(env["items"]["PKG-BOX-01"].pk, env["locations"]["WIP-RB"].pk) == Decimal(0)

    assert_view_matches_ledger()
    cost = assert_cost_drills_down(work_order)
    assert cost.material_actual > 0
    assert cost.total_actual == cost.material_actual + cost.labor_actual + cost.overhead_actual
