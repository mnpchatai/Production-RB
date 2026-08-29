# Production RB Supabase Setup

This folder contains the database schema and a lightweight JS adapter for migrating the app from localStorage to a multi-user backend.

> **`rb_planning/`** is a separate, self-contained migration: it moves the real
> Excel workbooks (`ระบบวางแผนการสั่งงานแผนก RB V1.7.1`) into Supabase — its own
> schema, an ETL script, and two ways to load the data. See
> [`rb_planning/README.md`](rb_planning/README.md). The schema here is for the
> demo app in `index.html` and is unrelated to those tables.

## 1) Create Supabase project
- Create a new project at https://supabase.com
- Get project URL and anon key
- Replace the placeholders in `supabase.js`

## 2) Run schema
Open Supabase SQL editor and paste the contents of `schema.sql`.

## 3) Install dependency
```bash
npm install @supabase/supabase-js
```

## 4) Replace localStorage logic in the app
In `index.html`, find the functions that load and save database data:
- `loadDB()`
- `saveDB()`
- `initialSeed()` or equivalent data bootstrap logic

Then replace them with Supabase calls like:

```js
const { data, error } = await supabase.from('items').select('*');
```

## 5) Recommended next step
Create a small adapter object that maps the existing app data model to the table structure.

Example:
```js
const DB = {
  items: await loadFromSupabase('items'),
  machines: await loadFromSupabase('machines'),
  orders: await loadFromSupabase('orders'),
  txns: await loadFromSupabase('inventory_txns'),
  pos: await loadFromSupabase('purchase_orders'),
  settings: await getSettings()
};
```

## Notes
- This setup keeps the static frontend model intact.
- The app still behaves like a single-page JS dashboard.
- Data is now shared across users and devices through Supabase.
