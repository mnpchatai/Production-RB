"""สถานการณ์ 7 — แท็บเล็ตออฟไลน์แล้ว sync ซ้ำ"""

import threading
import uuid
from decimal import Decimal

import pytest
from django.db import connections
from django.utils import timezone

from apps.inventory.models import StockTransaction
from apps.production.models import ShopFloorReport
from apps.production.services import report_shop_floor
from conftest import assert_view_matches_ledger, make_work_order, receive, report


@pytest.mark.django_db(transaction=True)
def test_resending_the_same_client_ref_changes_nothing(seeded):
    env = seeded
    receive(env, "SFG-CMP-01", "500", lot="SFG-LOT-1")
    work_order = make_work_order(env, qty="100")

    client_ref = uuid.uuid4()
    first = report(env, work_order, 10, "40", client_ref=client_ref)
    txn_count = StockTransaction.objects.count()

    for _ in range(5):
        again = report(env, work_order, 10, "40", client_ref=client_ref)
        assert again.pk == first.pk

    assert ShopFloorReport.objects.filter(client_ref=client_ref).count() == 1
    assert StockTransaction.objects.count() == txn_count
    work_order.refresh_from_db()
    assert work_order.operations.get(sequence=10).qty_good == Decimal("40.0000")
    assert_view_matches_ledger()


@pytest.mark.django_db(transaction=True)
def test_ten_concurrent_syncs_of_the_same_client_ref(seeded):
    """เรียงกันผ่านง่ายเกินไป — ต้องยิงพร้อมกันถึงจะจับ race ที่เกิดจริง"""
    env = seeded
    receive(env, "SFG-CMP-01", "500", lot="SFG-LOT-1")
    work_order = make_work_order(env, qty="100")

    client_ref = uuid.uuid4()
    errors = []
    barrier = threading.Barrier(10)

    def worker():
        try:
            barrier.wait(timeout=10)
            report_shop_floor(
                client_ref=client_ref,
                wo_no=work_order.wo_no,
                operation_seq=10,
                qty_good=Decimal("40"),
                user=env["operator"],
                posted_at=timezone.now(),
            )
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)
        finally:
            connections.close_all()

    threads = [threading.Thread(target=worker) for _ in range(10)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)

    assert not errors, errors
    assert ShopFloorReport.objects.filter(client_ref=client_ref).count() == 1
    work_order.refresh_from_db()
    assert work_order.operations.get(sequence=10).qty_good == Decimal("40.0000")
    assert StockTransaction.objects.filter(client_ref=client_ref).count() >= 1
    assert_view_matches_ledger()
