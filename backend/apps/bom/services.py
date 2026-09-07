"""สูตรการผลิต — คลี่ BOM หลายระดับ

สูตรที่ใช้คิดความต้องการ (ตัดสินใจไว้ใน docs/phases/phase-1-bom-routing.md):

    qty_required = qty_parent * qty_per / (1 - scrap_pct/100)

คือ "ต้องเบิกเผื่อเสีย" ไม่ใช่ qty_parent * (1 + scrap_pct) ซึ่งให้ผลต่างกัน
และต่างมากขึ้นเมื่อสะสมหลายระดับ ถ้าจะเปลี่ยนต้องเปลี่ยนพร้อม ADR
"""

from dataclasses import dataclass, field
from decimal import Decimal

from apps.masterdata.services import conversion_graph, convert, effective_on

from .models import ACTIVE, BomHeader, BomLine, RoutingHeader

MAX_BOM_DEPTH = 20
HUNDRED = Decimal(100)


class CircularBomError(Exception):
    """BOM วนกลับมาหาตัวเอง — ข้อความต้องบอก path เต็มถึงจุดที่วน"""


class BomTooDeepError(Exception):
    pass


class AmbiguousBomError(Exception):
    """มี BOM ที่ใช้งานอยู่หลายฉบับในวันเดียวกัน — ข้อมูลหลักผิด"""


class NoEffectiveBomError(Exception):
    """item มี BOM อยู่ แต่ไม่มีฉบับใดมีผลในวันที่ที่ขอ — ออกใบสั่งผลิตไม่ได้"""


@dataclass
class BomRequirement:
    level: int
    item_id: int
    item_code: str
    qty_required: Decimal
    uom_id: int
    uom_code: str
    path: list[int] = field(default_factory=list)
    parent_item_id: int | None = None
    qty_per: Decimal = Decimal(0)
    scrap_pct: Decimal = Decimal(0)
    source_bom_header_id: int | None = None
    source_bom_line_id: int | None = None
    bom_revision: str = ""
    alternate_item_codes: list[str] = field(default_factory=list)
    has_bom: bool = False


def resolve_bom(item, as_of_date):
    """หา BOM ที่ใช้งานอยู่ของ item ณ วันที่ที่ระบุ

    ไม่มี default ให้ as_of_date โดยเจตนา (INVARIANT ข้อ 9)
    """
    item_id = item if isinstance(item, int) else item.pk
    return _resolve_bom_map([item_id], as_of_date).get(item_id)


def resolve_routing(item, as_of_date):
    item_id = item if isinstance(item, int) else item.pk
    found = list(
        RoutingHeader.objects.filter(item_id=item_id, status=ACTIVE)
        .filter(effective_on(as_of_date))
        .order_by("-effective_from")
    )
    if len(found) > 1:
        raise AmbiguousBomError(
            f"item {item_id} มี routing ที่ใช้งานอยู่ {len(found)} ฉบับ ณ {as_of_date}"
        )
    return found[0] if found else None


def _resolve_bom_map(item_ids, as_of_date):
    """คิวรีเดียวสำหรับหลาย item — ห้ามยิงคิวรีในลูป"""
    headers = (
        BomHeader.objects.filter(item_id__in=list(item_ids), status=ACTIVE)
        .filter(effective_on(as_of_date))
        .order_by("item_id", "-effective_from")
    )
    result: dict[int, BomHeader] = {}
    for header in headers:
        if header.item_id in result:
            raise AmbiguousBomError(
                f"item {header.item_id} มี BOM ที่ใช้งานอยู่มากกว่าหนึ่งฉบับ ณ {as_of_date}"
            )
        result[header.item_id] = header
    return result


