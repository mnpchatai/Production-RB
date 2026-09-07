from django.db import migrations

CREATE_VIEW = """
CREATE OR REPLACE VIEW stock_balances AS
SELECT
    md5(item_id::text || ':' || location_id::text || ':' || lot_no) AS id,
    item_id,
    location_id,
    lot_no,
    SUM(qty_base) AS qty_on_hand
FROM (
    SELECT item_id, from_location_id AS location_id, lot_no, -qty_base AS qty_base
    FROM stock_transactions
    WHERE from_location_id IS NOT NULL
    UNION ALL
    SELECT item_id, to_location_id AS location_id, lot_no, qty_base
    FROM stock_transactions
    WHERE to_location_id IS NOT NULL
) AS movements
GROUP BY item_id, location_id, lot_no;
"""

DROP_VIEW = "DROP VIEW IF EXISTS stock_balances;"


class Migration(migrations.Migration):
    """วิวยอดคงเหลือ — สร้างจาก stock_transactions เท่านั้น (INVARIANT ข้อ 3)

    วิวนี้สร้างใหม่ได้จากศูนย์เสมอเพราะไม่มีสถานะของตัวเอง
    id เป็น md5 ของคีย์เพราะ Django ต้องการ primary key แต่วิวไม่มี
    """

    dependencies = [("inventory", "0001_initial")]

    operations = [migrations.RunSQL(sql=CREATE_VIEW, reverse_sql=DROP_VIEW)]
