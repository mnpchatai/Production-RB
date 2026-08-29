-- Row Level Security สำหรับตาราง rb_*
--
-- schema.sql เปิด RLS ไว้แล้วแต่ไม่มี policy เลย = อ่านไม่ได้เลยนอกจาก service_role
-- ไฟล์นี้เปิดสิทธิ์อ่านให้ผู้ใช้ที่ล็อกอินแล้ว ซึ่งเป็นสิ่งที่หน้าเว็บในแอปต้องการ
--
--   psql "$SUPABASE_DB_URL" -v ON_ERROR_STOP=1 -f policies.sql
--   (หรือวางในหน้า SQL Editor ของ Supabase แล้ว Run)
--
-- จากนั้นสร้างผู้ใช้ที่ Authentication → Users แล้วล็อกอินในแอปที่
-- ตั้งค่าข้อมูลหลัก → Supabase (ข้อมูลจริง)

do $$
declare
  t text;
  tables text[] := array['rb_books','rb_colors','rb_customers','rb_products','rb_formulas',
                         'rb_item_standards','rb_bom_lines','rb_work_order_lines','rb_doc_log'];
begin
  foreach t in array tables loop
    execute format('drop policy if exists %I on public.%I', t || '_read_authenticated', t);
    execute format(
      'create policy %I on public.%I for select to authenticated using (true)',
      t || '_read_authenticated', t);
  end loop;
end $$;

-- ตรวจว่า policy ครบแล้ว
select tablename, policyname, roles, cmd
from pg_policies
where schemaname = 'public' and tablename like 'rb\_%'
order by tablename;


-- ---------------------------------------------------------------------------
-- ทางเลือก: เปิดให้อ่านโดยไม่ต้องล็อกอิน
--
-- อย่าใช้กับข้อมูลชุดนี้ถ้าหน้าเว็บอยู่บน URL สาธารณะ — anon key ฝังอยู่ในหน้าเว็บ
-- ใครเปิด DevTools ก็เห็น เท่ากับเปิดรายชื่อลูกค้า สูตรยาง และ BOM ทั้งหมดให้คนทั่วไป
-- ใช้ได้เฉพาะตอนทดสอบ หรือเมื่อหน้าเว็บอยู่หลังระบบยืนยันตัวตนจริง ๆ เท่านั้น
--
-- do $$
-- declare
--   t text;
--   tables text[] := array['rb_books','rb_colors','rb_customers','rb_products','rb_formulas',
--                          'rb_item_standards','rb_bom_lines','rb_work_order_lines','rb_doc_log'];
-- begin
--   foreach t in array tables loop
--     execute format('create policy %I on public.%I for select to anon using (true)',
--                    t || '_read_anon', t);
--   end loop;
-- end $$;
