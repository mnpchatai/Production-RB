import uuid
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from apps.common.services import next_document_no
from apps.common.state_machine import CANCELLED, COMPLETED, CONFIRMED, DRAFT, transition
from apps.inventory.models import DELIVERY
from apps.inventory.services import TxnLine, lock_items, post_transactions

from .models import SalesOrder, SalesOrderLine


@transaction.atomic
def create_sales_order(*, customer, order_date, lines, user, note=""):
    """lines: list ของ dict {item, qty_ordered, uom, due_date, unit_price}"""
    if not lines:
        raise ValueError("ใบสั่งขายต้องมีอย่างน้อยหนึ่งบรรทัด")

    order = SalesOrder.objects.create(
        so_no=next_document_no("sales_order", on_date=order_date, user=user),
        customer=customer,
        order_date=order_date,
        status=DRAFT,
        note=note,
        created_by=user,
        updated_by=user,
    )
    SalesOrderLine.objects.bulk_create(
        [
            SalesOrderLine(
                sales_order=order,
                line_no=(index + 1) * 10,
                item=line["item"],
                qty_ordered=Decimal(line["qty_ordered"]),
                uom=line.get("uom") or line["item"].uom,
                unit_price=Decimal(line.get("unit_price", 0)),
                due_date=line["due_date"],
                created_by=user,
                updated_by=user,
            )
            for index, line in enumerate(lines)
        ]
    )
    return order


def confirm_sales_order(order, user, note=""):
    return transition(order, CONFIRMED, user, note=note)


def cancel_sales_order(order, user, reason):
    return transition(order, CANCELLED, user, reason=reason)


@transaction.atomic
def deliver_sales_order_line(
    *, so_line, qty, from_location, lot_no="", user=None, posted_at=None, client_ref=None
):
    """ส่งของตามใบสั่งขาย — ลดสต็อกด้วยธุรกรรม delivery"""
    posted_at = posted_at or timezone.now()
    qty = Decimal(qty)
    if qty <= 0:
        raise ValueError("จำนวนส่งต้องมากกว่าศูนย์")

    lock_items([so_line.item_id])
    remaining = Decimal(so_line.qty_ordered) - so_line.qty_delivered
    if qty > remaining:
        raise ValueError(
            f"ส่งเกินยอดสั่ง: เหลือส่งได้ {remaining} แต่จะส่ง {qty}"
        )

    client_ref = client_ref or uuid.uuid4()
    return post_transactions(
        client_ref=client_ref,
        lines=[
            TxnLine(
                item=so_line.item,
                qty=qty,
                uom=so_line.uom_id,
                txn_type=DELIVERY,
                from_location=from_location,
                lot_no=lot_no,
                unit_cost=so_line.item.standard_cost,
                doc_type="sales_order",
                doc_no=so_line.sales_order.so_no,
                doc_line_id=so_line.pk,
            )
        ],
        posted_at=posted_at,
        posted_by=user,
        on_date=posted_at.date(),
    )


def complete_sales_order(order, user, note=""):
    return transition(order, COMPLETED, user, note=note)
