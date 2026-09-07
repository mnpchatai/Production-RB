from decimal import Decimal

from django.db.models import Q

from apps.common.uom import UomConversionError, build_graph, find_factor  # noqa: F401

from .models import UomConversion, WorkCenterRate


def conversion_graph():
    """สร้างกราฟแปลงหน่วยครั้งเดียวแล้วส่งต่อ — กันการยิงคิวรีในลูป"""
    edges = UomConversion.objects.values_list("from_uom_id", "to_uom_id", "factor")
    return build_graph(edges)


def convert(qty, from_uom, to_uom, graph=None):
    """แปลงจำนวนข้ามหน่วย — แปลงไม่ได้ต้อง raise ไม่ใช่คืนค่าเดิม"""
    from_id = from_uom if isinstance(from_uom, int) else from_uom.pk
    to_id = to_uom if isinstance(to_uom, int) else to_uom.pk
    if from_id == to_id:
        return Decimal(qty)
    graph = conversion_graph() if graph is None else graph
    return Decimal(qty) * find_factor(graph, from_id, to_id)


def effective_on(on_date, prefix=""):
    """ตัวกรองช่วงเวลามีผล — effective_from <= on_date < effective_to

    effective_to เป็น exclusive และ null แปลว่ายังไม่หมดอายุ
    ใช้ร่วมกันทั้ง BOM, Routing และอัตราของ work center
    """
    return Q(**{f"{prefix}effective_from__lte": on_date}) & (
        Q(**{f"{prefix}effective_to__isnull": True})
        | Q(**{f"{prefix}effective_to__gt": on_date})
    )


def rate_for(work_center, on_date):
    """อัตราค่าแรง/overhead ของ work center ณ วันที่ที่กำหนด

    ไม่มี default ให้ on_date โดยเจตนา — ต้นทุนต้องอ้างอัตราตามวันที่ของธุรกรรม
    ไม่ใช่อัตราปัจจุบัน
    """
    return (
        WorkCenterRate.objects.filter(work_center=work_center)
        .filter(effective_on(on_date))
        .order_by("-effective_from")
        .first()
    )
