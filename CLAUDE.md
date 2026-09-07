# ระบบวางแผนและติดตามการผลิต

## บริบทธุรกิจ

- รูปแบบการผลิต: **MTO (ผลิตตามสั่ง)** — ใบสั่งผลิตเกิดจากใบสั่งขายเป็นหลัก
  `work_orders.source_sales_order_line_id` เป็น null ได้ (งานผลิตซ่อม/ทดลอง) แต่เส้นทางหลักคือมีค่า
- ระดับการสอบย้อนกลับ: **ระดับ lot** — ทุกธุรกรรมสต็อกของ item ที่ `is_lot_controlled = true`
  ต้องมี `lot_no` โครงสร้างเผื่อ `serial_no` ไว้แล้วแต่ยังไม่บังคับใช้ในเฟสนี้
- กระแสเอกสาร: ใบสั่งขาย → วางแผนความต้องการ → ใบสั่งผลิต → เบิกวัตถุดิบ →
  บันทึกผลรายขั้นตอน → รับเข้าคลัง → ปิดงานและคิดต้นทุน
- ผู้ใช้หลัก: ฝ่ายขาย, ฝ่ายวางแผน, หัวหน้ากะ, พนักงานหน้างาน, ฝ่ายบัญชีต้นทุน

## Stack

- Backend: **Django 5 + Django REST Framework (Python 3.11+)**
- Database: **PostgreSQL 16**
- ORM/Query: **Django ORM** (ใช้ raw SQL ได้เฉพาะใน view/materialized view และฟังก์ชันสรุปยอด)
- Frontend: **React + TypeScript (Vite)**
- ภาษา UI: **ไทย** (ชื่อฟิลด์ในโค้ดและฐานข้อมูลเป็นภาษาอังกฤษเสมอ)

## กฎที่ห้ามละเมิด (INVARIANTS)

ถ้างานที่ได้รับมอบหมายทำให้ต้องละเมิดข้อใดข้อหนึ่ง ให้หยุดและถามก่อน ห้ามหาทางเลี่ยง

1. **ห้ามลบข้อมูลเอกสารถาวร** ไม่มี hard delete ในตารางเอกสารทุกตาราง
   การยกเลิกทำโดยเปลี่ยน status เป็น `cancelled` พร้อมบันทึก `cancelled_by`,
   `cancelled_at`, `cancel_reason`
2. **ใบสั่งผลิตต้องคัดลอก BOM และ Routing มาเก็บในตัวเอง**
   ห้าม join ไปหา `bom_line` หรือ `routing_operation` เพื่อคำนวณอะไรก็ตามของ
   ใบสั่งผลิตที่ออกไปแล้ว ใช้ `work_order_material` และ `work_order_operation`
   ซึ่งเป็นสำเนา ณ เวลาที่ออกใบเท่านั้น
3. **ยอดสต็อกต้องคำนวณจาก `stock_transaction` เสมอ**
   ห้ามมีคอลัมน์ `qty_on_hand` ที่เขียนทับได้ ถ้าต้องการความเร็ว ให้ใช้
   materialized view หรือตารางสรุปที่สร้างจาก transaction เท่านั้น และต้อง
   สร้างใหม่ได้จากศูนย์เสมอ
4. **จำนวนทุกค่าต้องมาคู่กับหน่วยนับ** ทุกฟิลด์ที่เป็นจำนวนต้องมี `uom_id` กำกับ
   การแปลงหน่วยผ่าน `uom_conversion` เท่านั้น ห้ามฝังตัวคูณไว้ในโค้ด
5. **ห้ามใช้ float กับจำนวนและเงิน** ใช้ `numeric`/`decimal` เท่านั้น
   จำนวน 4 ตำแหน่งทศนิยม เงิน 4 ตำแหน่งทศนิยม ปัดเศษเฉพาะตอนแสดงผล
6. **ทุกตารางต้องมี audit fields** `created_at`, `created_by`, `updated_at`,
   `updated_by` และเอกสารต้องมีประวัติการเปลี่ยนสถานะแยกตาราง
7. **การเปลี่ยนสถานะต้องผ่าน state machine ที่ประกาศไว้ที่เดียว**
   ห้าม `UPDATE ... SET status = ...` กระจายอยู่ตาม service ต่างๆ
8. **การบันทึกผลหน้างานต้องเป็น idempotent** ทุก request ต้องมี `client_ref`
   (uuid ที่เครื่องปลายทางสร้าง) ส่งซ้ำด้วย `client_ref` เดิมต้องไม่สร้าง
   ธุรกรรมซ้ำ เพราะหน้างานต้องรองรับ offline แล้ว sync ทีหลัง
9. **BOM มีวันเริ่มและวันสิ้นสุดผล** การค้นหา BOM ต้องระบุวันที่เสมอ
   ห้ามเขียนฟังก์ชันที่ดึง "BOM ปัจจุบัน" โดยไม่รับพารามิเตอร์วันที่
