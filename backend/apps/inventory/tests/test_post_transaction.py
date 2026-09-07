import threading
import uuid
from decimal import Decimal

import pytest
from django.db import connections
from django.utils import timezone

from apps.inventory.models import ISSUE_TO_WO, RECEIPT, TRANSFER, StockTransaction
from apps.inventory.services import (
    LotRequiredError,
    NegativeStockError,
    TxnLine,
    balance_of,
    post_transactions,
    rebuild_balance,
)


def receipt_line(env, code, qty, lot="LOT-A"):
    item = env["items"][code]
    return TxnLine(
        item=item,
        qty=Decimal(qty),
        uom=item.uom_id,
        txn_type=RECEIPT,
        to_location=env["locations"]["RM-01"],
        lot_no=lot if item.is_lot_controlled else "",
        unit_cost=item.standard_cost,
        doc_type="test",
        doc_no="T-001",
    )


def issue_line(env, code, qty, lot="LOT-A"):
    item = env["items"][code]
    return TxnLine(
        item=item,
        qty=Decimal(qty),
        uom=item.uom_id,
        txn_type=ISSUE_TO_WO,
        from_location=env["locations"]["RM-01"],
        to_location=env["locations"]["WIP-RB"],
        lot_no=lot if item.is_lot_controlled else "",
        doc_type="work_order",
        doc_no="WO-TEST",
    )


@pytest.mark.django_db
def test_balance_view_matches_manual_recomputation(seeded_no_stock):
    """ยอดจากวิวต้องตรงกับผลรวมที่คำนวณเองจากทุกแถวเสมอ"""
    env = seeded_no_stock
    post_transactions(
        client_ref=uuid.uuid4(),
        lines=[receipt_line(env, "RM-NR-01", "100")],
        posted_at=timezone.now(),
    )
    post_transactions(
        client_ref=uuid.uuid4(),
        lines=[issue_line(env, "RM-NR-01", "30")],
        posted_at=timezone.now(),
    )
    item_id = env["items"]["RM-NR-01"].pk
    store = env["locations"]["RM-01"].pk
    wip = env["locations"]["WIP-RB"].pk

    assert balance_of(item_id, store, "LOT-A") == Decimal("70.0000")
    assert balance_of(item_id, wip, "LOT-A") == Decimal("30.0000")
    assert rebuild_balance(item_id, store, "LOT-A") == balance_of(item_id, store, "LOT-A")
    assert rebuild_balance(item_id, wip, "LOT-A") == balance_of(item_id, wip, "LOT-A")


@pytest.mark.django_db
def test_uom_conversion_is_stored_alongside_entered_value(seeded_no_stock):
    """qty เก็บตามที่กรอก qty_base เก็บค่าเดียวกันในหน่วยหลัก"""
    env = seeded_no_stock
    item = env["items"]["RM-NR-01"]
    txn = post_transactions(
        client_ref=uuid.uuid4(),
        lines=[
            TxnLine(
                item=item,
                qty=Decimal("2"),
                uom=env["uoms"]["TON"].pk,
                txn_type=RECEIPT,
                to_location=env["locations"]["RM-01"],
                lot_no="LOT-T",
            )
        ],
        posted_at=timezone.now(),
    )[0]
    assert txn.qty == Decimal("2.0000")
    assert txn.uom.code == "TON"
    assert txn.qty_base == Decimal("2000.0000")
    assert balance_of(item.pk, env["locations"]["RM-01"].pk, "LOT-T") == Decimal("2000.0000")


@pytest.mark.django_db
def test_issue_beyond_balance_is_rejected_and_leaves_nothing_behind(seeded_no_stock):
    env = seeded_no_stock
    post_transactions(
        client_ref=uuid.uuid4(),
        lines=[receipt_line(env, "RM-NR-01", "10")],
        posted_at=timezone.now(),
    )
    before = StockTransaction.objects.count()

    with pytest.raises(NegativeStockError):
        post_transactions(
            client_ref=uuid.uuid4(),
            lines=[issue_line(env, "RM-NR-01", "11")],
            posted_at=timezone.now(),
        )

    assert StockTransaction.objects.count() == before, "ธุรกรรมค้างอยู่ทั้งที่ต้อง rollback"
    assert balance_of(env["items"]["RM-NR-01"].pk) == Decimal("10.0000")


@pytest.mark.django_db
def test_allow_negative_item_can_go_below_zero(seeded_no_stock):
    env = seeded_no_stock
    item = env["items"]["RM-CB-01"]
    item.allow_negative = True
    item.save()
    post_transactions(
        client_ref=uuid.uuid4(),
        lines=[issue_line(env, "RM-CB-01", "5")],
        posted_at=timezone.now(),
    )
    assert balance_of(item.pk, env["locations"]["RM-01"].pk, "LOT-A") == Decimal("-5.0000")


