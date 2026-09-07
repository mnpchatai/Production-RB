import uuid
from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from apps.production.models import ShopFloorReport
from conftest import make_work_order, receive

URL = "/api/shop-floor/report"


@pytest.fixture
def client(seeded):
    api = APIClient()
    api.force_authenticate(user=seeded["operator"])
    return api


@pytest.fixture
def open_work_order(seeded):
    receive(seeded, "SFG-CMP-01", "500", lot="SFG-LOT-1")
    return make_work_order(seeded, qty="100")


@pytest.mark.django_db
def test_report_is_accepted_and_fills_in_server_side_fields(client, open_work_order):
    response = client.post(
        URL,
        {
            "client_ref": str(uuid.uuid4()),
            "wo_no": open_work_order.wo_no,
            "operation_seq": 10,
            "qty_good": "40",
        },
        format="json",
    )
    assert response.status_code == 201, response.data
    assert response.data["work_center"] == "INJ"
    assert response.data["shift"] in {"A", "B"}
    assert response.data["work_order_status"] == "in_progress"


@pytest.mark.django_db
def test_client_supplied_server_fields_are_rejected_not_ignored(client, open_work_order):
    """ระบบเติมเอง: user, work_center, shift, เวลามาตรฐาน, ต้นทุน"""
    for field, value in [
        ("user", 1),
        ("work_center", "MIX"),
        ("shift", "A"),
        ("unit_cost", "9.99"),
        ("posted_by", 1),
    ]:
        response = client.post(
            URL,
            {
                "client_ref": str(uuid.uuid4()),
                "wo_no": open_work_order.wo_no,
                "operation_seq": 10,
                "qty_good": "1",
                field: value,
            },
            format="json",
        )
        assert response.status_code == 400, f"{field} ควรถูกปฏิเสธ"
        assert field in response.data


@pytest.mark.django_db
def test_same_client_ref_over_http_creates_one_report(client, open_work_order):
    payload = {
        "client_ref": str(uuid.uuid4()),
        "wo_no": open_work_order.wo_no,
        "operation_seq": 10,
        "qty_good": "40",
    }
    first = client.post(URL, payload, format="json")
    second = client.post(URL, payload, format="json")

    assert first.status_code == 201
    assert second.status_code == 201
    assert ShopFloorReport.objects.filter(client_ref=payload["client_ref"]).count() == 1
    open_work_order.refresh_from_db()
    assert open_work_order.operations.get(sequence=10).qty_good == Decimal("40.0000")


@pytest.mark.django_db
def test_shortage_does_not_block_the_report_but_is_flagged(seeded, client):
    """วัตถุดิบไม่พอ: บันทึกผ่าน ยอดสต็อกไม่ติดลบ และมีคิวให้ฝ่ายวางแผนตามแก้"""
    from apps.inventory.services import balance_of
    from apps.production.models import BackflushException

    work_order = make_work_order(seeded, qty="100")  # ไม่มี SFG ในคลังเลย
    response = client.post(
        URL,
        {
            "client_ref": str(uuid.uuid4()),
            "wo_no": work_order.wo_no,
            "operation_seq": 10,
            "qty_good": "50",
        },
        format="json",
    )
    assert response.status_code == 201, response.data
    assert response.data["has_exception"] is True
    assert response.data["backflush_exceptions"][0]["item_code"] == "SFG-CMP-01"

    assert balance_of(seeded["items"]["SFG-CMP-01"].pk) == Decimal(0), "ยอดติดลบ"
    assert BackflushException.objects.filter(work_order=work_order, resolved_at=None).count() == 1
    work_order.refresh_from_db()
    assert work_order.operations.get(sequence=10).qty_good == Decimal("50.0000")


@pytest.mark.django_db
def test_planner_can_resolve_the_shortage_later_without_double_issue(seeded, client):
    from apps.inventory.models import ISSUE_TO_WO, StockTransaction
    from apps.production.models import BackflushException
    from apps.production.services import resolve_backflush_exception

    work_order = make_work_order(seeded, qty="100")
    client.post(
        URL,
        {
            "client_ref": str(uuid.uuid4()),
            "wo_no": work_order.wo_no,
            "operation_seq": 10,
            "qty_good": "50",
        },
        format="json",
    )
    receive(seeded, "SFG-CMP-01", "500", lot="SFG-LOT-1")

    exception = BackflushException.objects.get(work_order=work_order, resolved_at=None)
    resolve_backflush_exception(exception, seeded["user"])
    resolve_backflush_exception(exception, seeded["user"])  # ซ้ำต้องไม่ตัดอีกรอบ

    issued = StockTransaction.objects.filter(
        doc_no=work_order.wo_no, txn_type=ISSUE_TO_WO, item__code="SFG-CMP-01"
    )
    assert issued.count() == 1
    exception.refresh_from_db()
    assert exception.resolved_at is not None


@pytest.mark.django_db
def test_unknown_work_order_returns_404(client):
    response = client.post(
        URL,
        {
            "client_ref": str(uuid.uuid4()),
            "wo_no": "WO-NOPE",
            "operation_seq": 10,
            "qty_good": "1",
        },
        format="json",
    )
    assert response.status_code == 404


@pytest.mark.django_db
def test_anonymous_requests_are_rejected(open_work_order):
    response = APIClient().post(
        URL,
        {
            "client_ref": str(uuid.uuid4()),
            "wo_no": open_work_order.wo_no,
            "operation_seq": 10,
            "qty_good": "1",
        },
        format="json",
    )
    assert response.status_code in (401, 403)
