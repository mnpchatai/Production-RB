-- เปิดสิทธิ์เต็มชั่วคราว — อ่าน/เขียนได้ทุกตาราง rb_* ไม่แยกสิทธิ์
--
--   psql "$SUPABASE_DB_URL" -v ON_ERROR_STOP=1 -f full_access.sql
--   (หรือวางในหน้า SQL Editor ของ Supabase แล้ว Run)
--
-- ใช้ไฟล์นี้แทน policies.sql + ops_policies.sql ในช่วงที่ยังไม่กำหนดสิทธิ์
-- รันซ้ำได้ไม่มีปัญหา — ลบ policy เดิมบนตาราง rb_* ทุกอันแล้วสร้างใหม่ให้เหลืออันเดียว
--
-- ต่างจากสองไฟล์นั้นตรงไหน
--   · เขียนได้ทุกตาราง รวมตารางที่มาจาก Excel และ rb_units ซึ่งเดิมอ่านอย่างเดียว
--   · ให้สิทธิ์ทั้ง role anon และ authenticated หน้าเว็บจึงใช้ได้ทันที
--     ไม่ว่าจะเปิด Anonymous Sign-Ins ไว้หรือยัง
--
-- *** เปิดเต็มแปลว่าใครเปิดหน้าเว็บได้ก็อ่านและแก้ข้อมูลได้ทุกอย่าง ***
-- ตราบใดที่เว็บอยู่บน URL สาธารณะ (GitHub Pages) เท่ากับเปิดรายชื่อลูกค้า สูตรยาง
-- BOM และบันทึกผลการผลิตทั้งหมดให้คนทั่วไป — รับได้ตอนยังไม่มีข้อมูลจริง
-- หรือเว็บอยู่ในวงภายใน แต่ก่อนขึ้นใช้งานจริงควรกลับไปล็อกตามหัวข้อท้ายไฟล์

do $$
declare
  t text;
  p text;
  tables text[];
  pols   text[];
begin
  -- เก็บรายชื่อไว้ก่อนแล้วค่อยวน — ไม่แก้ catalog ระหว่างที่ยังอ่าน catalog อยู่
  select coalesce(array_agg(tablename), '{}')
    into tables
    from pg_tables
   where schemaname = 'public' and tablename like 'rb\_%';

  foreach t in array tables loop
    execute format('alter table public.%I enable row level security', t);

    -- ลบ policy เดิมทุกอันบนตารางนี้ ไม่ว่าจะมาจาก policies.sql, ops_policies.sql
    -- หรือที่เคยเขียนเองไว้ กันสองชุดทับกันจนงงว่าอันไหนมีผล
    select coalesce(array_agg(policyname), '{}')
      into pols
      from pg_policies
     where schemaname = 'public' and tablename = t;

    foreach p in array pols loop
      execute format('drop policy %I on public.%I', p, t);
    end loop;

    execute format(
      'create policy %I on public.%I for all to anon, authenticated using (true) with check (true)',
      t || '_full', t);
  end loop;
end $$;

-- ตรวจว่าเหลือ policy เดียวต่อตารางจริง
select tablename, policyname, roles, cmd
from pg_policies
where schemaname = 'public' and tablename like 'rb\_%'
order by tablename;


-- ---------------------------------------------------------------------------
-- ตอนจะกลับไปล็อก
-- ---------------------------------------------------------------------------
-- รัน policies.sql กับ ops_policies.sql ทับได้เลย ทั้งสองไฟล์ drop policy เดิมก่อนสร้างใหม่
-- แต่ policy ชื่อ rb_*_full ที่ไฟล์นี้สร้างไว้จะไม่ถูกลบ ต้องลบเองก่อน:
--
--   do $$
--   declare t text;
--   begin
--     for t in select tablename from pg_tables
--              where schemaname = 'public' and tablename like 'rb\_%'
--     loop
--       execute format('drop policy if exists %I on public.%I', t || '_full', t);
--     end loop;
--   end $$;
--
-- จากนั้นค่อยเลือกว่าจะล็อกระดับไหน — ทั้งสองแบบทำที่ฝั่ง SQL อย่างเดียว ไม่ต้องแตะหน้าเว็บ
--
--   1. เขียนได้เฉพาะคนที่ล็อกอินจริง (เซสชันอัตโนมัติอ่านได้อย่างเดียว)
--      ใช้ claim is_anonymous — ดูตัวอย่างท้าย ops_policies.sql
--   2. แยกสิทธิ์รายหน่วยตาม rb_employees.role — ดูตัวอย่างท้าย ops_policies.sql เช่นกัน