@pytest.mark.django_db
def test_lot_controlled_item_requires_lot_no(seeded_no_stock):
    env = seeded_no_stock
    with pytest.raises(LotRequiredError):
        post_transactions(
            client_ref=uuid.uuid4(),
            lines=[receipt_line(env, "RM-NR-01", "10", lot="")],
            posted_at=timezone.now(),
        )


@pytest.mark.django_db
def test_transactions_cannot_be_deleted(seeded):
    txn = StockTransaction.objects.first()
    with pytest.raises(RuntimeError):
        txn.delete()


@pytest.mark.django_db
def test_transfer_to_same_location_rejected_by_database(seeded_no_stock):
    from django.db import IntegrityError, transaction

    env = seeded_no_stock
    item = env["items"]["RM-NR-01"]
    with pytest.raises(IntegrityError), transaction.atomic():
        StockTransaction.objects.create(
            txn_no="X-1",
            txn_type=TRANSFER,
            item=item,
            from_location=env["locations"]["RM-01"],
            to_location=env["locations"]["RM-01"],
            qty=Decimal("1"),
            uom=item.uom,
            qty_base=Decimal("1"),
            posted_at=timezone.now(),
            client_ref=uuid.uuid4(),
        )


@pytest.mark.django_db
def test_wrong_direction_for_txn_type_rejected_by_database(seeded_no_stock):
    """receipt ต้องไม่มีขาออก — บังคับที่ฐานข้อมูล ไม่ใช่แค่ที่ service"""
    from django.db import IntegrityError, transaction

    env = seeded_no_stock
    item = env["items"]["RM-NR-01"]
    with pytest.raises(IntegrityError), transaction.atomic():
        StockTransaction.objects.create(
            txn_no="X-2",
            txn_type=RECEIPT,
            item=item,
            from_location=env["locations"]["RM-01"],
            to_location=env["locations"]["WIP-RB"],
            qty=Decimal("1"),
            uom=item.uom,
            qty_base=Decimal("1"),
            posted_at=timezone.now(),
            client_ref=uuid.uuid4(),
        )


@pytest.mark.django_db(transaction=True)
def test_same_client_ref_posted_ten_times_concurrently_creates_one_transaction(
    seeded_no_stock,
):
    """INVARIANT ข้อ 8 — ยิงซ้ำพร้อมกันต้องได้ธุรกรรมเดียวและยอดถูก"""
    env = seeded_no_stock
    post_transactions(
        client_ref=uuid.uuid4(),
        lines=[receipt_line(env, "RM-NR-01", "1000")],
        posted_at=timezone.now(),
    )
    client_ref = uuid.uuid4()
    errors = []
    barrier = threading.Barrier(10)

    def worker():
        try:
            barrier.wait(timeout=10)
            post_transactions(
                client_ref=client_ref,
                lines=[issue_line(env, "RM-NR-01", "40")],
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
        thread.join(timeout=30)

    assert not errors, errors
    assert StockTransaction.objects.filter(client_ref=client_ref).count() == 1
    item_id = env["items"]["RM-NR-01"].pk
    assert balance_of(item_id, env["locations"]["RM-01"].pk, "LOT-A") == Decimal("960.0000")
    assert balance_of(item_id, env["locations"]["WIP-RB"].pk, "LOT-A") == Decimal("40.0000")


@pytest.mark.django_db(transaction=True)
def test_two_concurrent_issues_when_stock_covers_only_one(seeded_no_stock):
    """ของเหลือพอสำหรับคนเดียว — ต้องสำเร็จคนเดียว ห้ามสำเร็จทั้งคู่"""
    env = seeded_no_stock
    post_transactions(
        client_ref=uuid.uuid4(),
        lines=[receipt_line(env, "RM-NR-01", "10")],
        posted_at=timezone.now(),
    )

    outcomes = []
    barrier = threading.Barrier(2)

    def worker():
        try:
            barrier.wait(timeout=10)
            post_transactions(
                client_ref=uuid.uuid4(),
                lines=[issue_line(env, "RM-NR-01", "8")],
                posted_at=timezone.now(),
            )
            outcomes.append("ok")
        except NegativeStockError:
            outcomes.append("rejected")
        except Exception as exc:  # noqa: BLE001
            outcomes.append(f"unexpected: {exc!r}")
        finally:
            connections.close_all()

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    assert sorted(outcomes) == ["ok", "rejected"], outcomes
    assert balance_of(env["items"]["RM-NR-01"].pk, env["locations"]["RM-01"].pk, "LOT-A") == Decimal(
        "2.0000"
    )
