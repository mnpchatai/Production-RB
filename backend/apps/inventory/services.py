"""ธุรกรรมสต็อก — แกนกลางของระบบ

กฎการล็อก (INVARIANT ข้อ 10):
วิว stock_balances ล็อกไม่ได้ จึงล็อกแถว items ที่เป็นเจ้าของยอดนั้นแทน
และล็อกเรียงตาม item_id เสมอทุกที่ในระบบ เพื่อกัน deadlock ตอนธุรกรรม
หลายบรรทัดแตะ item ชุดเดียวกันคนละลำดับ
"""

from dataclasses import dataclass, field
from decimal import Decimal
from functools import reduce
from operator import or_

from django.db import IntegrityError, transaction
from django.db.models import Q, Sum

from apps.common.services import next_document_numbers
from apps.masterdata.models import Item
from apps.masterdata.services import conversion_graph, convert

from .models import (
    DELIVERY,
    ISSUE_TO_WO,
    RETURN_FROM_WO,
    StockBalance,
    StockTransaction,
)

ZERO = Decimal("0")


class NegativeStockError(Exception):
    """ยอดจะติดลบสำหรับ item ที่ allow_negative = false"""


class LotRequiredError(Exception):
    """item ที่ควบคุมด้วย lot ต้องระบุ lot_no ทุกธุรกรรม"""


@dataclass
class TxnLine:
    item: object
    qty: Decimal
    uom: object
    txn_type: str
    from_location: object = None
    to_location: object = None
    lot_no: str = ""
    serial_no: str = ""
    unit_cost: Decimal = ZERO
    doc_type: str = ""
    doc_no: str = ""
    doc_line_id: int | None = None
    is_auto_backflush: bool = False
    extra: dict = field(default_factory=dict)

    @property
    def item_id(self):
        return self.item if isinstance(self.item, int) else self.item.pk


def lock_items(item_ids):
    """ล็อกแถว items เรียงตาม id — ต้องเรียกก่อนอ่านยอดคงเหลือทุกครั้ง"""
    ordered = sorted(set(item_ids))
    if not ordered:
        return []
    return list(Item.objects.select_for_update().filter(pk__in=ordered).order_by("pk"))


def balance_of(item, location=None, lot_no=None):
    """ยอดคงเหลือในหน่วยนับหลักของ item — อ่านจากวิวเสมอ"""
    item_id = item if isinstance(item, int) else item.pk
    qs = StockBalance.objects.filter(item_id=item_id)
    if location is not None:
        qs = qs.filter(location_id=location if isinstance(location, int) else location.pk)
    if lot_no is not None:
        qs = qs.filter(lot_no=lot_no)
    return qs.aggregate(total=Sum("qty_on_hand"))["total"] or ZERO


def balances_for(keys):
    """ยอดของหลาย (item, location, lot) ในคิวรีเดียว"""
    if not keys:
        return {}
    condition = reduce(
        or_,
        (Q(item_id=i, location_id=loc, lot_no=lot) for i, loc, lot in keys),
    )
    rows = StockBalance.objects.filter(condition).values_list(
        "item_id", "location_id", "lot_no", "qty_on_hand"
    )
    return {(i, loc, lot): qty for i, loc, lot, qty in rows}


@transaction.atomic
def post_transactions(*, client_ref, lines, posted_at, posted_by=None, on_date=None):
    """ลงธุรกรรมสต็อกหนึ่งชุดภายใต้ client_ref เดียว

    ยิงซ้ำด้วย client_ref เดิมคืนธุรกรรมชุดเดิมโดยไม่สร้างใหม่ (INVARIANT ข้อ 8)
    ทั้งชุดอยู่ใน transaction เดียว — บรรทัดใดพังทั้งชุดไม่เกิด (INVARIANT ข้อ 10)
    """
    existing = list(
        StockTransaction.objects.filter(client_ref=client_ref).order_by("client_seq")
    )
    if existing:
        return existing
    if not lines:
        return []

    try:
        with transaction.atomic():
            return _create_transactions(
                client_ref=client_ref,
                lines=lines,
                posted_at=posted_at,
                posted_by=posted_by,
                on_date=on_date,
            )
    except IntegrityError:
        # อีก transaction ลง client_ref เดียวกันไปก่อนแล้วและ commit ไปแล้ว
        existing = list(
            StockTransaction.objects.filter(client_ref=client_ref).order_by("client_seq")
        )
        if not existing:
            raise
        return existing


