from decimal import Decimal

import pytest

from apps.common.uom import UomConversionError, build_graph, find_factor


def test_converts_across_multiple_hops():
    """แปลงข้ามขั้น TON -> KG -> G ได้ค่าถูกต้อง"""
    graph = build_graph([(1, 2, Decimal("1000")), (3, 1, Decimal("1000"))])
    assert find_factor(graph, 3, 2) == Decimal("1000000")


def test_converts_in_reverse_direction():
    """ทิศย้อนกลับใช้ 1/factor ให้เอง ไม่ต้องประกาศสองแถว"""
    graph = build_graph([(1, 2, Decimal("1000"))])
    assert find_factor(graph, 2, 1) == Decimal(1) / Decimal("1000")


def test_same_uom_is_identity():
    assert find_factor(build_graph([]), 5, 5) == Decimal(1)


def test_missing_path_raises_instead_of_returning_input():
    """แปลงไม่ได้ต้อง raise — คืนค่าเดิมเงียบ ๆ คือบั๊กที่หาไม่เจอ"""
    graph = build_graph([(1, 2, Decimal("1000"))])
    with pytest.raises(UomConversionError) as exc:
        find_factor(graph, 1, 99)
    assert "ไม่มีเส้นทาง" in str(exc.value)


def test_non_positive_factor_rejected():
    with pytest.raises(UomConversionError):
        build_graph([(1, 2, Decimal("-5"))])
