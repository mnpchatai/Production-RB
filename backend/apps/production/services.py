"""ใบสั่งผลิตและการบันทึกผลหน้างาน

การเดินของวัตถุดิบในระบบนี้:
  1. backflush ตอนบันทึกผลขั้นตอนแรก  issue_to_wo : คลัง -> WIP
  2. ผลผลิตตอนบันทึกผลขั้นตอนสุดท้าย   wo_output   : WIP  -> คลังสินค้า
  3. ปิดงาน                            consume_from_wip : WIP -> ออกจากระบบ
     (ตัดวัตถุดิบที่ค้างใน WIP ของใบนี้ให้เป็นศูนย์ ณ วันปิดงาน)
  4. ยกเลิกหลังเบิก                     return_from_wo : WIP -> คลัง (ต้องคืนให้หมดก่อน)
"""

import uuid
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from apps.bom.services import (
    NoEffectiveBomError,
    aggregate_requirements,
    explode_bom,
    resolve_bom,
    resolve_routing,
)
from apps.common.services import next_document_no
from apps.common.state_machine import (
    CANCELLED,
    COMPLETED,
    IN_PROGRESS,
    RELEASED,
    transition,
)
from apps.inventory.models import (
    CONSUME_FROM_WIP,
    ISSUE_TO_WO,
    RETURN_FROM_WO,
    WO_OUTPUT,
    StockTransaction,
)
from apps.inventory.services import (
    NegativeStockError,
    TxnLine,
    balance_of,
    lock_items,
    post_transactions,
)
from apps.masterdata.services import convert, rate_for

from .models import (
    OP_COMPLETED,
    OP_IN_PROGRESS,
    BackflushException,
    ShopFloorReport,
    WorkOrder,
    WorkOrderMaterial,
    WorkOrderOperation,
)

ZERO = Decimal("0")
HUNDRED = Decimal(100)


class ShopFloorError(Exception):
    pass


class OverProductionError(ShopFloorError):
    pass


def shift_for(moment):
    """กะทำงาน — ระบบเติมเอง ห้ามรับจาก client"""
    local_hour = timezone.localtime(moment).hour
    return "A" if 8 <= local_hour < 20 else "B"


@transaction.atomic
def create_work_order(
    *,
    item,
    qty_planned,
    uom,
    due_date,
    user,
    as_of_date,
    wip_location,
    output_location,
    scrap_location,
    source_sales_order_line=None,
    multi_level=False,
):
    """สร้างใบสั่งผลิตพร้อม snapshot BOM และ Routing ทันที (INVARIANT ข้อ 2)

    as_of_date ไม่มี default — BOM ที่ใช้ต้องผูกกับวันที่เสมอ (INVARIANT ข้อ 9)
    """
    qty_planned = Decimal(qty_planned)
    if qty_planned <= 0:
        raise ValueError("qty_planned ต้องมากกว่าศูนย์")

    qty_base = convert(qty_planned, uom, item.uom_id)
    work_order = WorkOrder.objects.create(
        wo_no=next_document_no("work_order", on_date=as_of_date, user=user),
        item=item,
        qty_planned=qty_planned,
        uom=uom,
        due_date=due_date,
        status="draft",
        source_sales_order_line=source_sales_order_line,
        wip_location=wip_location,
        output_location=output_location,
        scrap_location=scrap_location,
        snapshot_date=as_of_date,
        created_by=user,
        updated_by=user,
    )

    from apps.bom.models import BomHeader

    if resolve_bom(item, as_of_date) is None and BomHeader.objects.filter(item=item).exists():
        raise NoEffectiveBomError(
            f"{item.code} มี BOM อยู่ แต่ไม่มีฉบับใดมีผลในวันที่ {as_of_date} "
            "— ออกใบสั่งผลิตแล้วจะได้ใบที่ไม่มีวัตถุดิบ"
        )

    rows = explode_bom(item.pk, qty_base, as_of_date)
    if multi_level:
        selected = aggregate_requirements(rows, leaves_only=True)
    else:
        selected = [row for row in rows if row.level == 1]

    bom_revision = ""
    materials = []
    for line_no, row in enumerate(selected, start=1):
        bom_revision = bom_revision or row.bom_revision
        from apps.masterdata.models import Item

        component = Item.objects.get(pk=row.item_id)
        materials.append(
            WorkOrderMaterial(
                work_order=work_order,
                line_no=line_no * 10,
                component_item=component,
                qty_per=row.qty_per or (row.qty_required / qty_base),
                scrap_pct=row.scrap_pct,
                qty_required=row.qty_required,
                uom_id=row.uom_id,
                standard_unit_cost=component.standard_cost,
                bom_level=row.level,
                source_bom_header_id=row.source_bom_header_id,
                source_bom_line_id=row.source_bom_line_id,
                bom_revision=row.bom_revision,
                created_by=user,
                updated_by=user,
            )
        )
    WorkOrderMaterial.objects.bulk_create(materials)

    routing = resolve_routing(item, as_of_date)
    operations = []
    if routing is not None:
        for operation in routing.operations.select_related("work_center").all():
            rate = rate_for(operation.work_center, as_of_date)
            operations.append(
                WorkOrderOperation(
                    work_order=work_order,
                    sequence=operation.sequence,
                    work_center=operation.work_center,
                    name=operation.name,
                    setup_minutes=operation.setup_minutes,
                    run_minutes_per_unit=operation.run_minutes_per_unit,
                    labor_rate_per_hour=rate.labor_rate_per_hour if rate else ZERO,
                    overhead_rate_per_hour=rate.overhead_rate_per_hour if rate else ZERO,
                    source_routing_header_id=routing.pk,
                    source_routing_operation_id=operation.pk,
                    routing_revision=routing.revision,
                    created_by=user,
                    updated_by=user,
                )
            )
        WorkOrderOperation.objects.bulk_create(operations)

    work_order.bom_revision = bom_revision
    work_order.routing_revision = routing.revision if routing else ""
    work_order.save(update_fields=["bom_revision", "routing_revision", "updated_at"])
    return work_order


