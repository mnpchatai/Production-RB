-- =============================================================================
-- ติดตั้ง Supabase ให้ระบบใบสั่งงานแผนกขึ้นรูปยาง — รันไฟล์เดียวจบ
-- =============================================================================
-- วางทั้งไฟล์ในหน้า SQL Editor ของ Supabase แล้วกด Run (หรือ Ctrl+Enter)
-- ใช้เวลาไม่กี่วินาที และรันซ้ำได้ไม่มีปัญหาถ้าไม่แน่ใจว่ารันไปหรือยัง
--
-- ไฟล์นี้คือสามไฟล์นี้ต่อกันตามลำดับ ไม่ได้แก้เนื้อในเลย:
--   1. schema.sql       ตารางที่รับข้อมูลจาก Excel
--   2. ops_schema.sql   ตารางบันทึกผลการผลิต + ข้อมูลหลักของแผนก
--   3. full_access.sql  สิทธิ์เต็มทุกตาราง (ยังไม่แยกสิทธิ์)
--
-- อยากรันทีละไฟล์ก็ยังทำได้ ไฟล์ต้นฉบับยังอยู่ที่เดิมในโฟลเดอร์นี้
--
-- รันเสร็จจะได้ตารางผลลัพธ์ 21 แถว ตารางละหนึ่ง policy ชื่อ <ตาราง>_full
-- ถ้าเห็นครบแปลว่าเรียบร้อย เอา Project URL ไปวางที่หน้าเว็บได้เลย
--
-- *** เปิดสิทธิ์เต็ม = ใครเปิดหน้าเว็บได้ก็อ่านและแก้ข้อมูลได้ทุกอย่าง ***
-- ตั้งใจไว้แบบนี้ระหว่างที่ยังไม่กำหนดสิทธิ์ — ก่อนขึ้นใช้งานจริงกับข้อมูลจริง
-- ให้กลับไปล็อกตามวิธีท้าย full_access.sql
-- =============================================================================



-- #############################################################################
-- ##  1. schema.sql — ตารางที่รับข้อมูลจาก Excel
-- #############################################################################

-- =============================================================================
-- ระบบวางแผนการสั่งงานแผนก RB (V1.7.1) — Supabase / PostgreSQL schema
-- แปลงจากไฟล์ Excel .xlsm สองเล่ม (สมุดงาน TOY และสมุดงานยางอุตสาหกรรม)
--
-- โครงสร้างยึดตามชีตต้นทางแบบตรงตัว เพื่อให้ย้ายข้อมูลได้ครบโดยไม่ตีความเกิน:
--   Master_Rubber      -> rb_formulas
--   DATA STANDARD      -> rb_item_standards
--   DATA BOM           -> rb_bom_lines
--   Chronicle_Working  -> rb_work_order_lines
--   System (D:G/I:J/L:M) -> rb_colors / rb_customers / rb_products
--   LogSheet           -> rb_doc_log
--
-- ทุกตารางผูกกับ rb_books เพราะสองเล่มใช้รหัสชนกันได้ (เลขใบสั่งผลิตคนละชุด
-- รหัสชิ้นงานซ้ำกันแค่ 12 รหัส) การรวมเป็นชุดเดียวจะทำให้ข้อมูลทับกัน
-- =============================================================================

create extension if not exists pgcrypto;

-- ---------------------------------------------------------------- สมุดงานต้นทาง
create table if not exists public.rb_books (
  code          text primary key,          -- 'TOY' / 'IND'
  name          text not null,
  source_file   text,                      -- ชื่อไฟล์ .xlsm ต้นทาง
  app_version   text,                      -- เวอร์ชันของไฟล์ Excel เช่น V1.7.1
  doc_no        text,                      -- เลขที่เอกสารในชีต LogSheet
  settings      jsonb not null default '{}'::jsonb,  -- ค่าที่ค้างอยู่บนหน้า System
  imported_at   timestamptz not null default now()
);

-- ---------------------------------------------------------------- สีมาตรฐาน
create table if not exists public.rb_colors (
  book_code   text not null references public.rb_books(code) on delete cascade,
  seq         integer,
  color_code  text not null,               -- BK01
  color_name  text,                        -- ดำ # 19
  color_group text,                        -- BK
  primary key (book_code, color_code)
);

-- ---------------------------------------------------------------- ลูกค้า / ออร์เดอร์
create table if not exists public.rb_customers (
  book_code     text not null references public.rb_books(code) on delete cascade,
  seq           integer,
  customer_name text not null,
  primary key (book_code, customer_name)
);

