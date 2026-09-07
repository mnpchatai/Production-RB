from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.db import IntegrityError, transaction

from apps.bom.models import BomHeader
from apps.common.models import DocumentDeletionNotAllowed
from apps.common.state_machine import (
    APPROVED,
    CANCELLED,
    IN_PROGRESS,
    RELEASED,
    InvalidTransition,
    TransitionBlocked,
)
from apps.common.state_machine import transition
from apps.production.models import WorkOrder
from conftest import make_work_order


@pytest.mark.django_db
def test_work_order_snapshots_bom_and_routing_on_creation(seeded):
    work_order = make_work_order(seeded, qty="100", release=False)
    materials = {m.component_item.code: m for m in work_order.materials.all()}

    assert set(materials) == {"SFG-CMP-01", "PKG-BOX-01"}
    expected = (Decimal(100) * Decimal("0.25") / (Decimal(97) / Decimal(100))).quantize(
        Decimal("0.0001")
    )
    assert materials["SFG-CMP-01"].qty_required == expected
    assert materials["SFG-CMP-01"].bom_revision == "A"
    assert [op.sequence for op in work_order.operations.all()] == [10, 20, 30]
    assert work_order.operations.first().labor_rate_per_hour == Decimal("220.0000")


@pytest.mark.django_db
def test_snapshot_survives_deleting_the_source_bom_entirely(seeded):
    """เทสต์ที่แค่แก้ qty_per จับ FK ที่หลุดไม่ได้ทุกกรณี — ต้องลบทั้งฉบับ"""
    work_order = make_work_order(seeded, qty="100", release=False)
    before = {m.component_item.code: m.qty_required for m in work_order.materials.all()}

    header = BomHeader.objects.get(item__code="FG-RB-001")
    header.lines.all().delete()
    header.delete()

    work_order.refresh_from_db()
    after = {m.component_item.code: m.qty_required for m in work_order.materials.all()}
    assert after == before
    assert BomHeader.objects.filter(item__code="FG-RB-001").count() == 0


@pytest.mark.django_db
def test_editing_source_bom_does_not_change_released_work_order(seeded):
    work_order = make_work_order(seeded, qty="100")
    before = {m.component_item.code: m.qty_required for m in work_order.materials.all()}

    header = BomHeader.objects.get(item__code="FG-RB-001")
    line = header.lines.get(component_item__code="SFG-CMP-01")
    line.qty_per = Decimal("99")
    line.save()

    work_order.refresh_from_db()
    after = {m.component_item.code: m.qty_required for m in work_order.materials.all()}
    assert after == before


@pytest.mark.django_db
def test_qty_planned_locked_after_release_by_database_trigger(seeded):
    """บังคับที่ฐานข้อมูล — queryset.update() ก็ต้องผ่านไม่ได้"""
    work_order = make_work_order(seeded, qty="100")
    with pytest.raises(Exception) as exc, transaction.atomic():
        WorkOrder.objects.filter(pk=work_order.pk).update(qty_planned=Decimal("200"))
    assert "qty_planned" in str(exc.value)

    work_order.refresh_from_db()
    assert work_order.qty_planned == Decimal("100.0000")


@pytest.mark.django_db
def test_qty_planned_editable_while_draft(seeded):
    work_order = make_work_order(seeded, qty="100", release=False)
    work_order.qty_planned = Decimal("120")
    work_order.save(update_fields=["qty_planned"])
    work_order.refresh_from_db()
    assert work_order.qty_planned == Decimal("120.0000")


@pytest.mark.django_db
def test_work_order_cannot_be_hard_deleted(seeded):
    work_order = make_work_order(seeded, release=False)
    with pytest.raises(DocumentDeletionNotAllowed):
        work_order.delete()


@pytest.mark.django_db
def test_disallowed_transitions_are_rejected(seeded):
    work_order = make_work_order(seeded, release=False)
    with pytest.raises(InvalidTransition):
        transition(work_order, IN_PROGRESS, seeded["user"])

    transition(work_order, APPROVED, seeded["user"])
    transition(work_order, RELEASED, seeded["user"])
    transition(work_order, IN_PROGRESS, seeded["user"])

    with pytest.raises(InvalidTransition) as exc:
        transition(work_order, CANCELLED, seeded["user"], reason="เปลี่ยนใจ")
    assert "in_progress" in str(exc.value)


@pytest.mark.django_db
def test_cancel_requires_a_reason(seeded):
    work_order = make_work_order(seeded, release=False)
    with pytest.raises(TransitionBlocked):
        transition(work_order, CANCELLED, seeded["user"])


@pytest.mark.django_db
def test_every_transition_is_written_to_status_history(seeded):
    work_order = make_work_order(seeded)
    history = list(work_order.status_history.all())
    assert [(h.from_status, h.to_status) for h in history] == [
        ("draft", "approved"),
        ("approved", "released"),
    ]
    assert all(h.changed_by is not None for h in history)


@pytest.mark.django_db
def test_cannot_issue_work_order_when_no_bom_is_effective_that_day(seeded):
    """ออกใบในวันที่ไม่มีสูตรมีผล ต้อง raise ไม่ใช่ได้ใบเปล่าที่ไม่มีวัตถุดิบ"""
    from apps.bom.services import NoEffectiveBomError

    header = BomHeader.objects.get(item__code="FG-RB-001")
    header.effective_from = date.today() - timedelta(days=1)
    header.save()

    with pytest.raises(NoEffectiveBomError):
        make_work_order(seeded, as_of=date.today() - timedelta(days=10), release=False)


@pytest.mark.django_db
def test_snapshot_picks_the_revision_effective_on_the_snapshot_date(seeded):
    """สองรีวิชันคนละช่วงเวลา ต้องเลือกฉบับที่ตรงกับวันที่ออกใบ"""
    from apps.bom.models import ACTIVE, BomLine

    switch_day = date.today()
    old = BomHeader.objects.get(item__code="FG-RB-001")
    old.effective_to = switch_day
    old.save()

    new = BomHeader.objects.create(
        item=seeded["items"]["FG-RB-001"],
        revision="B",
        effective_from=switch_day,
        status=ACTIVE,
    )
    BomLine.objects.create(
        bom=new,
        sequence=10,
        component_item=seeded["items"]["SFG-CMP-01"],
        qty_per=Decimal("0.5000"),
        uom=seeded["uoms"]["KG"],
        scrap_pct=Decimal(0),
    )

    yesterday = make_work_order(
        seeded, qty="100", as_of=switch_day - timedelta(days=1), release=False
    )
    today_order = make_work_order(seeded, qty="100", as_of=switch_day, release=False)

    assert yesterday.bom_revision == "A"
    assert today_order.bom_revision == "B"
    assert today_order.materials.get(
        component_item__code="SFG-CMP-01"
    ).qty_required == Decimal("50.0000")
