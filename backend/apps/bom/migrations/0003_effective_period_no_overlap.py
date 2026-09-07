from django.db import migrations

FORWARD = """
CREATE EXTENSION IF NOT EXISTS btree_gist;

ALTER TABLE bom_headers ADD CONSTRAINT bom_active_no_overlap
    EXCLUDE USING gist (
        item_id WITH =,
        daterange(effective_from, effective_to) WITH &&
    ) WHERE (status = 'active');

ALTER TABLE routing_headers ADD CONSTRAINT routing_active_no_overlap
    EXCLUDE USING gist (
        item_id WITH =,
        daterange(effective_from, effective_to) WITH &&
    ) WHERE (status = 'active');

ALTER TABLE work_center_rates ADD CONSTRAINT wc_rate_no_overlap
    EXCLUDE USING gist (
        work_center_id WITH =,
        daterange(effective_from, effective_to) WITH &&
    );
"""

REVERSE = """
ALTER TABLE bom_headers DROP CONSTRAINT IF EXISTS bom_active_no_overlap;
ALTER TABLE routing_headers DROP CONSTRAINT IF EXISTS routing_active_no_overlap;
ALTER TABLE work_center_rates DROP CONSTRAINT IF EXISTS wc_rate_no_overlap;
"""


class Migration(migrations.Migration):
    """ห้ามช่วงเวลามีผลทับกัน — INVARIANT ข้อ 9 บังคับที่ฐานข้อมูล

    daterange(from, to) เป็น [from, to) ตรงกับที่โค้ดใช้ (effective_to exclusive)
    to เป็น NULL แปลว่า [from, infinity)
    บังคับที่ DB เพราะการตรวจใน clean() ไม่ทำงานตอน bulk_create หรือ raw SQL
    """

    dependencies = [("bom", "0002_initial"), ("masterdata", "0001_initial")]

    operations = [migrations.RunSQL(sql=FORWARD, reverse_sql=REVERSE)]