-- ---------------------------------------------------------------- รหัสสินค้าสำเร็จรูป
create table if not exists public.rb_products (
  book_code text not null references public.rb_books(code) on delete cascade,
  seq       integer,
  item_code text not null,                 -- ACG-01-A, Magic-SBS-02(B)-Z
  primary key (book_code, item_code)
);

-- ---------------------------------------------------------------- สูตรยาง (การตียาง)
create table if not exists public.rb_formulas (
  book_code            text not null references public.rb_books(code) on delete cascade,
  seq                  integer,
  formula_code         text not null,      -- B0000
  batch_weight_kg      numeric,            -- น้ำหนักต่อ 1 โม่ (kg.)
  strands_per_batch    numeric,            -- จำนวนเส้นยางที่ได้ต่อ 1 โม่
  weight_per_strand_kg numeric,            -- น้ำหนักยางต่อ 1 เส้นยาว (kg.)
  min_add_weight_kg    numeric,            -- น้ำหนักเพิ่ม-ขั้นต่ำ (kg.)
  primary key (book_code, formula_code)
);

-- ---------------------------------------------------------------- มาตรฐานชิ้นงาน RB
-- ชีตต้นทางเป็นรายการต่อท้ายไปเรื่อย ๆ รหัสเดียวกันจึงซ้ำได้หลายร้อยบรรทัด
-- (ต่างกันแค่ชื่อชิ้นงานที่พ่วงสีไว้) ตารางนี้ยุบเหลือรหัสละแถว
-- source_rows / name_variants บอกว่ายุบมาจากกี่บรรทัดและมีชื่อกี่แบบ
create table if not exists public.rb_item_standards (
  book_code           text not null references public.rb_books(code) on delete cascade,
  seq                 integer,
  dept                text,                -- แผนก
  rubber_type         text,                -- ประเภทยาง
  length_txt          text,                -- ยาว (เป็น text เพราะมีค่า 'XX')
  hole_txt            text,                -- รู / หนา
  outer_txt           text,                -- กว้าง / วงนอก
  item_code           text not null,       -- รหัสชิ้นงาน RB-A2003-02-212-14-19
  item_name           text,                -- ชื่อชิ้นงาน (ชื่อที่พบบ่อยที่สุด)
  weight_per_strand_g numeric,             -- น้ำหนักต่อเส้น RB (g.)
  head_allowance_kg   numeric,             -- นน.เผื่อแกะหัวเครื่องฉีด (กก.)
  joint_scrap_pct     numeric,             -- % นน.เผื่อเสียข้อต่อหัวท้าย
  general_scrap_pct   numeric,             -- % นน.เผื่อเสียทั่วไป RB
  formula_code        text,                -- สูตรยาง
  name_variants       integer not null default 1,
  source_rows         integer not null default 1,
  primary key (book_code, item_code)
);

-- ---------------------------------------------------------------- สูตรการผลิต (BOM)
-- สินค้าหนึ่งตัวใช้ชิ้นงาน RB รหัสเดิมซ้ำได้ (คนละความยาวตัด/คนละจำนวนต่อชุด)
-- จึงไม่ตั้ง unique ที่ (product_item, rb_code) — ใช้ src_row กันนำเข้าซ้ำแทน
create table if not exists public.rb_bom_lines (
  id               bigserial primary key,
  book_code        text not null references public.rb_books(code) on delete cascade,
  src_row          integer not null,       -- เลขแถวจริงในชีต DATA BOM
  product_item     text not null,          -- ITEM (รหัสสินค้าสำเร็จรูป)
  rb_weight_g      numeric,                -- นน. RB
  rb_code          text not null,          -- CODE
  dept_code        text,                   -- รหัสแผนก
  formula_code     text,                   -- สินค้า/สูตรยาง
  rubber_type      text,                   -- ประเภทยาง
  color_code       text,                   -- สี RB
  length_txt       text,                   -- ความยาว RB
  hole_txt         text,                   -- รูใน RB
  outer_txt        text,                   -- วงนอก RB
  rb_name          text,                   -- NAME
  producer_dept    text,                   -- แผนกผู้ผลิต
  qty_per_set      numeric,                -- จำนวนที่ใช้ต่อชุด
  cut_length       numeric,                -- ความยาวตัด
  cut_length_unit  text,
  pcs_per_strand   numeric,                -- จำนวนชิ้นที่ได้ต่อเส้น RB
  pcs_unit         text,
  qty_per_gr       numeric,                -- จำนวนที่ได้ต่อ 1 GR
  qty_per_gr_unit  text,
  rb_uom           text,                   -- หน่วยนับ RB
  -- รหัสในชีต BOM มีช่องสีคั่นอยู่ด้วย (RB-A2003-02--212-14-19) ส่วนชีต DATA STANDARD
  -- ไม่มี (RB-A2003-02-212-14-19) จึง join ตรง ๆ ไม่ติดสักแถว
  -- คอลัมน์นี้ประกอบรหัสขึ้นใหม่จากชิ้นส่วนให้ตรงรูปแบบของ rb_item_standards.item_code
  rb_code_std      text generated always as (
                     coalesce(dept_code,'')    || '-' || coalesce(formula_code,'') || '-' ||
                     coalesce(rubber_type,'')  || '-' || coalesce(length_txt,'')   || '-' ||
                     coalesce(hole_txt,'')     || '-' || coalesce(outer_txt,'')
                   ) stored,
  unique (book_code, src_row)
);