@transaction.atomic
def issue_materials(work_order, user, *, materials=None, ratio=None, posted_at=None, client_ref=None):
    """เบิกวัตถุดิบเข้าใบสั่งผลิตด้วยมือ (ฝ่ายคลังจ่ายของก่อนเริ่มงาน)

    ratio = สัดส่วนของ qty_required ที่จะเบิก (ค่าเริ่มต้น 1 = เบิกเต็มตามแผน)
    """
    posted_at = posted_at or timezone.now()
    ratio = Decimal(1) if ratio is None else Decimal(ratio)
    rows = list(materials or work_order.materials.select_related("component_item", "uom"))
    if not rows:
        return []

    lock_items(m.component_item_id for m in rows)
    lines = []
    for material in rows:
        qty = (Decimal(material.qty_required) * ratio).quantize(Decimal("0.0001"))
        if qty <= 0:
            continue
        source = _material_source_location(material, work_order.wip_location)
        if source is None:
            raise NegativeStockError(
                f"ไม่มี {material.component_item.code} ในคลังให้เบิก"
            )
        lines.append(
            TxnLine(
                item=material.component_item,
                qty=qty,
                uom=material.uom_id,
                txn_type=ISSUE_TO_WO,
                from_location=source.location,
                to_location=work_order.wip_location,
                lot_no=source.lot_no,
                unit_cost=material.standard_unit_cost,
                doc_type="work_order",
                doc_no=work_order.wo_no,
                doc_line_id=material.pk,
            )
        )
    return post_transactions(
        client_ref=client_ref or uuid.uuid4(),
        lines=lines,
        posted_at=posted_at,
        posted_by=user,
        on_date=posted_at.date(),
    )


def _material_source_location(material, wip_location):
    """หา location ที่มีของพอสำหรับเบิก — เลือกคลังเก็บที่ยอดมากที่สุด

    ต้องเป็น location ประเภท stock เท่านั้น การกันแค่ WIP ไม่พอ เพราะจะทำให้
    ของที่อยู่ในจุดพักของเสีย (scrap) หรือระหว่างขนย้าย (in_transit)
    ถูกเบิกกลับเข้าไลน์เงียบ ๆ ซึ่งทั้งผิดทางกายภาพและทำให้ยอดของเสียหายไปจากรายงาน
    """
    from apps.inventory.models import StockBalance
    from apps.masterdata.models import Location

    row = (
        StockBalance.objects.filter(
            item_id=material.component_item_id,
            qty_on_hand__gt=0,
            location__location_type=Location.STOCK,
        )
        .exclude(location_id=wip_location.pk)
        .select_related("location")
        .order_by("-qty_on_hand")
        .first()
    )
    return row


