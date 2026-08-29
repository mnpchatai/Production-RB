-- Production RB: Supabase PostgreSQL schema
-- Purpose: replace localStorage with a shared multi-user database

create extension if not exists pgcrypto;

create table if not exists public.users (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  email text unique,
  role text not null default 'viewer',
  is_active boolean not null default true,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.customers (
  id uuid primary key default gen_random_uuid(),
  code text unique not null,
  name text not null,
  contact text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.vendors (
  id uuid primary key default gen_random_uuid(),
  code text unique not null,
  name text not null,
  contact text,
  phone text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.items (
  id uuid primary key default gen_random_uuid(),
  code text unique not null,
  name text not null,
  item_type text not null default 'FG',
  unit text not null default 'pcs',
  rate numeric not null default 0,
  stock_min numeric not null default 0,
  stock_max numeric not null default 0,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.boms (
  id uuid primary key default gen_random_uuid(),
  parent_item_code text not null references public.items(code),
  child_item_code text not null references public.items(code),
  qty numeric not null default 1,
  scrap_rate numeric not null default 0,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique(parent_item_code, child_item_code)
);

create table if not exists public.machines (
  id uuid primary key default gen_random_uuid(),
  code text unique not null,
  name text not null,
  dept text not null,
  status text not null default 'IDLE',
  rate numeric not null default 0,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.orders (
  id uuid primary key default gen_random_uuid(),
  order_code text unique not null,
  item_code text not null references public.items(code),
  customer_id uuid references public.customers(id),
  dept text not null,
  machine_code text references public.machines(code),
  qty numeric not null default 0,
  produced numeric not null default 0,
  scrap numeric not null default 0,
  status text not null default 'PLANNED',
  priority text not null default 'NORMAL',
  start_date date,
  due_date date,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.order_logs (
  id uuid primary key default gen_random_uuid(),
  order_id uuid not null references public.orders(id) on delete cascade,
  log_type text not null,
  good_qty numeric not null default 0,
  scrap_qty numeric not null default 0,
  reason text,
  note text,
  created_by uuid references public.users(id),
  created_at timestamptz not null default now()
);

create table if not exists public.inventory_txns (
  id uuid primary key default gen_random_uuid(),
  item_code text not null references public.items(code),
  txn_type text not null,
  qty numeric not null,
  ref_type text,
  ref_id text,
  created_by uuid references public.users(id),
  created_at timestamptz not null default now()
);

create table if not exists public.purchase_orders (
  id uuid primary key default gen_random_uuid(),
  po_code text unique not null,
  vendor_id uuid not null references public.vendors(id),
  status text not null default 'ORDERED',
  eta date,
  total_amount numeric not null default 0,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.po_lines (
  id uuid primary key default gen_random_uuid(),
  po_id uuid not null references public.purchase_orders(id) on delete cascade,
  item_code text not null references public.items(code),
  qty numeric not null default 0,
  received_qty numeric not null default 0,
  unit_price numeric not null default 0,
  eta date,
  created_at timestamptz not null default now()
);

create table if not exists public.settings (
  id uuid primary key default gen_random_uuid(),
  key text unique not null,
  value jsonb not null,
  updated_at timestamptz not null default now()
);

create table if not exists public.mrp_runs (
  id uuid primary key default gen_random_uuid(),
  run_date date not null,
  item_code text not null references public.items(code),
  plan_qty numeric not null default 0,
  source text not null default 'manual',
  created_by uuid references public.users(id),
  created_at timestamptz not null default now()
);

create index if not exists idx_orders_status on public.orders(status);
create index if not exists idx_orders_due_date on public.orders(due_date);
create index if not exists idx_inventory_txns_item on public.inventory_txns(item_code, created_at desc);
create index if not exists idx_po_lines_item on public.po_lines(item_code);
create index if not exists idx_boms_parent on public.boms(parent_item_code);
create index if not exists idx_settings_key on public.settings(key);

create or replace function public.update_updated_at()
returns trigger as $$
begin
  new.updated_at = now();
  return new;
end;
$$ language plpgsql;

create trigger trg_users_updated_at
before update on public.users
for each row execute function public.update_updated_at();

create trigger trg_customers_updated_at
before update on public.customers
for each row execute function public.update_updated_at();

create trigger trg_vendors_updated_at
before update on public.vendors
for each row execute function public.update_updated_at();

create trigger trg_items_updated_at
before update on public.items
for each row execute function public.update_updated_at();

create trigger trg_boms_updated_at
before update on public.boms
for each row execute function public.update_updated_at();

create trigger trg_machines_updated_at
before update on public.machines
for each row execute function public.update_updated_at();

create trigger trg_orders_updated_at
before update on public.orders
for each row execute function public.update_updated_at();

create trigger trg_purchase_orders_updated_at
before update on public.purchase_orders
for each row execute function public.update_updated_at();

create trigger trg_settings_updated_at
before update on public.settings
for each row execute function public.update_updated_at();

-- Optional: basic RLS policy skeleton
-- Enable RLS for tables that should enforce access control.

alter table public.users enable row level security;
alter table public.customers enable row level security;
alter table public.vendors enable row level security;
alter table public.items enable row level security;
alter table public.boms enable row level security;
alter table public.machines enable row level security;
alter table public.orders enable row level security;
alter table public.order_logs enable row level security;
alter table public.inventory_txns enable row level security;
alter table public.purchase_orders enable row level security;
alter table public.po_lines enable row level security;
alter table public.settings enable row level security;

-- Example policy: allow authenticated users to read all tables
-- create policy "read_all" on public.items for select using (auth.role() = 'authenticated');
-- create policy "write_all" on public.items for all using (auth.role() = 'authenticated');

-- Example seed data for settings
insert into public.settings(key, value)
values
  ('app_name', '{"value":"Production RB"}'),
  ('currency', '{"value":"THB"}'),
  ('default_password', '{"value":"rubber2026"}')
on conflict (key) do nothing;
