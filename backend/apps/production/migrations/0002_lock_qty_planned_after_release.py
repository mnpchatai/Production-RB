from django.db import migrations

FORWARD = """
CREATE OR REPLACE FUNCTION wo_guard_qty_planned() RETURNS trigger AS $$
BEGIN
    IF OLD.status NOT IN ('draft', 'approved')
       AND NEW.qty_planned IS DISTINCT FROM OLD.qty_planned THEN
        RAISE EXCEPTION
            'ใบสั่งผลิต % อยู่ในสถานะ % แล้ว แก้ qty_planned ไม่ได้',
            OLD.wo_no, OLD.status
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER wo_guard_qty_planned_trg
    BEFORE UPDATE ON work_orders
    FOR EACH ROW EXECUTE FUNCTION wo_guard_qty_planned();
"""

REVERSE = """
DROP TRIGGER IF EXISTS wo_guard_qty_planned_trg ON work_orders;
DROP FUNCTION IF EXISTS wo_guard_qty_planned();
"""


class Migration(migrations.Migration):
    """released ขึ้นไปห้ามแก้ qty_planned — บังคับที่ฐานข้อมูล

    CheckConstraint เทียบกับค่าเดิมไม่ได้ จึงต้องใช้ trigger
    บังคับที่ DB เพราะ clean() ไม่ทำงานตอน queryset.update() หรือ raw SQL
    """

    dependencies = [("production", "0001_initial")]

    operations = [migrations.RunSQL(sql=FORWARD, reverse_sql=REVERSE)]
