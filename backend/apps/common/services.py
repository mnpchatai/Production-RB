from django.db import IntegrityError, transaction
from django.utils import timezone

from .models import DocumentSequence, DocumentSequenceCounter


def _period_for(sequence, on_date):
    if sequence.reset_rule == DocumentSequence.RESET_YEARLY:
        return f"{on_date.year:04d}"
    if sequence.reset_rule == DocumentSequence.RESET_MONTHLY:
        return f"{on_date.year:04d}{on_date.month:02d}"
    return ""


@transaction.atomic
def next_document_numbers(doc_type, count=1, on_date=None, user=None):
    """จองเลขที่เอกสารทีละหลายเลข — ทนการยิงพร้อมกันด้วยการล็อกแถวตัวนับ

    ห้ามใช้ MAX(no)+1 เพราะสองธุรกรรมที่อ่านพร้อมกันจะได้เลขเดียวกัน
    จองทีละบล็อกเพื่อไม่ให้ธุรกรรมหลายบรรทัดต้องล็อกตัวนับซ้ำ ๆ
    """
    if count < 1:
        raise ValueError("count ต้องมากกว่าศูนย์")
    on_date = on_date or timezone.localdate()
    sequence = DocumentSequence.objects.get(doc_type=doc_type)
    period = _period_for(sequence, on_date)

    counter = (
        DocumentSequenceCounter.objects.select_for_update()
        .filter(sequence=sequence, period=period)
        .first()
    )
    if counter is None:
        try:
            with transaction.atomic():
                DocumentSequenceCounter.objects.create(
                    sequence=sequence, period=period, created_by=user, updated_by=user
                )
        except IntegrityError:
            pass  # อีก transaction สร้างไปก่อนแล้ว — ไปหยิบแถวนั้นมาล็อก
        counter = DocumentSequenceCounter.objects.select_for_update().get(
            sequence=sequence, period=period
        )

    start = counter.next_number
    counter.next_number = start + count
    counter.updated_by = user
    counter.save(update_fields=["next_number", "updated_by", "updated_at"])

    numbers = []
    for offset in range(count):
        body = str(start + offset).zfill(sequence.padding)
        numbers.append(
            f"{sequence.prefix}{period}-{body}" if period else f"{sequence.prefix}{body}"
        )
    return numbers


def next_document_no(doc_type, on_date=None, user=None):
    return next_document_numbers(doc_type, 1, on_date=on_date, user=user)[0]
