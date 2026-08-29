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
create or replace view public.v_rb_item_standards_all as
  select s.*, b.name as book_name from public.rb_item_standards s
  join public.rb_books b on b.code = s.book_code;

create or replace view public.v_rb_bom_all as
  select l.*, b.name as book_name from public.rb_bom_lines l
  join public.rb_books b on b.code = l.book_code;

create or replace view public.v_rb_work_orders_all as
  select w.*, b.name as book_name from public.rb_work_order_lines w
  join public.rb_books b on b.code = w.book_code;

-- สรุปใบสั่งผลิต 1 แถวต่อ 1 ใบ (ชีตต้นทางเก็บเป็นรายบรรทัดอะไหล่)
create or replace view public.v_rb_production_orders as
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
create or replace view public.v_rb_bom_with_standard as
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
create or replace view public.v_rb_missing_standards as
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