@transaction.atomic
def report_shop_floor(
    *,
    client_ref,
    wo_no,
    operation_seq,
    qty_good,
    qty_scrap=0,
    scrap_reason=None,
    started_at=None,
    finished_at=None,
    user=None,
    posted_at=None,
):
    """บันทึกผลหน้างานหนึ่งครั้ง — idempotent ตาม client_ref (INVARIANT ข้อ 8)

    วัตถุดิบไม่พอไม่บล็อกการบันทึก แต่ลง BackflushException ไว้ให้ฝ่ายวางแผนตามแก้
    ยอดสต็อกจึงไม่ติดลบ และหน้างานก็ไม่ถูกบล็อก พร้อมกัน
    """
    client_ref = uuid.UUID(str(client_ref))
    # ทางลัด: ถ้าเคยบันทึกแล้วและ commit ไปแล้ว ไม่ต้องล็อกอะไรเลย
    existing = ShopFloorReport.objects.filter(client_ref=client_ref).first()
    if existing is not None:
        return existing

    qty_good = Decimal(qty_good)
    qty_scrap = Decimal(qty_scrap or 0)
    if qty_good < 0 or qty_scrap < 0:
        raise ShopFloorError("จำนวนติดลบไม่ได้")
    if qty_good == 0 and qty_scrap == 0:
        raise ShopFloorError("ต้องมีจำนวนอย่างน้อยหนึ่งช่อง")

    posted_at = posted_at or timezone.now()
    if started_at and started_at > posted_at:
        raise ShopFloorError("เวลาเริ่มอยู่ในอนาคต")
    if finished_at and started_at and finished_at < started_at:
        raise ShopFloorError("เวลาเสร็จก่อนเวลาเริ่ม")

    work_order = WorkOrder.objects.select_for_update().get(wo_no=wo_no)

    # ตรวจซ้ำหลังได้ล็อกแถวใบสั่งผลิต — สองเครื่องที่ sync พร้อมกันด้วย client_ref
    # เดียวกันจะผ่านการตรวจครั้งแรกทั้งคู่ เพราะยังไม่มีใครเขียนลงฐานข้อมูล
    # ทุกคำขอของใบเดียวกันเรียงคิวที่ล็อกนี้ คนหลังจึงเห็นแถวที่คนแรก commit แล้ว
    existing = ShopFloorReport.objects.filter(client_ref=client_ref).first()
    if existing is not None:
        return existing

    if work_order.status not in (RELEASED, IN_PROGRESS):
        raise ShopFloorError(
            f"ใบสั่งผลิต {wo_no} อยู่ในสถานะ {work_order.status} — บันทึกผลไม่ได้"
        )
    if started_at and started_at.date() < work_order.snapshot_date:
        raise ShopFloorError("เวลาเริ่มเก่ากว่าวันที่ออกใบสั่งผลิต")

    operation = WorkOrderOperation.objects.select_for_update().get(
        work_order=work_order, sequence=operation_seq
    )

    is_last = not WorkOrderOperation.objects.filter(
        work_order=work_order, sequence__gt=operation.sequence
    ).exists()
    if is_last:
        tolerance = work_order.item.over_production_tolerance_pct
        ceiling = work_order.qty_planned * (HUNDRED + tolerance) / HUNDRED
        if work_order.qty_completed + qty_good > ceiling:
            raise OverProductionError(
                f"ผลิตเกินแผนเกินเกณฑ์: แผน {work_order.qty_planned} "
                f"รับได้ถึง {ceiling} แต่จะกลายเป็น {work_order.qty_completed + qty_good}"
            )

    report = ShopFloorReport.objects.create(
        client_ref=client_ref,
        work_order=work_order,
        operation=operation,
        qty_good=qty_good,
        qty_scrap=qty_scrap,
        scrap_reason=scrap_reason,
        started_at=started_at,
        finished_at=finished_at,
        posted_at=posted_at,
        posted_by=user,
        work_center=operation.work_center,
        shift=shift_for(posted_at),
        created_by=user,
        updated_by=user,
    )

    operation.qty_good += qty_good
    operation.qty_scrap += qty_scrap
    if started_at and finished_at:
        operation.actual_minutes += Decimal(
            (finished_at - started_at).total_seconds()
        ) / Decimal(60)
    operation.status = (
        OP_COMPLETED
        if operation.qty_good >= work_order.qty_planned
        else OP_IN_PROGRESS
    )
    operation.updated_by = user
    operation.save(
        update_fields=[
            "qty_good",
            "qty_scrap",
            "actual_minutes",
            "status",
            "updated_by",
            "updated_at",
        ]
    )

    is_first = not WorkOrderOperation.objects.filter(
        work_order=work_order, sequence__lt=operation.sequence
    ).exists()
    if is_first:
        _backflush(report, work_order, qty_good + qty_scrap, user, posted_at)

    if is_last and qty_good > 0:
        _post_output(report, work_order, qty_good, user, posted_at)
        work_order.qty_completed += qty_good
        work_order.qty_scrapped += qty_scrap
        work_order.updated_by = user
        work_order.save(
            update_fields=["qty_completed", "qty_scrapped", "updated_by", "updated_at"]
        )
    elif qty_scrap > 0:
        work_order.qty_scrapped += qty_scrap
        work_order.updated_by = user
        work_order.save(update_fields=["qty_scrapped", "updated_by", "updated_at"])

    if work_order.status == RELEASED:
        transition(work_order, IN_PROGRESS, user, note=f"บันทึกผลครั้งแรก {report.client_ref}")

    return report