10. **ทุกฟังก์ชันที่แตะสต็อกหรือสถานะเอกสารต้องอยู่ใน transaction เดียว**
    และล็อกแถวที่เกี่ยวข้องเพื่อกันการเบิกเกินจากการยิงพร้อมกัน

## ข้อตกลงการตั้งชื่อ

- ตารางเป็น snake_case พหูพจน์: `work_orders`, `stock_transactions`
- เอกสารทุกใบใช้รูปแบบ header/line: `sales_orders` + `sales_order_lines`
- คีย์นอกลงท้ายด้วย `_id`, จำนวนขึ้นต้นด้วย `qty_`, เงินขึ้นต้นด้วย `amount_`
- เลขที่เอกสารมาจากตาราง `document_sequences` เท่านั้น ห้ามใช้ id ของแถวเป็นเลขที่เอกสาร

## แนวทางทำงานกับ Claude

- ก่อนแก้ schema ให้เสนอ migration และรอการยืนยันก่อนเสมอ
- งานที่แตะสต็อกหรือต้นทุน ต้องเขียนเทสต์ก่อนเขียน implementation
- อย่าสร้างไฟล์ใหม่ถ้าแก้ไฟล์เดิมได้
- อย่าเพิ่ม dependency ใหม่โดยไม่ถาม

---

# วิธีบังคับใช้ INVARIANTS บน stack นี้

ส่วนนี้แปลกฎข้างบนเป็นกลไกจริงของ Django ไม่ใช่กฎใหม่ ถ้าขัดกับกฎข้างบน กฎข้างบนชนะ

| ข้อ | กลไกที่ต้องใช้ | สิ่งที่ห้ามเห็นใน diff |
|---|---|---|
| 1 | `DocumentModel.delete()` ต้อง `raise NotImplementedError` และใช้ `cancel(user, reason)` แทน | `.delete()`, `on_delete=CASCADE` บนตารางเอกสาร, `--fake` migration ที่ลบแถว |
| 2 | `WorkOrderMaterial` / `WorkOrderOperation` เป็น FK ไป `work_order` เท่านั้น ไม่มี FK ไป `bom_line` (เก็บได้แค่ `source_bom_line_id` แบบไม่มี FK constraint ไว้อ้างอิงย้อนหลัง) | `work_order.item.bom_set`, การ join `bom_lines` ในโค้ดที่คำนวณความต้องการของ WO |
| 3 | ยอดคงเหลืออยู่ใน view `stock_balances` (item × location × lot) สร้างจาก `stock_transactions` เท่านั้น | field ชื่อ `qty_on_hand` / `qty_available` / `balance` ที่เขียนได้บน model |
| 4 | ทุกฟิลด์ `qty_*` ต้องมี `uom` FK คู่กันในตารางเดียวกัน แปลงหน่วยผ่าน `uom.convert(qty, from_uom, to_uom)` | ตัวเลขคูณลอย ๆ ในโค้ด, `qty` ที่ไม่มี `uom_id` ในตารางเดียวกัน |
| 5 | `DecimalField(max_digits=18, decimal_places=4)` เท่านั้น | `FloatField`, `float(...)`, `round(...)` นอกชั้นแสดงผล |
| 6 | สืบทอด `AuditedModel` ทุกตาราง + ตาราง `*_status_history` สำหรับเอกสาร | ตารางใหม่ที่ไม่ได้สืบทอด `AuditedModel` |
| 7 | ประกาศ transition ที่เดียวใน `apps/common/state_machine.py` แล้วเรียก `transition(doc, to_status, user)` | `obj.status = "..."` ตามด้วย `save()` นอก state machine |
| 8 | `client_ref = UUIDField(unique=True)` + `get_or_create` ใน `transaction.atomic()` | endpoint ที่รับผลหน้างานแต่ไม่มี `client_ref` |
| 9 | `resolve_bom(item, as_of_date)` — พารามิเตอร์วันที่ไม่มี default | ฟังก์ชันชื่อ `get_current_bom(item)` หรือ `as_of_date=None` |
| 10 | `transaction.atomic()` + `select_for_update()` บนแถว item/location ที่จะแตะ | service ที่แตะสต็อกแล้วไม่มี `atomic` หรือไม่มี `select_for_update` |

**เรื่อง `select_for_update` กับ view**: `stock_balances` เป็น view ล็อกไม่ได้
ให้ล็อกที่ตารางจริง — ล็อกแถว `items` (หรือ `item_locations` ถ้าเฟส 3 สร้างขึ้น)
ที่เป็นเจ้าของยอดนั้นก่อนอ่านยอดคงเหลือเสมอ ลำดับการล็อกต้องเรียงตาม `item_id`
เสมอเพื่อกัน deadlock

## โครงสร้างโปรเจกต์ที่ต้องยึด

เฟส 0 เป็นคนสร้างจริง เฟสหลังห้ามคิดโครงใหม่