-- ---------------------------------------------------------------- ใบสั่งงาน
-- คอลัมน์ S:AX ของชีตเป็นค่ามาตรฐานที่ VLOOKUP มาแปะไว้ตอนสั่งงาน
-- เก็บไว้ทั้งก้อนใน std_snapshot เพื่อคงค่า ณ วันที่สั่ง ไม่ต้องเพิ่มอีก 30 คอลัมน์
create table if not exists public.rb_work_order_lines (
  id                   bigserial primary key,
  book_code            text not null references public.rb_books(code) on delete cascade,
  src_row              integer not null,   -- เลขแถวจริงในชีต Chronicle_Working
  seq                  integer,            -- ลำดับ
  customer_name        text,               -- ออร์เดอร์
  production_order_no  text,               -- เลขที่ใบสั่งผลิต
  fg_code              text,               -- รหัสสินค้าสำเร็จรูป
  rb_code              text,               -- รหัสอะไหล่ RB
  rb_name              text,               -- ชื่ออะไหล่ RB
  color                text,               -- สี
  qty_kg               numeric,            -- จำนวนสั่งงาน (กก.)
  mixing_strands       numeric,            -- จำนวนเส้นตียาง (40 กก.)
  rb_strands           numeric,            -- จำนวนเส้นยางยาว RB (ชิ้น)
  head_allowance_kg    numeric,            -- นน.เผื่อแกะหัว (กก.)
  joint_allowance_kg   numeric,            -- นน.เผื่อข้อต่อหัวท้าย (กก.)
  general_scrap_kg     numeric,            -- นน.เผื่อเสียทั่วไป RB (กก.)
  other_dept_scrap_kg  numeric,            -- นน.เผื่อเสียทั่วไปแผนกอื่น (กก.)
  mixing_start         date,               -- กำหนดเริ่ม ตียาง
  injection_due        date,               -- กำหนดเสร็จ ฉีดยาง
  hcm_due              date,               -- กำหนดเสร็จ HCM
  work_order_no        text,               -- หมายเหตุ (เลขที่ใบสั่งงาน) เช่น 1/26
  std_snapshot         jsonb not null default '{}'::jsonb,
  unique (book_code, src_row)
);

-- ---------------------------------------------------------------- ทะเบียนรับเอกสาร
create table if not exists public.rb_doc_log (
  book_code     text not null references public.rb_books(code) on delete cascade,
  seq           integer not null,
  sent_date     date,                      -- วันที่ส่งเอกสาร
  work_order_no text,                      -- เลขที่ใบสั่งงาน
  job_type      text,                      -- ประเภทงานที่สั่ง
  doc_count     text,                      -- จำนวนเอกสาร (ชุด/2แผ่น)
  customer_name text,                      -- ชื่อลูกค้า
  pi_order_no   text,                      -- เลขที่ PI ออเดอร์
  sender        text,                      -- ผู้ส่งเอกสาร
  receiver      text,                      -- ผู้รับเอกสาร
  primary key (book_code, seq)
);