def _backflush(report, work_order, qty_started, user, posted_at):
    """ตัดวัตถุดิบตามสัดส่วนที่ผลิต — ของไม่พอไม่บล็อก แต่เข้าคิว exception"""
    if qty_started <= 0:
        return
    ratio = qty_started / work_order.qty_planned
    materials = list(work_order.materials.select_related("component_item", "uom"))
    if not materials:
        return

    lock_items(m.component_item_id for m in materials)

    lines = []
    shortages = []
    for material in materials:
        qty = (Decimal(material.qty_required) * ratio).quantize(Decimal("0.0001"))
        if qty <= 0:
            continue
        source = _material_source_location(material, work_order.wip_location)
        available = ZERO if source is None else Decimal(source.qty_on_hand)
        qty_base = convert(qty, material.uom_id, material.component_item.uom_id)
        if source is None or available < qty_base:
            shortages.append((material, qty, available))
            continue
        lines.append(
            TxnLine(
                item=material.component_item,
                qty=qty,
                uom=material.uom_id,
                txn_type=ISSUE_TO_WO,
                from_location=source.location,
                to_location=work_order.wip_location,
                lot_no=source.lot_no,
                unit_cost=material.standard_unit_cost,
                doc_type="work_order",
                doc_no=work_order.wo_no,
                doc_line_id=material.pk,
                is_auto_backflush=True,
            )
        )

    if lines:
        post_transactions(
            client_ref=report.client_ref,
            lines=lines,
            posted_at=posted_at,
            posted_by=user,
            on_date=posted_at.date(),
        )

    if shortages:
        BackflushException.objects.bulk_create(
            [
                BackflushException(
                    report=report,
                    work_order=work_order,
                    material=material,
                    qty_short=qty - available,
                    uom_id=material.uom_id,
                    detail=(
                        f"ต้องการ {qty} {material.uom.code} "
                        f"แต่มีในคลัง {available} — ยังไม่ได้ตัดสต็อก"
                    ),
                    created_by=user,
                    updated_by=user,
                )
                for material, qty, available in shortages
            ]
        )
        report.has_exception = True
        report.save(update_fields=["has_exception", "updated_at"])


def _post_output(report, work_order, qty_good, user, posted_at):
    lot_no = work_order.wo_no if work_order.item.is_lot_controlled else ""
    post_transactions(
        client_ref=uuid.uuid5(report.client_ref, "wo_output"),
        lines=[
            TxnLine(
                item=work_order.item,
                qty=qty_good,
                uom=work_order.uom_id,
                txn_type=WO_OUTPUT,
                to_location=work_order.output_location,
                lot_no=lot_no,
                unit_cost=ZERO,
                doc_type="work_order",
                doc_no=work_order.wo_no,
                doc_line_id=work_order.pk,
                is_auto_backflush=True,
            )
        ],
        posted_at=posted_at,
        posted_by=user,
        on_date=posted_at.date(),
    )


