-- RLS สำหรับตารางบันทึกผลการผลิต (ops_schema.sql)
--
--   psql "$SUPABASE_DB_URL" -v ON_ERROR_STOP=1 -f ops_policies.sql
--
-- ผู้ใช้ที่ล็อกอินแล้วอ่านได้ทุกตาราง และเขียนได้เฉพาะตารางบันทึกผล
-- ข้อมูลที่มาจาก Excel (rb_bom_lines, rb_item_standards ฯลฯ) ยังอ่านอย่างเดียว
-- ตามที่ policies.sql ตั้งไว้ — แก้ที่ไฟล์ Excel แล้วนำเข้าใหม่

do $$
declare
  t text;
  -- อ่านได้อย่างเดียว: ข้อมูลหลักที่ตั้งค่าจากฝั่งแอดมิน
  read_only text[] := array['rb_units'];
  -- อ่าน/เขียนได้: ข้อมูลหลักของแผนก + ทุกตารางบันทึกผล
  read_write text[] := array['rb_employees','rb_machines','rb_defect_reasons',
                             'rb_process_standards','rb_jobs','rb_chem_weighings',
                             'rb_chem_color','rb_mixing_runs','rb_injection_runs',
                             'rb_oven_runs','rb_hcm_runs'];
begin
  foreach t in array read_only loop
    execute format('drop policy if exists %I on public.%I', t || '_read', t);
    execute format('create policy %I on public.%I for select to authenticated using (true)',
                   t || '_read', t);
  end loop;

  foreach t in array read_write loop
    execute format('drop policy if exists %I on public.%I', t || '_read', t);
    execute format('drop policy if exists %I on public.%I', t || '_write', t);
    execute format('create policy %I on public.%I for select to authenticated using (true)',
                   t || '_read', t);
    -- for all ครอบ insert/update/delete — with check กันการเขียนข้ามสิทธิ์เมื่อเพิ่มเงื่อนไขทีหลัง
    execute format('create policy %I on public.%I for all to authenticated using (true) with check (true)',
                   t || '_write', t);
  end loop;
end $$;

-- ตรวจว่า policy ครบแล้ว
select tablename, policyname, roles, cmd
from pg_policies
where schemaname = 'public' and tablename like 'rb\_%'
order by tablename, cmd;


-- ---------------------------------------------------------------------------
-- ถ้าจะแยกสิทธิ์ตามหน่วยงานทีหลัง ให้แทน policy _write ของตารางบันทึกผล
-- ด้วยเงื่อนไขที่เช็คหน่วยของผู้ใช้จาก rb_employees เช่น
--
-- create policy rb_mixing_runs_write on public.rb_mixing_runs
--   for all to authenticated
--   using (exists (select 1 from public.rb_employees e
--                  where e.auth_email = auth.jwt() ->> 'email'
--                    and e.active and e.role in ('admin','supervisor','operator')))
--   with check (true);


-- ---------------------------------------------------------------------------
-- เซสชันอัตโนมัติ (Anonymous Sign-Ins)
-- ---------------------------------------------------------------------------
-- หน้าเว็บขอเซสชันให้เองตอนโหลดข้อมูล ผู้ใช้จึงไม่ต้องกรอกอีเมล/รหัสผ่านเลย
-- เปิดสวิตช์ที่ Dashboard → Authentication → Sign In / Providers → Anonymous Sign-Ins
--
-- เซสชันแบบนี้ได้ role = authenticated เหมือนล็อกอินปกติ policy ข้างบนจึงใช้ได้ทั้งหมด
-- โดยไม่ต้องแก้อะไร ต่างกันแค่ JWT มี claim is_anonymous = true ติดมาด้วย
--
-- ข้อควรรู้: เมื่อเปิดแล้ว ใครที่มีคีย์ฝั่งผู้ใช้ (ซึ่งอยู่ในหน้าเว็บ) ก็ขอเซสชันได้
-- เท่ากับข้อมูลเปิดให้คนที่เข้าถึงหน้าเว็บได้ทุกคน — รับได้ถ้าเว็บอยู่หลัง VPN หรือ
-- อยู่ในวงภายใน แต่ถ้าเว็บอยู่บน URL สาธารณะ ให้ใช้ policy ข้างล่างแทน
--
-- ขั้นถัดไปตอนจะแยกสิทธิ์: "อ่านได้ทุกเซสชัน แต่เขียนได้เฉพาะคนที่ล็อกอินจริง"
-- ทำได้ที่ฝั่ง SQL อย่างเดียว ไม่ต้องแตะหน้าเว็บเลย
--
-- create policy rb_mixing_runs_write on public.rb_mixing_runs
--   for all to authenticated
--   using      (coalesce((auth.jwt() ->> 'is_anonymous')::boolean, false) = false)
--   with check (coalesce((auth.jwt() ->> 'is_anonymous')::boolean, false) = false);
--
-- และถ้าอยากปิดการอ่านของเซสชันอัตโนมัติด้วย ก็เติมเงื่อนไขเดียวกันใน policy _read
-- ของตารางที่อ่อนไหว (rb_customers, rb_formulas, rb_bom_lines)