-- ---------------------------------------------------------------- ดัชนี
create index if not exists idx_rb_bom_product  on public.rb_bom_lines(book_code, product_item);
create index if not exists idx_rb_bom_rb_code  on public.rb_bom_lines(book_code, rb_code);
create index if not exists idx_rb_bom_formula  on public.rb_bom_lines(book_code, formula_code);
create index if not exists idx_rb_bom_std     on public.rb_bom_lines(book_code, rb_code_std);
create index if not exists idx_rb_std_formula  on public.rb_item_standards(book_code, formula_code);
create index if not exists idx_rb_wo_order     on public.rb_work_order_lines(book_code, production_order_no);
create index if not exists idx_rb_wo_rb_code   on public.rb_work_order_lines(book_code, rb_code);
create index if not exists idx_rb_wo_wono      on public.rb_work_order_lines(book_code, work_order_no);
create index if not exists idx_rb_wo_mixing    on public.rb_work_order_lines(mixing_start);
create index if not exists idx_rb_wo_hcm_due   on public.rb_work_order_lines(hcm_due);

-- ---------------------------------------------------------------- วิวรวมสองเล่ม
-- ใช้เมื่ออยากค้นข้ามเล่ม โดยยังรู้ว่าแถวไหนมาจากเล่มไหน
--
-- ทุกวิวต้องมี security_invoker = on — ไม่งั้น PostgreSQL 15+ จะรันวิวด้วยสิทธิ์ของ
-- "คนสร้างวิว" ไม่ใช่ "คนที่กำลังคิวรี" เท่ากับวิวข้าม RLS ของตารางที่มันอ่านไปเลย
-- (Database Linter ของ Supabase จะขึ้น ERROR security_definer_view ถ้าไม่ใส่)
-- ตอนนี้เปิดสิทธิ์เต็มอยู่จึงยังไม่ต่างอะไร แต่พอกลับไปล็อกสิทธิ์เมื่อไหร่ วิวที่ไม่ใส่
-- จะกลายเป็นช่องให้อ่านข้ามสิทธิ์ทันที
create or replace view public.v_rb_item_standards_all with (security_invoker = on) as
  select s.*, b.name as book_name from public.rb_item_standards s
  join public.rb_books b on b.code = s.book_code;

create or replace view public.v_rb_bom_all with (security_invoker = on) as
  select l.*, b.name as book_name from public.rb_bom_lines l
  join public.rb_books b on b.code = l.book_code;

create or replace view public.v_rb_work_orders_all with (security_invoker = on) as
  select w.*, b.name as book_name from public.rb_work_order_lines w
  join public.rb_books b on b.code = w.book_code;

-- สรุปใบสั่งผลิต 1 แถวต่อ 1 ใบ (ชีตต้นทางเก็บเป็นรายบรรทัดอะไหล่)
create or replace view public.v_rb_production_orders with (security_invoker = on) as
  select book_code,
         production_order_no,
         min(customer_name)          as customer_name,
         count(*)                    as line_count,
         count(distinct fg_code)     as fg_count,
         sum(qty_kg)                 as total_qty_kg,
         min(mixing_start)           as mixing_start,
         max(injection_due)          as injection_due,
         max(hcm_due)                as hcm_due
  from public.rb_work_order_lines
  where production_order_no is not null
  group by book_code, production_order_no;

-- BOM ต่อกับมาตรฐานชิ้นงานผ่าน rb_code_std
create or replace view public.v_rb_bom_with_standard with (security_invoker = on) as
  select l.*,
         s.item_name           as std_item_name,
         s.weight_per_strand_g as std_weight_per_strand_g,
         s.head_allowance_kg   as std_head_allowance_kg,
         s.joint_scrap_pct     as std_joint_scrap_pct,
         s.general_scrap_pct   as std_general_scrap_pct,
         s.formula_code        as std_formula_code
  from public.rb_bom_lines l
  left join public.rb_item_standards s
         on s.book_code = l.book_code and s.item_code = l.rb_code_std;

-- รหัสที่ถูกใช้งานจริงแต่ยังไม่มีแถวใน DATA STANDARD (ช่องว่างของข้อมูลต้นทาง)
create or replace view public.v_rb_missing_standards with (security_invoker = on) as
  select book_code, rb_code_std as item_code, 'bom' as used_in, count(*) as uses,
         min(rb_name) as sample_name
  from public.rb_bom_lines l
  where rb_code_std is not null
    and not exists (select 1 from public.rb_item_standards s
                    where s.book_code = l.book_code and s.item_code = l.rb_code_std)
  group by 1, 2
  union all
  select book_code, rb_code, 'work_order', count(*), min(rb_name)
  from public.rb_work_order_lines w
  where rb_code is not null
    and not exists (select 1 from public.rb_item_standards s
                    where s.book_code = w.book_code and s.item_code = w.rb_code)
  group by 1, 2;