```
backend/
  manage.py
  pyproject.toml
  config/                 settings/ (base, dev, prod), urls, asgi, wsgi
  apps/
    common/               AuditedModel, DecimalField helpers, state_machine.py,
                          document_sequences, uom conversion
    masterdata/           uoms, items, warehouses, locations, work_centers
    bom/                  bom_headers/lines, routing_headers/operations, explode_bom
    sales/                sales_orders, sales_order_lines
    production/           work_orders, work_order_materials/operations, shop floor
    inventory/            stock_transactions, post_transaction, stock_balances view
    costing/              actual cost roll-up, variance, reports
  tests/                  integration/scenario tests (ข้ามแอป)
frontend/
  src/
    api/                  generated client
    pages/                หน้าจอตามบทบาท
    shopfloor/            หน้าแท็บเล็ต + คิว IndexedDB
docs/
  schema.md               ER diagram (mermaid) — อัปเดตทุกเฟส
  phases/                 prompt ของแต่ละเฟส
  decisions/              ADR
```

## ข้อตกลงเพิ่มเติมของ Django

- หนึ่งแอปหนึ่ง `services.py` — business logic อยู่ที่นั่น ไม่อยู่ใน view/serializer/model
- ห้าม signal (`post_save`, `pre_delete`) กับงานที่แตะสต็อกหรือสถานะ
  เพราะซ่อนลำดับการทำงานและทำให้ทดสอบ concurrency ไม่ได้
- ห้ามใช้ `auto_now` / `auto_now_add` กับฟิลด์ที่เป็น "เวลาที่เกิดธุรกรรมจริง"
  (`posted_at`, `started_at`, `finished_at`) เพราะหน้างานออฟไลน์ส่งย้อนหลัง
  `created_at` ใช้ `auto_now_add` ได้ เพราะหมายถึงเวลาที่ระบบรับข้อมูล
- migration ทุกไฟล์ต้องตั้งชื่อสื่อความ (`0003_stock_transactions.py` ไม่ใช่ `0003_auto_...`)
- constraint ที่สำคัญต้องอยู่ในฐานข้อมูล (`CheckConstraint`, `UniqueConstraint`)
  ไม่ใช่แค่ `clean()` เพราะ `clean()` ไม่ทำงานตอน `bulk_create` หรือ raw SQL

## เทสต์

- `pytest` + `pytest-django` รันบน PostgreSQL จริงเท่านั้น ห้าม SQLite
  เพราะ `select_for_update` และ `numeric` ทำงานไม่เหมือนกัน
- เทสต์ concurrency ใช้ thread จริงกับ connection แยก ไม่ใช่ mock
- ทุกงานที่แตะสต็อกหรือต้นทุน ต้องมีเทสต์เส้นทางที่ **ต้องล้มเหลว** ด้วยเสมอ
  (เบิกเกินสต็อก, แก้เอกสารที่ปิดแล้ว, ยิงซ้ำ, transition ที่ไม่อนุญาต)

## ลำดับการพัฒนา

รันทีละเฟส ตรวจให้ผ่านก่อนขึ้นเฟสถัดไป prompt อยู่ใน `docs/phases/`

สถานะปัจจุบัน: **เฟส 0-5 เสร็จแล้ว** — backend ครบ, API ครบ, หน้าจอหน้างานพร้อมโหมด
ออฟไลน์, เทสต์ 59 ตัวเขียวบน PostgreSQL จริง งานต่อจากนี้กลับไปทำทีละเรื่องตามปกติ
และรัน `/check-invariants` กับ `/pre-merge-review` ก่อน merge ทุกครั้ง

## คำสั่งที่ใช้บ่อย

```bash
make setup           # สร้าง venv + ติดตั้ง dependency
make migrate seed    # เตรียมฐานข้อมูลและข้อมูลตัวอย่าง
make run             # backend ที่ http://127.0.0.1:8000
make front-dev       # หน้าจอหน้างานที่ http://127.0.0.1:5173
make test            # เทสต์ทั้งหมด (ต้องมี PostgreSQL จริง)
make lint            # django check + ตรวจ migration ค้าง
```

## สิ่งที่ต้องรู้ก่อนแก้โค้ด

- **ยอดคงเหลืออยู่ในวิว `stock_balances`** ล็อกไม่ได้ ต้องล็อกแถว `items`
  เรียงตาม `item_id` ก่อนอ่านเสมอ (`inventory.services.lock_items`)
- **ทุกการเขียนสต็อกผ่าน `inventory.services.post_transactions` เท่านั้น**
  ห้ามสร้าง `StockTransaction` ตรง
- **ทุกการเปลี่ยนสถานะผ่าน `common.state_machine.transition` เท่านั้น**
  เงื่อนไขก่อนเปลี่ยน (เช่น ต้องคืนของก่อนยกเลิก) อยู่ใน `PRECONDITIONS`
  ของไฟล์นั้น ไม่ใช่ใน service เพื่อกันการเรียกลัด
- **`report_shop_floor` ตรวจ `client_ref` สองรอบ** รอบแรกเป็นทางลัด
  รอบสองอยู่หลังล็อกแถวใบสั่งผลิต — รอบสองคือรอบที่กัน race จริง
- โครงสร้างฐานข้อมูลและ constraint ทั้งหมดอยู่ใน `docs/schema.md`
