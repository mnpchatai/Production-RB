"""สถานการณ์ 8 — สองคนบันทึกผลขั้นตอนเดียวกันพร้อมกัน"""

import threading
from decimal import Decimal

import pytest
from django.db import connections
from django.utils import timezone

from apps.production.models import ShopFloorReport
from apps.production.services import report_shop_floor
from conftest import assert_view_matches_ledger, make_work_order, receive
import uuid


@pytest.mark.django_db(transaction=True)
def test_two_operators_on_the_same_operation_are_added_not_overwritten(seeded):
    env = seeded
    receive(env, "SFG-CMP-01", "1000", lot="SFG-LOT-1")
    work_order = make_work_order(env, qty="100")

    errors = []
    barrier = threading.Barrier(2)

    def worker(qty):
        def run():
            try:
                barrier.wait(timeout=10)
                report_shop_floor(
                    client_ref=uuid.uuid4(),
                    wo_no=work_order.wo_no,
                    operation_seq=10,
                    qty_good=Decimal(qty),
                    user=env["operator"],
                    posted_at=timezone.now(),
                )
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)
            finally:
                connections.close_all()

        return run

    threads = [threading.Thread(target=worker("30")), threading.Thread(target=worker("25"))]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)

    assert not errors, errors
    assert ShopFloorReport.objects.filter(work_order=work_order, operation__sequence=10).count() == 2

    work_order.refresh_from_db()
    operation = work_order.operations.get(sequence=10)
    assert operation.qty_good == Decimal("55.0000"), "ผลของคนหนึ่งหายไป (เขียนทับแทนที่จะบวกสะสม)"
    assert_view_matches_ledger()
