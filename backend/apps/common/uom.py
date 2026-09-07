"""อัลกอริทึมแปลงหน่วย — ไม่แตะฐานข้อมูล รับตารางความสัมพันธ์เข้ามาตรง ๆ

แยกจาก apps.masterdata เพื่อให้ทดสอบได้โดยไม่ต้องมี DB และเพื่อไม่ให้
apps.common ต้อง import ย้อนกลับไปหา app ที่ประกาศ model
"""

from collections import deque
from decimal import Decimal


class UomConversionError(Exception):
    """แปลงหน่วยไม่ได้ — ต้องโยนออกไป ห้ามคืนค่าเดิมเงียบ ๆ (INVARIANT ข้อ 4)"""


def build_graph(edges):
    """edges: iterable ของ (from_uom_id, to_uom_id, factor)

    คืน adjacency map ที่มีทั้งสองทิศ ทิศย้อนกลับใช้ 1/factor
    """
    graph: dict[int, list[tuple[int, Decimal]]] = {}
    for from_id, to_id, factor in edges:
        factor = Decimal(factor)
        if factor <= 0:
            raise UomConversionError(
                f"ตัวคูณแปลงหน่วยต้องมากกว่าศูนย์ (uom {from_id} -> {to_id} = {factor})"
            )
        graph.setdefault(from_id, []).append((to_id, factor))
        graph.setdefault(to_id, []).append((from_id, Decimal(1) / factor))
    return graph


def find_factor(graph, from_uom_id, to_uom_id):
    """หาตัวคูณจาก from ไป to ด้วย BFS — เส้นทางสั้นที่สุดคลาดเคลื่อนน้อยที่สุด"""
    if from_uom_id == to_uom_id:
        return Decimal(1)

    seen = {from_uom_id}
    queue = deque([(from_uom_id, Decimal(1))])
    while queue:
        node, acc = queue.popleft()
        for neighbour, factor in graph.get(node, ()):
            if neighbour in seen:
                continue
            value = acc * factor
            if neighbour == to_uom_id:
                return value
            seen.add(neighbour)
            queue.append((neighbour, value))
    raise UomConversionError(
        f"ไม่มีเส้นทางแปลงหน่วยจาก uom {from_uom_id} ไป uom {to_uom_id}"
    )


def convert(qty, from_uom_id, to_uom_id, graph):
    return Decimal(qty) * find_factor(graph, from_uom_id, to_uom_id)
