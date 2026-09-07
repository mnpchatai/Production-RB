"""สถานการณ์ 4 — ของเสียกลางทางแล้วต้องเบิกวัตถุดิบเพิ่ม"""

from decimal import Decimal

import pytest
from django.db.models import Sum

from apps.inventory.models import ISSUE_TO_WO, StockTransaction
from apps.inventory.services import balance_of
from conftest import assert_cost_drills_down, assert_view_matches_ledger, make_work_order, receive, report


def issued_qty(work_order, item_code):
    return StockTransaction.objects.filter(
        doc_type="work_order",
        doc_no=work_order.wo_no,
        txn_type=ISSUE_TO_WO,
        item__code=item_code,
    ).aggregate(total=Sum("qty_base"))["total"] or Decimal(0)


@pytest.mark.django_db(transaction=True)
def test_scrap_forces_extra_material_to_finish_the_plan(seeded):
    env = seeded
    receive(env, "SFG-CMP-01", "500", lot="SFG-LOT-1")
    work_order = make_work_order(env, qty="100")
    reason = env["scrap_reasons"]["SR01"]

    # รอบแรก: ทำได้ 90 ดี เสีย 10 -> เบิกวัตถุดิบสำหรับ 100 หน่วย
    report(env, work_order, 10, "90", qty_scrap="10", scrap_reason=reason)
    first_issue = issued_qty(work_order, "SFG-CMP-01")

    # ต้องทำเพิ่มอีก 10 เพื่อให้ครบแผน -> เบิกวัตถุดิบเพิ่มตามสัดส่วน
    report(env, work_order, 10, "10")
    total_issue = issued_qty(work_order, "SFG-CMP-01")

    per_unit = first_issue / Decimal(100)
    assert total_issue > first_issue, "ผลิตซ่อมแล้วไม่ได้เบิกวัตถุดิบเพิ่ม"
    assert total_issue == (per_unit * Decimal(110)).quantize(Decimal("0.0001"))

    report(env, work_order, 20, "100")
    report(env, work_order, 30, "100")

    work_order.refresh_from_db()
    assert work_order.qty_completed == Decimal("100.0000")
    assert work_order.qty_scrapped == Decimal("10.0000")
    assert balance_of(
        env["items"]["FG-RB-001"].pk, env["locations"]["FG-01"].pk, work_order.wo_no
    ) == Decimal("100.0000")

    # ของเสียต้องโผล่ในรายงานพร้อมสาเหตุและ work center
    from apps.costing.services import scrap_report

    rows = scrap_report()
    assert any(
        row["scrap_reason__code"] == "SR01" and row["work_center__code"] == "INJ"
        for row in rows
    ), rows

    assert_view_matches_ledger()
    assert_cost_drills_down(work_order)
