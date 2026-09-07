from django.contrib.auth.models import AbstractUser
from django.db import models

from .fields import AmountField  # noqa: F401  (re-export ให้แอปอื่นเรียกที่เดียว)


class AuditedModel(models.Model):
    """INVARIANT ข้อ 6 — ทุกตารางต้องมี audit fields

    created_at/updated_at คือ "เวลาที่ระบบรับข้อมูล" จึงใช้ auto_* ได้
    เวลาที่เกิดธุรกรรมจริง (posted_at, started_at, finished_at) ห้ามใช้ auto_*
    เพราะหน้างานออฟไลน์ส่งย้อนหลัง — ดู CLAUDE.md
    """

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    created_by = models.ForeignKey(
        "common.User", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        "common.User", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )

    class Meta:
        abstract = True

    def stamp(self, user, creating=False):
        if creating:
            self.created_by = user
        self.updated_by = user
        return self


class Role(AuditedModel):
    """บทบาทผู้ใช้ — ฝ่ายขาย ฝ่ายวางแผน หัวหน้ากะ พนักงานหน้างาน บัญชีต้นทุน"""

    code = models.CharField(max_length=32, unique=True)
    name = models.CharField(max_length=128)

    class Meta:
        db_table = "roles"
        ordering = ["code"]

    def __str__(self):
        return self.name


class User(AbstractUser):
    roles = models.ManyToManyField(Role, related_name="users", blank=True)
    employee_code = models.CharField(max_length=32, blank=True, db_index=True)
    default_work_center = models.ForeignKey(
        "masterdata.WorkCenter",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
    )

    class Meta:
        db_table = "users"

    def has_role(self, code):
        return self.is_superuser or self.roles.filter(code=code).exists()


class DocumentDeletionNotAllowed(Exception):
    """INVARIANT ข้อ 1 — ห้ามลบข้อมูลเอกสารถาวร"""


class DocumentModel(AuditedModel):
    """ฐานของเอกสารทุกใบ

    DOC_TYPE  ใช้เป็นคีย์ของ state machine และของ document_sequences
    STATUS_HISTORY_RELATED  ชื่อ related_name ของตารางประวัติสถานะ
    """

    DOC_TYPE: str = ""
    STATUS_HISTORY_RELATED: str = "status_history"

    status = models.CharField(max_length=32, db_index=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancelled_by = models.ForeignKey(
        "common.User", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    cancel_reason = models.TextField(blank=True)

    class Meta:
        abstract = True

    def delete(self, *args, **kwargs):
        raise DocumentDeletionNotAllowed(
            f"ห้ามลบ {type(self).__name__} ({self.pk}) — "
            "ยกเลิกด้วยการเปลี่ยนสถานะเป็น cancelled ผ่าน state machine เท่านั้น"
        )


class StatusHistory(AuditedModel):
    """ฐานของตารางประวัติสถานะ — แต่ละเอกสารมีตารางของตัวเอง"""

    from_status = models.CharField(max_length=32, blank=True)
    to_status = models.CharField(max_length=32)
    changed_at = models.DateTimeField()
    changed_by = models.ForeignKey(
        "common.User", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    note = models.TextField(blank=True)

    class Meta:
        abstract = True
        ordering = ["changed_at", "id"]


class DocumentSequence(AuditedModel):
    """INVARIANT — เลขที่เอกสารมาจากตารางนี้เท่านั้น ห้ามใช้ id ของแถว"""

    RESET_NONE = "none"
    RESET_YEARLY = "yearly"
    RESET_MONTHLY = "monthly"
    RESET_CHOICES = [
        (RESET_NONE, "ไม่รีเซ็ต"),
        (RESET_YEARLY, "รีเซ็ตรายปี"),
        (RESET_MONTHLY, "รีเซ็ตรายเดือน"),
    ]

    doc_type = models.CharField(max_length=32, unique=True)
    prefix = models.CharField(max_length=16)
    reset_rule = models.CharField(max_length=16, choices=RESET_CHOICES, default=RESET_YEARLY)
    padding = models.PositiveSmallIntegerField(default=5)

    class Meta:
        db_table = "document_sequences"
        ordering = ["doc_type"]

    def __str__(self):
        return f"{self.doc_type} ({self.prefix})"


class DocumentSequenceCounter(AuditedModel):
    """ตัวนับแยกตามงวด — แถวนี้คือแถวที่ถูก lock ตอนจองเลข"""

    sequence = models.ForeignKey(
        DocumentSequence, on_delete=models.PROTECT, related_name="counters"
    )
    period = models.CharField(max_length=8, blank=True)
    next_number = models.PositiveIntegerField(default=1)

    class Meta:
        db_table = "document_sequence_counters"
        constraints = [
            models.UniqueConstraint(
                fields=["sequence", "period"], name="uniq_sequence_period"
            )
        ]