def wip_outstanding(work_order):
    """วัตถุดิบที่ยังค้างอยู่ใน WIP ของใบสั่งผลิตนี้ (เบิก - คืน - ตัดปิดงาน)"""
    from django.db.models import Sum

    rows = (
        StockTransaction.objects.filter(
            doc_type="work_order",
            doc_no=work_order.wo_no,
            txn_type__in=[ISSUE_TO_WO, RETURN_FROM_WO, CONSUME_FROM_WIP],
        )
        .values("item_id", "item__code", "lot_no", "txn_type")
        .annotate(total=Sum("qty_base"))
    )
    net: dict[tuple[int, str], Decimal] = {}
    codes: dict[int, str] = {}
    for row in rows:
        sign = 1 if row["txn_type"] == ISSUE_TO_WO else -1
        key = (row["item_id"], row["lot_no"])
        net[key] = net.get(key, ZERO) + sign * row["total"]
        codes[row["item_id"]] = row["item__code"]
    return {key: qty for key, qty in net.items() if qty > 0}, codes


@transaction.atomic
def return_materials_to_stock(work_order, user, *, to_location=None, posted_at=None, reason=""):
    """คืนวัตถุดิบที่ค้างใน WIP กลับคลัง — ใช้ก่อนยกเลิกใบสั่งผลิต"""
    from apps.masterdata.models import Item

    posted_at = posted_at or timezone.now()
    outstanding, _codes = wip_outstanding(work_order)
    if not outstanding:
        return []

    items = {i.pk: i for i in Item.objects.filter(pk__in={k[0] for k in outstanding})}
    lock_items(items)
    target = to_location or _default_return_location(work_order)

    lines = [
        TxnLine(
            item=items[item_id],
            qty=qty,
            uom=items[item_id].uom_id,
            txn_type=RETURN_FROM_WO,
            from_location=work_order.wip_location,
            to_location=target,
            lot_no=lot_no,
            doc_type="work_order",
            doc_no=work_order.wo_no,
            doc_line_id=work_order.pk,
        )
        for (item_id, lot_no), qty in sorted(outstanding.items())
    ]
    return post_transactions(
        client_ref=uuid.uuid5(uuid.NAMESPACE_URL, f"wo-return/{work_order.wo_no}/{posted_at}"),
        lines=lines,
        posted_at=posted_at,
        posted_by=user,
        on_date=posted_at.date(),
    )


def _default_return_location(work_order):
    """คืนของกลับคลังที่เบิกออกมา ถ้าหาไม่เจอใช้คลังผลผลิต"""
    last_issue = (
        StockTransaction.objects.filter(
            doc_type="work_order", doc_no=work_order.wo_no, txn_type=ISSUE_TO_WO
        )
        .order_by("-posted_at", "-id")
        .select_related("from_location")
        .first()
    )
    return last_issue.from_location if last_issue else work_order.output_location


@transaction.atomic
def cancel_work_order(work_order, user, reason, *, posted_at=None):
    """ยกเลิกใบสั่งผลิต — คืนวัตถุดิบก่อนเสมอ แล้วค่อยเปลี่ยนสถานะ

    การคืนของกับการเปลี่ยนสถานะอยู่ใน transaction เดียว ถ้าอย่างใดพังต้อง rollback ทั้งคู่
    """
    if not reason:
        raise ShopFloorError("การยกเลิกต้องระบุเหตุผล")
    work_order = WorkOrder.objects.select_for_update().get(pk=work_order.pk)
    if work_order.status == RELEASED:
        return_materials_to_stock(work_order, user, posted_at=posted_at, reason=reason)
    transition(work_order, CANCELLED, user, reason=reason)
    return work_order