-- ---------------------------------------------------------------- RLS
-- เปิด RLS ไว้ก่อน แล้วค่อยเพิ่ม policy ตามสิทธิ์ที่ต้องการ
-- ระหว่างที่ยังไม่มี policy จะเข้าถึงได้เฉพาะ service_role เท่านั้น
alter table public.rb_books            enable row level security;
alter table public.rb_colors           enable row level security;
alter table public.rb_customers        enable row level security;
alter table public.rb_products         enable row level security;
alter table public.rb_formulas         enable row level security;
alter table public.rb_item_standards   enable row level security;
alter table public.rb_bom_lines        enable row level security;
alter table public.rb_work_order_lines enable row level security;
alter table public.rb_doc_log          enable row level security;

-- ตัวอย่าง policy: ให้ผู้ใช้ที่ล็อกอินแล้วอ่านได้ทุกตาราง (รันเมื่อพร้อมใช้จริง)
-- do $$
-- declare t text;
-- begin
--   foreach t in array array['rb_books','rb_colors','rb_customers','rb_products',
--                            'rb_formulas','rb_item_standards','rb_bom_lines',
--                            'rb_work_order_lines','rb_doc_log']
--   loop
--     execute format('create policy %I on public.%I for select to authenticated using (true)', t||'_read', t);
--   end loop;
-- end $$;


-- #############################################################################
-- ##  2. ops_schema.sql — ตารางบันทึกผลการผลิต + ข้อมูลหลักของแผนก
-- #############################################################################

-- =============================================================================
-- ใบสั่งงานแผนกขึ้นรูปยาง — ตารางสำหรับบันทึกผลการผลิตจริง
--
-- โครงยึดตามชีต "ใบสั่งงานในแผนก" ของไฟล์ V1.7.1 ทีละหน่วยงาน:
--   1.หน่วยชั่งเคมี              -> rb_chem_weighings
--   2.หน่วยตียาง                 -> rb_mixing_runs
--   3.หน่วยฉีดยาง                -> rb_injection_runs
--   4.มาตรฐานการอบยางตู้อบ       -> rb_oven_runs
--   5.หน่วยอบยางเครื่องยาว HCM   -> rb_hcm_runs
--
-- ต้องรัน schema.sql ก่อน (ตาราง rb_work_order_lines ถูกอ้างถึงที่นี่)
-- แล้วรัน ops_policies.sql ต่อ ไม่งั้น RLS จะบล็อกทั้งอ่านและเขียน
-- =============================================================================

create extension if not exists pgcrypto;

-- ---------------------------------------------------------------- ข้อมูลหลักของแผนก

-- พนักงาน — ใช้เป็นตัวเลือกผู้ปฏิบัติงานในทุกหน่วย และผูกกับผู้ใช้ Supabase
create table if not exists public.rb_employees (
  code       text primary key,          -- EMP-001-ADM
  name       text not null,
  dept       text,                      -- IT & Digital Transformation
  role       text not null default 'operator',  -- admin / supervisor / operator / viewer
  auth_email text,                      -- อีเมลผู้ใช้ใน Supabase Auth (ถ้าผูกไว้)
  active     boolean not null default true,
  created_at timestamptz not null default now()
);

-- หน่วยงานในสายการผลิต — ใช้เป็น enum กลางของทั้งระบบ
create table if not exists public.rb_units (
  code     text primary key,            -- CHEM / MIX / INJ / OVEN / HCM
  name     text not null,
  step_no  integer not null,
  created_at timestamptz not null default now()
);

insert into public.rb_units(code, name, step_no) values
  ('CHEM', 'หน่วยชั่งเคมี',            0),
  ('MIX',  'หน่วยตียาง',                1),
  ('INJ',  'หน่วยฉีดยาง',               2),
  ('OVEN', 'หน่วยอบยาง (ตู้อบ)',        3),
  ('HCM',  'หน่วยอบยางเครื่องยาว HCM',  4)
on conflict (code) do nothing;

-- เครื่องจักรแยกตามหน่วย
create table if not exists public.rb_machines (
  code      text primary key,           -- MX-01 / IJ-02 / OV-01 / HCM-01
  name      text not null,
  unit_code text not null references public.rb_units(code),
  active    boolean not null default true,
  created_at timestamptz not null default now()
);

