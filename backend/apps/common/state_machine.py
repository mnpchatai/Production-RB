"""INVARIANT ข้อ 7 — การเปลี่ยนสถานะทุกที่ในระบบต้องผ่านไฟล์นี้ที่เดียว

ถ้าเห็น `obj.status = "..."` ตามด้วย save() ที่อื่น แปลว่ามีคนหลุดกฎ
"""

from django.db import transaction
from django.utils import timezone

DRAFT = "draft"
APPROVED = "approved"
CONFIRMED = "confirmed"
RELEASED = "released"
IN_PROGRESS = "in_progress"
COMPLETED = "completed"
CLOSED = "closed"
CANCELLED = "cancelled"

STATUS_LABELS = {
    DRAFT: "ร่าง",
    APPROVED: "อนุมัติแล้ว",
    CONFIRMED: "ยืนยันแล้ว",
    RELEASED: "ปล่อยงาน",
    IN_PROGRESS: "กำลังผลิต",
    COMPLETED: "ผลิตเสร็จ",
    CLOSED: "ปิดงาน",
    CANCELLED: "ยกเลิก",
}

# doc_type -> สถานะปัจจุบัน -> สถานะที่ไปต่อได้
TRANSITIONS: dict[str, dict[str, set[str]]] = {
    "sales_order": {
        DRAFT: {CONFIRMED, CANCELLED},
        CONFIRMED: {COMPLETED, CANCELLED},
        COMPLETED: {CLOSED},
        CLOSED: set(),
        CANCELLED: set(),
    },
    "work_order": {
        DRAFT: {APPROVED, CANCELLED},
        APPROVED: {RELEASED, CANCELLED},
        RELEASED: {IN_PROGRESS, CANCELLED},
        IN_PROGRESS: {COMPLETED},
        COMPLETED: {CLOSED},
        CLOSED: set(),
        CANCELLED: set(),
    },
}

INITIAL_STATUS = {"sales_order": DRAFT, "work_order": DRAFT}


class InvalidTransition(Exception):
    """เส้นทางสถานะที่ไม่อนุญาต — ต้อง raise เสมอ ห้ามปล่อยผ่านเงียบ ๆ"""


class TransitionBlocked(Exception):
    """เส้นทางถูกต้องแต่เงื่อนไขยังไม่ครบ (เช่น ยังไม่ได้คืนวัตถุดิบ)"""


def _require_materials_returned(doc, **context):
    """ยกเลิกใบสั่งผลิตที่ปล่อยงานแล้ว ต้องคืนวัตถุดิบให้หมดก่อน

    เงื่อนไขอยู่ตรงนี้ ไม่ใช่ใน service เพื่อกันการเรียก transition() ตรง
    แล้วข้ามการคืนของ
    """
    from apps.inventory.services import outstanding_wo_issues

    outstanding = outstanding_wo_issues(doc)
    if outstanding:
        detail = ", ".join(
            f"{item_code} {qty}" for item_code, qty in sorted(outstanding.items())
        )
        raise TransitionBlocked(
            "ยกเลิกใบสั่งผลิตไม่ได้ ยังมีวัตถุดิบที่เบิกไปแล้วและยังไม่ได้คืน: " + detail
        )


def _require_all_operations_done(doc, **context):
    unfinished = doc.operations.exclude(status=COMPLETED).count()
    if unfinished:
        raise TransitionBlocked(
            f"ยังมีขั้นตอนที่ไม่เสร็จอีก {unfinished} ขั้นตอน ปิดเป็น completed ไม่ได้"
        )


# (doc_type, from_status, to_status) -> ฟังก์ชันตรวจก่อนเปลี่ยน
PRECONDITIONS = {
    ("work_order", RELEASED, CANCELLED): _require_materials_returned,
    ("work_order", IN_PROGRESS, COMPLETED): _require_all_operations_done,
}


def allowed_transitions(doc):
    return TRANSITIONS[doc.DOC_TYPE].get(doc.status, set())


def can_transition(doc, to_status):
    return to_status in allowed_transitions(doc)


@transaction.atomic
def transition(doc, to_status, user, note="", reason="", **context):
    """เปลี่ยนสถานะเอกสารหนึ่งใบ พร้อมล็อกแถวและบันทึกประวัติ

    INVARIANT ข้อ 10 — ล็อกแถวเอกสารก่อนอ่านสถานะ มิฉะนั้นสองคนกดพร้อมกัน
    จะผ่านการตรวจทั้งคู่
    """
    model = type(doc)
    doc_type = doc.DOC_TYPE
    if doc_type not in TRANSITIONS:
        raise InvalidTransition(f"ไม่รู้จักเอกสารชนิด {doc_type!r}")

    locked = model.objects.select_for_update().get(pk=doc.pk)
    from_status = locked.status

    graph = TRANSITIONS[doc_type]
    if from_status not in graph:
        raise InvalidTransition(f"{doc_type} {locked} อยู่ในสถานะที่ไม่รู้จัก: {from_status!r}")
    if to_status not in graph[from_status]:
        allowed = ", ".join(sorted(graph[from_status])) or "(ไม่มี)"
        raise InvalidTransition(
            f"{doc_type} {locked} เปลี่ยนจาก {from_status} ไป {to_status} ไม่ได้ "
            f"— ที่ไปได้คือ {allowed}"
        )

    precondition = PRECONDITIONS.get((doc_type, from_status, to_status))
    if precondition is not None:
        precondition(locked, **context)

    now = timezone.now()
    fields = ["status", "updated_by", "updated_at"]
    locked.status = to_status
    locked.updated_by = user
    if to_status == CANCELLED:
        if not reason:
            raise TransitionBlocked("การยกเลิกต้องระบุเหตุผล (cancel_reason)")
        locked.cancelled_at = now
        locked.cancelled_by = user
        locked.cancel_reason = reason
        fields += ["cancelled_at", "cancelled_by", "cancel_reason"]
    locked.save(update_fields=fields)

    history_model = locked.status_history.model
    history_model.objects.create(
        document=locked,
        from_status=from_status,
        to_status=to_status,
        changed_at=now,
        changed_by=user,
        note=note or reason,
        created_by=user,
        updated_by=user,
    )

    # ทำให้ instance ที่ผู้เรียกถืออยู่ตรงกับฐานข้อมูล
    for field in fields:
        setattr(doc, field, getattr(locked, field))
    return locked