@transaction.atomic
def close_work_order(work_order, user, *, posted_at=None, note=""):
    """ปิดงาน — ตัดวัตถุดิบที่ค้างใน WIP ของใบนี้ให้เป็นศูนย์

    นี่คือจุดที่ WIP กลายเป็นสินค้าสำเร็จรูปกับส่วนที่สูญเสียในทางบัญชี
    """
    from apps.masterdata.models import Item

    posted_at = posted_at or timezone.now()
    work_order = WorkOrder.objects.select_for_update().get(pk=work_order.pk)
    outstanding, _codes = wip_outstanding(work_order)
    if outstanding:
        items = {i.pk: i for i in Item.objects.filter(pk__in={k[0] for k in outstanding})}
        lock_items(items)
        post_transactions(
            client_ref=uuid.uuid5(uuid.NAMESPACE_URL, f"wo-close/{work_order.wo_no}"),
            lines=[
                TxnLine(
                    item=items[item_id],
                    qty=qty,
                    uom=items[item_id].uom_id,
                    txn_type=CONSUME_FROM_WIP,
                    from_location=work_order.wip_location,
                    lot_no=lot_no,
                    unit_cost=items[item_id].standard_cost,
                    doc_type="work_order",
                    doc_no=work_order.wo_no,
                    doc_line_id=work_order.pk,
                )
                for (item_id, lot_no), qty in sorted(outstanding.items())
            ],
            posted_at=posted_at,
            posted_by=user,
            on_date=posted_at.date(),
        )
    transition(work_order, "closed", user, note=note or "ปิดงาน")
    return work_order


@transaction.atomic
def short_close_work_order(work_order, user, reason, *, posted_at=None):
    """ผลิตไม่ครบแล้วปิดงาน — ยอดที่ยังขาดต้องหายไปจากแผน ไม่ค้างเป็นงานรอ"""
    if not reason:
        raise ShopFloorError("การปิดงานก่อนครบต้องระบุเหตุผล")
    work_order = WorkOrder.objects.select_for_update().get(pk=work_order.pk)
    work_order.operations.exclude(status=OP_COMPLETED).update(
        status=OP_COMPLETED, updated_at=timezone.now()
    )
    if work_order.status == IN_PROGRESS:
        transition(work_order, COMPLETED, user, note=reason)
    return close_work_order(work_order, user, posted_at=posted_at, note=reason)


@transaction.atomic
def resolve_backflush_exception(exception, user, *, posted_at=None):
    """ตัดสต็อกย้อนหลังหลังจากฝ่ายวางแผนเติมของแล้ว — ใช้ client_ref ที่ผูกกับ exception

    ตัดซ้ำไม่ได้เพราะ client_ref เดิมให้ผลเดิม
    """
    posted_at = posted_at or timezone.now()
    exception = BackflushException.objects.select_for_update().get(pk=exception.pk)
    if exception.resolved_at is not None:
        return []

    material = exception.material
    work_order = exception.work_order
    lock_items([material.component_item_id])
    source = _material_source_location(material, work_order.wip_location)
    qty = Decimal(exception.qty_short)
    if source is None or Decimal(source.qty_on_hand) < qty:
        raise NegativeStockError(
            f"ยังตัดไม่ได้ — {material.component_item.code} มีไม่พอ (ต้องการ {qty})"
        )

    txns = post_transactions(
        client_ref=uuid.uuid5(uuid.NAMESPACE_URL, f"backflush-fix/{exception.pk}"),
        lines=[
            TxnLine(
                item=material.component_item,
                qty=qty,
                uom=exception.uom_id,
                txn_type=ISSUE_TO_WO,
                from_location=source.location,
                to_location=work_order.wip_location,
                lot_no=source.lot_no,
                unit_cost=material.standard_unit_cost,
                doc_type="work_order",
                doc_no=work_order.wo_no,
                doc_line_id=material.pk,
                is_auto_backflush=True,
            )
        ],
        posted_at=posted_at,
        posted_by=user,
        on_date=posted_at.date(),
    )
    exception.resolved_at = posted_at
    exception.resolved_by = user
    exception.updated_by = user
    exception.save(update_fields=["resolved_at", "resolved_by", "updated_by", "updated_at"])
    return txns


def recalculate_progress(work_order):
    """สร้างยอด qty_completed/qty_scrapped ใหม่จาก ShopFloorReport

    ใช้พิสูจน์ว่าคอลัมน์สรุปสองตัวนี้สร้างใหม่ได้จากศูนย์เสมอ
    (เจตนารมณ์เดียวกับ INVARIANT ข้อ 3)
    """
    from django.db.models import Sum

    last_seq = work_order.operations.order_by("-sequence").values_list("sequence", flat=True).first()
    completed = work_order.reports.filter(operation__sequence=last_seq).aggregate(
        total=Sum("qty_good")
    )["total"] or ZERO
    scrapped = work_order.reports.aggregate(total=Sum("qty_scrap"))["total"] or ZERO
    return completed, scrapped