-- สาเหตุของเสีย แยกตามหน่วย (ช่อง "นิยามอาการเสีย" ในใบสั่งงาน)
create table if not exists public.rb_defect_reasons (
  id        bigserial primary key,
  unit_code text not null references public.rb_units(code),
  label     text not null,
  active    boolean not null default true,
  unique (unit_code, label)
);

-- มาตรฐานของขั้นฉีด/อบ/HCM
-- คอลัมน์พวกนี้มีอยู่ในชีต DATA STANDARD แต่ว่างทั้งสองเล่ม จึงเปิดให้กรอกในระบบแทน
create table if not exists public.rb_process_standards (
  book_code        text not null,
  item_code        text not null,       -- รหัสชิ้นงาน RB (รูปแบบเดียวกับ rb_item_standards.item_code)
  inj_hole_mm      numeric,             -- ฉีดยาง: รูใน
  inj_outer_mm     numeric,             --          วงนอก
  inj_thick_mm     numeric,             --          ความหนา
  inj_width_mm     numeric,             --          ความกว้าง
  inj_flange       text,                --          หน้าแปลน
  inj_shaft        text,                --          ขนาดเพลา
  inj_speed        text,                --          ความเร็ว
  oven_temp_c      numeric,             -- ตู้อบ: อุณหภูมิ (°C)
  oven_minutes     numeric,             --        ระยะเวลา (นาที)
  hcm_temp_c       numeric,             -- HCM: อุณหภูมิในการผลิต
  hcm_speed        text,                --       ความเร็วในการวิ่ง
  hcm_cut_length   numeric,             --       ความยาวตัดหน้าเครื่อง
  hcm_strands      numeric,             --       จำนวนเส้นที่วิ่ง
  hcm_hot_outer    numeric,             --       ขนาดยางร้อน วงนอก/กว้าง
  hcm_hot_hole     numeric,             --       ขนาดยางร้อน รูใน/หนา
  updated_at       timestamptz not null default now(),
  updated_by       text,
  primary key (book_code, item_code)
);

-- ---------------------------------------------------------------- ใบสั่งงาน

-- หัวใบสั่งงานที่ออกให้แผนกขึ้นรูปยาง — หนึ่งใบต่อหนึ่งบรรทัดในชีต Chronicle_Working
--
-- ตั้งใจไม่ผูก foreign key ไปยังตารางที่มาจาก Excel (rb_books / rb_work_order_lines)
-- เพราะตารางพวกนั้นถูกล้างแล้วนำเข้าใหม่ทุกครั้งที่แก้ไฟล์ Excel — ถ้าผูก FK ไว้
-- การนำเข้ารอบใหม่จะลากบันทึกผลการผลิตหายไปด้วย
-- อ้างอิงกันด้วย (book_code, wo_src_row) ซึ่งเป็นคีย์ที่คงที่ข้ามการนำเข้า
create table if not exists public.rb_jobs (
  id           bigserial primary key,
  book_code    text not null,
  wo_src_row   integer,                 -- rb_work_order_lines.src_row (เลขแถวจริงในชีต)
  job_no       text not null,           -- เลขที่ RB บนหัวใบสั่งงาน เช่น 521/26
  issued_at    timestamptz not null default now(),
  issued_by    text,
  status       text not null default 'ISSUED',
                 -- ISSUED -> CHEM -> MIX -> INJ -> OVEN -> HCM -> DONE
                 -- (HOLD / CANCELLED ได้ทุกจังหวะ)
  note         text,
  created_at   timestamptz not null default now(),
  updated_at   timestamptz not null default now(),
  unique (book_code, job_no)
);

-- ---------------------------------------------------------------- บันทึกผลรายหน่วย

-- 1.หน่วยชั่งเคมี — เคมีขั้นที่ 1-3 อย่างละ จำนวนถุง/น้ำหนัก/ผลตรวจ
create table if not exists public.rb_chem_weighings (
  id          bigserial primary key,
  job_id      bigint not null references public.rb_jobs(id) on delete cascade,
  step_no     integer not null check (step_no between 1 and 3),
  bags        numeric,                  -- จำนวนถุง
  weight_kg   numeric,                  -- น้ำหนัก
  qc_pass     boolean,                  -- ตรวจสอบ ผ่าน/ไม่ผ่าน (null = ยังไม่ตรวจ)
  operator    text,
  recorded_at timestamptz not null default now(),
  note        text,
  unique (job_id, step_no)
);

