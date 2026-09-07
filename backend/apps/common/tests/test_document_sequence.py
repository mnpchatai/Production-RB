import threading
from datetime import date

import pytest
from django.db import connections

from apps.common.services import next_document_no, next_document_numbers


@pytest.mark.django_db
def test_numbers_are_sequential_with_prefix_and_period(seeded_no_stock):
    first = next_document_no("work_order", on_date=date(2026, 3, 1))
    second = next_document_no("work_order", on_date=date(2026, 3, 2))
    assert first == "WO2026-00001"
    assert second == "WO2026-00002"


@pytest.mark.django_db
def test_counter_resets_per_period(seeded_no_stock):
    next_document_no("stock_txn", on_date=date(2026, 3, 1))
    same_month = next_document_no("stock_txn", on_date=date(2026, 3, 31))
    next_month = next_document_no("stock_txn", on_date=date(2026, 4, 1))
    assert same_month == "ST202603-000002"
    assert next_month == "ST202604-000001"


@pytest.mark.django_db
def test_block_reservation_returns_contiguous_numbers(seeded_no_stock):
    numbers = next_document_numbers("work_order", count=5, on_date=date(2026, 3, 1))
    assert numbers == [f"WO2026-{i:05d}" for i in range(1, 6)]


@pytest.mark.django_db(transaction=True)
def test_ten_threads_get_unique_numbers_with_no_gaps(seeded_no_stock):
    """เทสต์ concurrency ด้วย thread จริงกับ connection แยก ไม่ใช่ mock

    ถ้าจองเลขด้วย MAX(no)+1 เทสต์นี้จะได้เลขซ้ำ
    """
    results = []
    errors = []
    barrier = threading.Barrier(10)

    def worker():
        try:
            barrier.wait(timeout=10)
            results.append(next_document_no("work_order", on_date=date(2026, 3, 1)))
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)
        finally:
            connections.close_all()

    threads = [threading.Thread(target=worker) for _ in range(10)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    assert not errors, errors
    assert len(set(results)) == 10, "เลขซ้ำ"
    assert sorted(results) == [f"WO2026-{i:05d}" for i in range(1, 11)], "มีช่องว่าง"
