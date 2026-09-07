# เฟส 2 — ใบสั่งขายและใบสั่งผลิต

```
งาน: ใบสั่งขาย และการออกใบสั่งผลิตจากใบสั่งขาย

sales_orders / sales_order_lines: customer, qty_ordered, qty_delivered, due_date, status
work_orders: wo_no, item_id, qty_planned, qty_completed, qty_scrapped,
             due_date, status, source_sales_order_line_id (null ได้)

จุดสำคัญที่สุดของเฟสนี้:
ตอนสร้าง work_order ต้อง snapshot BOM และ Routing ลง work_order_materials
และ work_order_operations ทันที หลังจากนั้นการแก้ BOM ต้นฉบับต้องไม่กระทบ
ใบสั่งผลิตที่ออกไปแล้ว

State machine ของ work_order:
draft -> approved -> released -> in_progress -> completed -> closed
โดยยกเลิกได้จาก draft/approved/released เท่านั้น
released ขึ้นไปห้ามแก้ qty_planned

เขียนเทสต์ที่พิสูจน์ว่า: สร้าง WO -> แก้ BOM ต้นฉบับ -> WO เดิมยังใช้สูตรเดิม
```

## snapshot ต้องคัดลอกอะไรบ้าง

"snapshot" ที่ไม่ครบคือช่องโหว่ที่พบบ่อยที่สุดของ INVARIANT ข้อ 2
`work_order_materials` ต้องยืนอยู่ได้เองแม้ BOM ต้นฉบับถูกลบทั้งฉบับ ดังนั้นต้องเก็บ:

- `qty_per`, `uom_id`, `scrap_pct` — ค่าจริง ณ วันที่ออกใบ ไม่ใช่ FK ไปอ่านทีหลัง
- `qty_required` — คำนวณจาก `qty_planned` แล้วเก็บไว้เลย
- `component_item_id` — FK ไป `items` ได้ (ข้อมูลหลักไม่ใช่เอกสาร)
- `source_bom_header_id`, `source_bom_line_id`, `bom_revision` —
  **เก็บเป็นตัวเลขธรรมดา ไม่มี FK constraint** ไว้สอบย้อนกลับว่ามาจากสูตรไหน
  ถ้าตั้งเป็น FK จริง จะมีคนเผลอ join กลับไปอ่านค่าปัจจุบันในภายหลัง

`work_order_operations` เหมือนกัน: `setup_minutes`, `run_minutes_per_unit`,
`work_center_id`, `sequence` คัดลอกมาทั้งหมด

**ต้องมีเทสต์ที่ลบ `bom_headers` ทิ้งทั้งฉบับ แล้วยืนยันว่า WO เดิมยังคำนวณต้นทุนได้**
เทสต์ที่แค่ "แก้ qty_per แล้วเช็คว่า WO ไม่เปลี่ยน" ยังจับ FK ที่หลุดไม่ได้ทุกกรณี

## state machine

ประกาศที่ `apps/common/state_machine.py` ที่เดียว (INVARIANT ข้อ 7)

```
draft ──→ approved ──→ released ──→ in_progress ──→ completed ──→ closed
  │          │            │
  └──────────┴────────────┴──→ cancelled
```

- `cancelled` จาก `released` ต้องคืนวัตถุดิบที่เบิกไปแล้วเข้าคลัง
  **เฟสนี้ยังไม่มีธุรกรรมสต็อก** — ให้ block transition นี้ไว้ก่อนด้วย error ที่ชัดเจน
  แล้วเปิดใช้ในเฟส 3 พร้อมเทสต์คืนของ อย่าปล่อยผ่านเงียบ ๆ
- `released` ขึ้นไปห้ามแก้ `qty_planned` → บังคับที่ service layer **และ**
  `CheckConstraint` หรือ trigger ระดับ DB ไม่ใช่แค่ `clean()`
- `qty_completed` / `qty_scrapped` เฟสนี้ยังไม่มีใครเขียน
  เฟส 4 เป็นคนเขียน และต้องเขียนผ่าน service เท่านั้น

## ความสัมพันธ์กับใบสั่งขาย (MTO)

- `sales_order_lines.qty_delivered` **ห้ามเป็นคอลัมน์ที่เขียนทับได้แบบอิสระ**
  ต้องคำนวณจากธุรกรรม `delivery` ในเฟส 3 หรือถ้าเก็บไว้เพื่อความเร็ว
  ต้องสร้างใหม่จาก `stock_transactions` ได้เสมอ (เจตนารมณ์ของ INVARIANT ข้อ 3)
- ปิด SO line ได้เมื่อ WO ที่ผูกอยู่ปิดหมดแล้วเท่านั้น
- หนึ่ง SO line ออกได้หลาย WO (ผลิตแบ่งล็อต) — ความสัมพันธ์เป็น 1:N ไม่ใช่ 1:1