-- ปริมาณสีที่ใช้ต่อ 1 เส้น — บรรทัดเดียวต่อใบสั่งงาน
create table if not exists public.rb_chem_color (
  job_id      bigint primary key references public.rb_jobs(id) on delete cascade,
  weight_kg   numeric,
  qc_pass     boolean,
  operator    text,
  recorded_at timestamptz not null default now(),
  note        text
);

-- 2.หน่วยตียาง
create table if not exists public.rb_mixing_runs (
  id           bigserial primary key,
  job_id       bigint not null references public.rb_jobs(id) on delete cascade,
  seq          integer not null,        -- ลำดับแถวในใบสั่งงาน (1-4)
  prod_date    date,                    -- วันที่ทำการผลิต
  time_start   time,                    -- เวลาปฏิบัติงาน เริ่ม
  time_end     time,                    --                 เสร็จ
  machine_code text references public.rb_machines(code),
  temp_c       numeric,                 -- ระดับอุณหภูมิที่ใช้ในการตียาง
  good_kg      numeric,                 -- ชิ้นงานดี (กก.)
  good_strands numeric,                 -- ชิ้นงานดี (เส้น)
  scrap_reason text,                    -- ชิ้นงานเสีย: สาเหตุ
  scrap_kg     numeric,                 --              จำนวน (กก.)
  operator     text,
  note         text,
  recorded_at  timestamptz not null default now(),
  unique (job_id, seq)
);

-- 3.หน่วยฉีดยาง
create table if not exists public.rb_injection_runs (
  id            bigserial primary key,
  job_id        bigint not null references public.rb_jobs(id) on delete cascade,
  seq           integer not null,       -- ลำดับแถวในใบสั่งงาน (1-4)
  prod_date     date,
  setup_start   time,                   -- ตั้งเครื่อง เริ่ม
  setup_end     time,                   --            เสร็จ
  run_start     time,                   -- เวลาปฏิบัติงาน เริ่ม
  run_end       time,                   --                 เสร็จ
  head_trim_kg  numeric,                -- นน.แกะหัว (กก.)
  machine_code  text references public.rb_machines(code),
  good_kg       numeric,                -- ชิ้นงานดี (กก.)
  good_trays    numeric,                -- ชิ้นงานดี (ถาด)
  rubber_kg     numeric,                -- นน.ยาง
  scrap_reason  text,
  scrap_kg      numeric,
  chk_hole_mm   numeric,                -- ตรวจสอบขนาด: รูใน
  chk_outer_mm  numeric,                --               วงนอก
  chk_width_mm  numeric,                --               กว้าง
  chk_thick_mm  numeric,                --               หนา
  op_out        text,                   -- ผู้ออกยาง
  op_cut        text,                   -- ผู้ตัดยาง
  op_stuff      text,                   -- ผู้ยัดยาง
  op_roll       text,                   -- ผู้ม้วนยาง
  note          text,
  recorded_at   timestamptz not null default now(),
  unique (job_id, seq)
);

-- 4.หน่วยอบยาง (ตู้อบ)
create table if not exists public.rb_oven_runs (
  id           bigserial primary key,
  job_id       bigint not null references public.rb_jobs(id) on delete cascade,
  seq          integer not null,
  prod_date    date,
  machine_code text references public.rb_machines(code),
  temp_c       numeric,                 -- อุณหภูมิในการอบยาง
  minutes      numeric,                 -- ระยะเวลาในการอบยาง
  time_in      time,                    -- เข้าตู้
  time_out     time,                    -- ออกตู้
  good_qty     numeric,
  good_unit    text,
  scrap_reason text,
  scrap_qty    numeric,
  operator     text,
  note         text,
  recorded_at  timestamptz not null default now(),
  unique (job_id, seq)
);

-- 5.หน่วยอบยางเครื่องยาว HCM
create table if not exists public.rb_hcm_runs (
  id            bigserial primary key,
  job_id        bigint not null references public.rb_jobs(id) on delete cascade,
  seq           integer not null,       -- ลำดับแถวในใบสั่งงาน (1-6)
  prod_date     date,
  setup_start   time,                   -- ตั้งเครื่อง เริ่ม
  run_start     time,                   -- เวลาปฏิบัติงาน เริ่ม
  run_end       time,                   --                 เสร็จ
  machine_code  text references public.rb_machines(code),
  good_kg       numeric,                -- ชิ้นงานดี (กก.)
  good_pieces   numeric,                -- ชิ้นงานดี (ท่อน)
  scrap_reason  text,
  scrap_kg      numeric,
  chk_hole_mm   numeric,                -- ตรวจสอบขนาด: รูใน
  chk_outer_mm  numeric,                --               วงนอก
  chk_width_mm  numeric,                --               กว้าง
  chk_thick_mm  numeric,                --               หนา
  chk_length_mm numeric,                --               ยาว
  operator      text,
  note          text,
  recorded_at   timestamptz not null default now(),
  unique (job_id, seq)
);

