"""สถานการณ์ 5 — ยกเลิกใบสั่งผลิตหลังเบิกของไปแล้ว ต้องคืนของเข้าคลัง"""

from decimal import Decimal

import pytest

from apps.common.state_machine import CANCELLED, RELEASED, TransitionBlocked, transition
from apps.inventory.services import balance_of
from apps.production.services import cancel_work_order, issue_materials
from conftest import assert_view_matches_ledger, make_work_order, receive


@pytest.mark.django_db(transaction=True)
def test_cancelling_returns_every_issued_material(seeded):
    env = seeded
    receive(env, "SFG-CMP-01", "500", lot="SFG-LOT-1")
    sfg_before = balance_of(env["items"]["SFG-CMP-01"].pk, env["locations"]["RM-01"].pk)
    pkg_before = balance_of(env["items"]["PKG-BOX-01"].pk, env["locations"]["RM-01"].pk)

    work_order = make_work_order(env, qty="100")
    issue_materials(work_order, env["user"])

    assert balance_of(env["items"]["SFG-CMP-01"].pk, env["locations"]["WIP-RB"].pk) > 0

    cancel_work_order(work_order, env["user"], "ลูกค้ายกเลิกออเดอร์")
    work_order.refresh_from_db()

    assert work_order.status == CANCELLED
    assert work_order.cancel_reason == "ลูกค้ายกเลิกออเดอร์"
    assert work_order.cancelled_at is not None
    assert work_order.cancelled_by == env["user"]

    # ของกลับเข้าคลังครบ WIP เป็นศูนย์
    assert balance_of(env["items"]["SFG-CMP-01"].pk, env["locations"]["RM-01"].pk) == sfg_before
    assert balance_of(env["items"]["PKG-BOX-01"].pk, env["locations"]["RM-01"].pk) == pkg_before
    assert balance_of(env["items"]["SFG-CMP-01"].pk, env["locations"]["WIP-RB"].pk) == Decimal(0)

    assert_view_matches_ledger()


@pytest.mark.django_db(transaction=True)
def test_cannot_bypass_the_return_by_calling_transition_directly(seeded):
    """เงื่อนไขอยู่ใน state machine ไม่ใช่ใน service — เรียกลัดก็ยังถูกบล็อก"""
    env = seeded
    receive(env, "SFG-CMP-01", "500", lot="SFG-LOT-1")
    work_order = make_work_order(env, qty="100")
    issue_materials(work_order, env["user"])

    with pytest.raises(TransitionBlocked) as exc:
        transition(work_order, CANCELLED, env["user"], reason="ลัดขั้นตอน")
    assert "ยังไม่ได้คืน" in str(exc.value)

    work_order.refresh_from_db()
    assert work_order.status == RELEASED


@pytest.mark.django_db(transaction=True)
def test_work_order_row_is_never_deleted_after_cancelling(seeded):
    from apps.production.models import WorkOrder

    env = seeded
    work_order = make_work_order(env, qty="10")
    cancel_work_order(work_order, env["user"], "ยกเลิกก่อนเริ่ม")
    assert WorkOrder.objects.filter(pk=work_order.pk).exists()
    assert WorkOrder.objects.get(pk=work_order.pk).status == CANCELLED
