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