-- ---------------------------------------------------------------- ดัชนี

create index if not exists idx_rb_jobs_status  on public.rb_jobs(book_code, status);
create index if not exists idx_rb_jobs_wo      on public.rb_jobs(book_code, wo_src_row);
create index if not exists idx_rb_chem_job     on public.rb_chem_weighings(job_id);
create index if not exists idx_rb_mix_job      on public.rb_mixing_runs(job_id);
create index if not exists idx_rb_mix_date     on public.rb_mixing_runs(prod_date);
create index if not exists idx_rb_inj_job      on public.rb_injection_runs(job_id);
create index if not exists idx_rb_inj_date     on public.rb_injection_runs(prod_date);
create index if not exists idx_rb_oven_job     on public.rb_oven_runs(job_id);
create index if not exists idx_rb_hcm_job      on public.rb_hcm_runs(job_id);
create index if not exists idx_rb_hcm_date     on public.rb_hcm_runs(prod_date);
create index if not exists idx_rb_machines_unit on public.rb_machines(unit_code) where active;

-- ---------------------------------------------------------------- updated_at

create or replace function public.rb_touch_updated_at()
returns trigger as $$
begin
  new.updated_at = now();
  return new;
end;
$$ language plpgsql;

drop trigger if exists trg_rb_jobs_updated_at on public.rb_jobs;
create trigger trg_rb_jobs_updated_at
before update on public.rb_jobs
for each row execute function public.rb_touch_updated_at();

-- ---------------------------------------------------------------- วิวสรุป

-- ใบสั่งงานพร้อมข้อมูลจากบรรทัดใน Chronicle_Working และยอดผลิตสะสมของแต่ละหน่วย
create or replace view public.v_rb_job_board with (security_invoker = on) as
  select j.id, j.book_code, j.job_no, j.status, j.issued_at, j.issued_by, j.note,
         w.production_order_no, w.work_order_no, w.customer_name, w.fg_code,
         w.rb_code, w.rb_name, w.color, w.qty_kg, w.rb_strands,
         w.mixing_start, w.injection_due, w.hcm_due,
         (select count(*) from public.rb_chem_weighings c where c.job_id = j.id)     as chem_rows,
         (select coalesce(sum(good_kg),0) from public.rb_mixing_runs m
            where m.job_id = j.id)                                                   as mix_good_kg,
         (select coalesce(sum(good_kg),0) from public.rb_injection_runs i
            where i.job_id = j.id)                                                   as inj_good_kg,
         (select coalesce(sum(good_qty),0) from public.rb_oven_runs o
            where o.job_id = j.id)                                                   as oven_good_qty,
         (select coalesce(sum(good_kg),0) from public.rb_hcm_runs h
            where h.job_id = j.id)                                                   as hcm_good_kg,
         (select coalesce(sum(scrap_kg),0) from public.rb_mixing_runs m
            where m.job_id = j.id)
       + (select coalesce(sum(scrap_kg),0) from public.rb_injection_runs i
            where i.job_id = j.id)
       + (select coalesce(sum(scrap_kg),0) from public.rb_hcm_runs h
            where h.job_id = j.id)                                                   as scrap_kg_total
  from public.rb_jobs j
  left join public.rb_work_order_lines w
         on w.book_code = j.book_code and w.src_row = j.wo_src_row;

-- ---------------------------------------------------------------- RLS

alter table public.rb_employees        enable row level security;
alter table public.rb_units            enable row level security;
alter table public.rb_machines         enable row level security;
alter table public.rb_defect_reasons   enable row level security;
alter table public.rb_process_standards enable row level security;
alter table public.rb_jobs             enable row level security;
alter table public.rb_chem_weighings   enable row level security;
alter table public.rb_chem_color       enable row level security;
alter table public.rb_mixing_runs      enable row level security;
alter table public.rb_injection_runs   enable row level security;
alter table public.rb_oven_runs        enable row level security;
alter table public.rb_hcm_runs         enable row level security;


-- #############################################################################
-- ##  3. full_access.sql — สิทธิ์เต็มทุกตาราง
-- #############################################################################

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
