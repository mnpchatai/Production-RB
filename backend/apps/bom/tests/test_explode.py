from datetime import date
from decimal import Decimal

import pytest

from apps.bom.models import ACTIVE, BomHeader, BomLine
from apps.bom.services import (
    AmbiguousBomError,
    CircularBomError,
    aggregate_requirements,
    explode_bom,
    resolve_bom,
)

HUNDRED = Decimal(100)


def by_code(rows):
    return {row.item_code: row for row in rows}


@pytest.mark.django_db
def test_explodes_three_levels(seeded_no_stock):
    """คลี่ BOM สามระดับได้ครบทุกชั้น พร้อม path จากรากลงมา"""
    rows = explode_bom(seeded_no_stock["items"]["FG-RB-001"].pk, 100, date(2026, 3, 1))
    codes = by_code(rows)
    assert set(codes) == {"SFG-CMP-01", "PKG-BOX-01", "RM-NR-01", "RM-CB-01", "RM-SUL-01"}
    assert codes["SFG-CMP-01"].level == 1
    assert codes["RM-NR-01"].level == 2
    assert codes["RM-NR-01"].path == [
        seeded_no_stock["items"]["FG-RB-001"].pk,
        seeded_no_stock["items"]["SFG-CMP-01"].pk,
        seeded_no_stock["items"]["RM-NR-01"].pk,
    ]


@pytest.mark.django_db
def test_scrap_compounds_per_level(seeded_no_stock):
    """scrap สะสมตามระดับด้วยสูตร qty / (1 - scrap) ไม่ใช่ qty * (1 + scrap)"""
    rows = by_code(explode_bom(seeded_no_stock["items"]["FG-RB-001"].pk, 100, date(2026, 3, 1)))

    # ระดับ 1: 100 ชิ้น x 0.25 กก. เผื่อเสีย 3%
    expected_sfg = Decimal(100) * Decimal("0.25") / (Decimal(97) / HUNDRED)
    assert rows["SFG-CMP-01"].qty_required == expected_sfg

    # ระดับ 2: คิดต่อจากจำนวนของระดับ 1 ไม่ใช่จากจำนวนสินค้าแม่
    expected_nr = expected_sfg * Decimal("0.7") / (Decimal(98) / HUNDRED)
    assert rows["RM-NR-01"].qty_required == expected_nr

    # สูตรที่ใช้ต้องไม่ใช่ qty * (1 + scrap)
    assert rows["SFG-CMP-01"].qty_required != Decimal(100) * Decimal("0.25") * Decimal("1.03")


@pytest.mark.django_db
def test_expired_bom_is_not_exploded(seeded_no_stock):
    """BOM ที่หมดอายุแล้วต้องไม่ถูกคลี่"""
    header = BomHeader.objects.get(item__code="SFG-CMP-01")
    header.effective_to = date(2026, 1, 1)
    header.save()

    before = by_code(explode_bom(seeded_no_stock["items"]["FG-RB-001"].pk, 10, date(2025, 6, 1)))
    after = by_code(explode_bom(seeded_no_stock["items"]["FG-RB-001"].pk, 10, date(2026, 3, 1)))

    assert "RM-NR-01" in before
    assert "RM-NR-01" not in after, "BOM ที่หมดอายุแล้วยังถูกคลี่อยู่"
    assert "SFG-CMP-01" in after


@pytest.mark.django_db
def test_effective_to_is_exclusive(seeded_no_stock):
    """effective_from <= as_of_date < effective_to"""
    header = BomHeader.objects.get(item__code="SFG-CMP-01")
    header.effective_to = date(2026, 3, 1)
    header.save()
    assert resolve_bom(seeded_no_stock["items"]["SFG-CMP-01"], date(2026, 2, 28)) is not None
    assert resolve_bom(seeded_no_stock["items"]["SFG-CMP-01"], date(2026, 3, 1)) is None


@pytest.mark.django_db
def test_circular_bom_names_the_looping_item(seeded_no_stock):
    """BOM วนซ้ำต้อง raise พร้อมบอก path เต็มถึงจุดที่วน"""
    items = seeded_no_stock["items"]
    loop = BomHeader.objects.create(
        item=items["RM-NR-01"],
        revision="LOOP",
        effective_from=date(2020, 1, 1),
        status=ACTIVE,
    )
    BomLine.objects.create(
        bom=loop,
        sequence=10,
        component_item=items["FG-RB-001"],
        qty_per=Decimal("1"),
        uom=items["FG-RB-001"].uom,
    )

    with pytest.raises(CircularBomError) as exc:
        explode_bom(items["FG-RB-001"].pk, 1, date(2026, 3, 1))
    message = str(exc.value)
    assert "FG-RB-001" in message
    assert "เส้นทาง" in message


@pytest.mark.django_db
def test_converts_uom_between_levels(seeded_no_stock):
    """สูตรกรอกเป็นกรัม แต่หน่วยหลักของ item เป็นกิโลกรัม"""
    items = seeded_no_stock["items"]
    header = BomHeader.objects.get(item__code="SFG-CMP-01")
    line = header.lines.get(component_item__code="RM-SUL-01")
    line.qty_per = Decimal("50")  # 50 กรัม
    line.uom = seeded_no_stock["uoms"]["G"]
    line.save()

    rows = by_code(explode_bom(items["FG-RB-001"].pk, 100, date(2026, 3, 1)))
    sfg_qty = rows["SFG-CMP-01"].qty_required
    # 50 กรัม/กก. -> 0.05 กก./กก.
    assert rows["RM-SUL-01"].qty_required == sfg_qty * Decimal("50") / Decimal("1000")
    assert rows["RM-SUL-01"].uom_code == "KG"


@pytest.mark.django_db
def test_overlapping_active_boms_rejected_by_database(seeded_no_stock):
    """ช่วงเวลามีผลทับกันต้องถูกปฏิเสธที่ฐานข้อมูล ไม่ใช่แค่ที่โค้ด"""
    from django.db import IntegrityError, transaction

    with pytest.raises(IntegrityError), transaction.atomic():
        BomHeader.objects.create(
            item=seeded_no_stock["items"]["SFG-CMP-01"],
            revision="B",
            effective_from=date(2024, 1, 1),
            status=ACTIVE,
        )


@pytest.mark.django_db
def test_aggregate_returns_leaves_only(seeded_no_stock):
    """รวมความต้องการเฉพาะรายการล่างสุดที่ต้องซื้อ/เบิกจริง"""
    rows = explode_bom(seeded_no_stock["items"]["FG-RB-001"].pk, 100, date(2026, 3, 1))
    leaves = {row.item_code for row in aggregate_requirements(rows)}
    assert leaves == {"PKG-BOX-01", "RM-NR-01", "RM-CB-01", "RM-SUL-01"}
    assert "SFG-CMP-01" not in leaves


@pytest.mark.django_db
def test_date_parameter_has_no_default():
    """INVARIANT ข้อ 9 — ฟังก์ชันหา BOM ต้องรับวันที่เสมอ"""
    import inspect

    signature = inspect.signature(explode_bom)
    assert signature.parameters["as_of_date"].default is inspect.Parameter.empty
    assert inspect.signature(resolve_bom).parameters["as_of_date"].default is inspect.Parameter.empty