def _create_transactions(*, client_ref, lines, posted_at, posted_by, on_date):
    lock_items(line.item_id for line in lines)

    graph = conversion_graph()
    items = {
        item.pk: item
        for item in Item.objects.select_related("uom").filter(
            pk__in={line.item_id for line in lines}
        )
    }
    numbers = next_document_numbers(
        "stock_txn", count=len(lines), on_date=on_date, user=posted_by
    )

    created = []
    outflow_keys = set()
    for seq, (line, txn_no) in enumerate(zip(lines, numbers, strict=True), start=1):
        item = items[line.item_id]
        lot_no = (line.lot_no or "").strip()
        if item.is_lot_controlled and not lot_no:
            raise LotRequiredError(
                f"item {item.code} ควบคุมด้วย lot — ธุรกรรมต้องระบุ lot_no"
            )
        if item.is_serial_controlled and not (line.serial_no or "").strip():
            raise LotRequiredError(
                f"item {item.code} ควบคุมด้วย serial — ธุรกรรมต้องระบุ serial_no"
            )

        qty = Decimal(line.qty)
        if qty <= 0:
            raise ValueError(f"จำนวนต้องมากกว่าศูนย์ (item {item.code}, qty {qty})")
        uom_id = line.uom if isinstance(line.uom, int) else line.uom.pk
        qty_base = convert(qty, uom_id, item.uom_id, graph)
        unit_cost = Decimal(line.unit_cost or 0)

        txn = StockTransaction.objects.create(
            txn_no=txn_no,
            txn_type=line.txn_type,
            doc_type=line.doc_type,
            doc_no=line.doc_no,
            doc_line_id=line.doc_line_id,
            item=item,
            lot_no=lot_no,
            serial_no=(line.serial_no or "").strip(),
            from_location=line.from_location,
            to_location=line.to_location,
            qty=qty,
            uom_id=uom_id,
            qty_base=qty_base,
            unit_cost=unit_cost,
            total_cost=(unit_cost * qty_base).quantize(Decimal("0.0001")),
            posted_at=posted_at,
            posted_by=posted_by,
            client_ref=client_ref,
            client_seq=seq,
            is_auto_backflush=line.is_auto_backflush,
            created_by=posted_by,
            updated_by=posted_by,
        )
        created.append(txn)
        if txn.from_location_id is not None:
            outflow_keys.add((item.pk, txn.from_location_id, lot_no))

    _assert_no_negative(outflow_keys, items)
    return created


def _assert_no_negative(outflow_keys, items):
    """ตรวจหลังลงธุรกรรม — วิวมองเห็นแถวที่เพิ่ง insert ใน transaction เดียวกัน"""
    checkable = {
        key for key in outflow_keys if not items[key[0]].allow_negative
    }
    if not checkable:
        return
    balances = balances_for(checkable)
    for key in sorted(checkable):
        qty = balances.get(key, ZERO)
        if qty < 0:
            item = items[key[0]]
            raise NegativeStockError(
                f"ยอดคงเหลือติดลบ: {item.code} ที่ location {key[1]} "
                f"lot {key[2] or '-'} จะเหลือ {qty} {item.uom.code}"
            )


def post_transaction(*, client_ref, line, posted_at, posted_by=None, on_date=None):
    return post_transactions(
        client_ref=client_ref,
        lines=[line],
        posted_at=posted_at,
        posted_by=posted_by,
        on_date=on_date,
    )[0]


def outstanding_wo_issues(work_order):
    """วัตถุดิบที่เบิกเข้าใบสั่งผลิตแล้วยังไม่ได้คืน — ใช้ตอนตรวจก่อนยกเลิก WO"""
    rows = (
        StockTransaction.objects.filter(
            doc_type="work_order",
            doc_no=work_order.wo_no,
            txn_type__in=[ISSUE_TO_WO, RETURN_FROM_WO],
        )
        .values("item__code", "txn_type")
        .annotate(total=Sum("qty_base"))
    )
    net: dict[str, Decimal] = {}
    for row in rows:
        sign = 1 if row["txn_type"] == ISSUE_TO_WO else -1
        net[row["item__code"]] = net.get(row["item__code"], ZERO) + sign * row["total"]
    return {code: qty for code, qty in net.items() if qty > 0}


def delivered_qty_for_so_line(so_line):
    total = StockTransaction.objects.filter(
        txn_type=DELIVERY, doc_type="sales_order", doc_line_id=so_line.pk
    ).aggregate(total=Sum("qty_base"))["total"]
    return total or ZERO


def rebuild_balance(item_id, location_id, lot_no=""):
    """คำนวณยอดใหม่จากศูนย์โดยไม่ผ่านวิว — ใช้พิสูจน์ว่าวิวถูกต้อง"""
    incoming = StockTransaction.objects.filter(
        item_id=item_id, to_location_id=location_id, lot_no=lot_no
    ).aggregate(total=Sum("qty_base"))["total"] or ZERO
    outgoing = StockTransaction.objects.filter(
        item_id=item_id, from_location_id=location_id, lot_no=lot_no
    ).aggregate(total=Sum("qty_base"))["total"] or ZERO
    return incoming - outgoing
