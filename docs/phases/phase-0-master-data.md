# เฟส 0 — วางโครงและ schema เปล่า

```
อ่าน CLAUDE.md ก่อน

งาน: วางโครงโปรเจกต์และ migration ชุดแรกสำหรับข้อมูลหลักเท่านั้น
ยังไม่ต้องทำเอกสารใดๆ

ต้องมี:
- uoms, uom_conversions
- items (มี item_type: FG/SFG/RM/PKG, uom_id หลัก, is_lot_controlled, is_serial_controlled)
- warehouses, locations
- work_centers
- document_sequences
- users, roles

สิ่งที่ต้องส่งมอบ:
1. ไฟล์ migration
2. ER diagram แบบ mermaid ในไฟล์ docs/schema.md
3. seed data ชุดเล็กสำหรับทดสอบ (5 items, 2 warehouses, 3 work centers)

อย่าเพิ่งเขียน API หรือ UI
```

## รายละเอียดที่ต้องได้ในเฟสนี้ (อย่าปล่อยไว้ให้เฟสหลัง)

เฟส 0 เป็นเฟสที่แก้ย้อนหลังแพงที่สุด เพราะทุกตารางหลังจากนี้อ้างถึงมันหมด

- **`apps/common` ต้องเสร็จก่อนตารางอื่น** — `AuditedModel`, ตัวช่วย `DecimalField`
  (18,4), โครง `state_machine.py` (ยังไม่มี transition ก็ได้ แต่ต้องมีที่ทางแล้ว)
- **`uom_conversions`** ต้องเป็นคู่ `(from_uom, to_uom, factor)` ที่มี unique constraint
  และมีฟังก์ชัน `convert(qty, from_uom, to_uom)` ที่หาเส้นทางแปลงข้ามหน่วยได้
  ถ้าแปลงไม่ได้ต้อง raise ไม่ใช่คืน qty เดิมเงียบ ๆ
- **`items.allow_negative`** ต้องมีตั้งแต่เฟสนี้ (default `false`) เฟส 3 ใช้
- **`document_sequences`** ต้องจองเลขได้แบบทนการยิงพร้อมกัน
  ใช้ `select_for_update()` บนแถว sequence ไม่ใช่ `MAX(no)+1`
  เก็บ `doc_type`, `prefix`, `period` (ถ้ารีเซ็ตรายปี/รายเดือน), `next_number`, `padding`
- **`locations`** ต้องผูกกับ `warehouse` และมี `location_type`
  อย่างน้อยต้องมีชนิดที่ใช้กับเฟส 3-4: stock, wip, scrap, in_transit
- **users, roles** ใช้ `AUTH_USER_MODEL` ที่ custom ตั้งแต่ migration แรก
  ย้ายทีหลังเจ็บมาก แม้ตอนนี้จะยังไม่มีฟิลด์เพิ่มก็ตาม
- seed data วางไว้ที่ `backend/apps/masterdata/fixtures/` หรือ management command
  ต้องรันซ้ำได้โดยไม่พัง (idempotent)

## เทสต์ที่ต้องมีก่อนปิดเฟส

- แปลงหน่วยข้ามขั้น (กก. → กรัม → มก.) ได้ค่าถูกต้อง
- แปลงหน่วยที่ไม่มีเส้นทาง → raise
- จองเลขเอกสารจาก 10 thread พร้อมกัน → ได้เลขไม่ซ้ำ 10 เลข ไม่มีช่องว่าง
- `AuditedModel` บันทึก `created_by` / `updated_by` ครบ
