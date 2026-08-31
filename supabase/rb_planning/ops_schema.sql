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