def explode_bom(item_id, qty, as_of_date, *, uom=None, graph=None):
    """คลี่ความต้องการวัตถุดิบทุกระดับ

    คืน list ของ BomRequirement เรียงตามระดับชั้น แต่ละแถวมี path จากรากลงมา
    เพื่อให้ debug ได้ว่าความต้องการก้อนนี้มาจากสาขาไหน

    qty ตีความเป็นหน่วยนับหลักของ item เว้นแต่ระบุ uom มาด้วย
    """
    from apps.masterdata.models import Item

    graph = conversion_graph() if graph is None else graph
    root = Item.objects.select_related("uom").get(pk=item_id)
    qty = Decimal(qty)
    if uom is not None:
        qty = convert(qty, uom, root.uom_id, graph)

    results: list[BomRequirement] = []
    current = [(root.pk, qty, [root.pk])]
    level = 0

    while current:
        level += 1
        if level > MAX_BOM_DEPTH:
            raise BomTooDeepError(
                f"BOM ลึกเกิน {MAX_BOM_DEPTH} ระดับที่ item {root.code} — ถือว่าข้อมูลหลักผิด"
            )

        parent_ids = {parent_id for parent_id, _, _ in current}
        bom_map = _resolve_bom_map(parent_ids, as_of_date)
        if not bom_map:
            break

        lines = list(
            BomLine.objects.filter(bom_id__in=[b.pk for b in bom_map.values()])
            .select_related("component_item", "component_item__uom", "uom")
            .order_by("bom_id", "sequence", "id")
        )
        lines_by_bom: dict[int, list[BomLine]] = {}
        alternates_by_line: dict[int, list[str]] = {}
        for line in lines:
            if line.alternate_of_line_id:
                alternates_by_line.setdefault(line.alternate_of_line_id, []).append(
                    line.component_item.code
                )
            else:
                lines_by_bom.setdefault(line.bom_id, []).append(line)

        next_level = []
        for parent_id, parent_qty, path in current:
            header = bom_map.get(parent_id)
            if header is None:
                continue
            for line in lines_by_bom.get(header.pk, ()):
                component = line.component_item
                if component.pk in path:
                    trail = " -> ".join(str(i) for i in [*path, component.pk])
                    raise CircularBomError(
                        f"BOM วนกลับมาที่ item {component.code} (id {component.pk}) "
                        f"— เส้นทาง: {trail}"
                    )

                divisor = (HUNDRED - Decimal(line.scrap_pct)) / HUNDRED
                required = parent_qty * Decimal(line.qty_per) / divisor
                required_base = convert(required, line.uom_id, component.uom_id, graph)

                results.append(
                    BomRequirement(
                        level=level,
                        item_id=component.pk,
                        item_code=component.code,
                        qty_required=required_base,
                        uom_id=component.uom_id,
                        uom_code=component.uom.code,
                        path=[*path, component.pk],
                        parent_item_id=parent_id,
                        qty_per=Decimal(line.qty_per),
                        scrap_pct=Decimal(line.scrap_pct),
                        source_bom_header_id=header.pk,
                        source_bom_line_id=line.pk,
                        bom_revision=header.revision,
                        alternate_item_codes=alternates_by_line.get(line.pk, []),
                    )
                )
                next_level.append((component.pk, required_base, [*path, component.pk]))

        current = next_level

    exploded_parents = {row.parent_item_id for row in results}
    for row in results:
        row.has_bom = row.item_id in exploded_parents
    return results


def aggregate_requirements(rows, *, leaves_only=True):
    """รวมความต้องการของ item เดียวกันที่มาจากหลายสาขา"""
    totals: dict[int, BomRequirement] = {}
    for row in rows:
        if leaves_only and row.has_bom:
            continue
        existing = totals.get(row.item_id)
        if existing is None:
            totals[row.item_id] = BomRequirement(
                level=row.level,
                item_id=row.item_id,
                item_code=row.item_code,
                qty_required=row.qty_required,
                uom_id=row.uom_id,
                uom_code=row.uom_code,
            )
        else:
            existing.qty_required += row.qty_required
            existing.level = max(existing.level, row.level)
    return sorted(totals.values(), key=lambda r: r.item_code)
