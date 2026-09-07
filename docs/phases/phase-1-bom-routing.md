# เฟส 1 — BOM และ Routing

```
งาน: เพิ่ม BOM หลายระดับ และ Routing

ข้อกำหนด:
- bom_headers: item_id, revision, effective_from, effective_to, status
- bom_lines: component_item_id, qty_per, uom_id, scrap_pct, sequence, alternate_of_line_id
- routing_headers + routing_operations: work_center_id, sequence, setup_minutes, run_minutes_per_unit

ต้องมีฟังก์ชัน explode_bom(item_id, qty, as_of_date) ที่:
- คืนความต้องการวัตถุดิบทุกระดับ พร้อมระดับชั้น (level)
- คิด scrap_pct สะสมตามระดับ
- ตรวจจับ circular reference แล้ว throw error ที่บอกว่าวนที่ item ไหน
- เคารพ effective date ตาม as_of_date

เขียนเทสต์ก่อน อย่างน้อย: BOM 3 ระดับ, กรณีวนซ้ำ, กรณี BOM หมดอายุ,
กรณีมี scrap ทุกระดับ, กรณีหน่วยนับต่างกันระหว่างระดับ
```

## จุดที่ต้องตัดสินใจให้ชัดในเฟสนี้

ทั้งสามข้อนี้ถ้าปล่อยคลุมเครือ ต้นทุนในเฟส 5 จะเพี้ยนแบบหาสาเหตุยาก
เลือกแล้วเขียน ADR

1. **`scrap_pct` สะสมยังไง** — สูตรที่ใช้ต้องเขียนไว้ใน docstring ชัดเจน
   ระบบนี้ใช้ `qty_required = qty_parent / (1 - scrap_pct)` (คิดแบบ "ต้องเบิกเผื่อเสีย")
   ไม่ใช่ `qty_parent * (1 + scrap_pct)` สองสูตรนี้ให้ผลต่างกัน และต่างมากขึ้นเมื่อสะสมหลายระดับ
   ถ้าจะเปลี่ยนต้องเปลี่ยนพร้อม ADR
2. **`effective_to` เป็น inclusive หรือ exclusive** — ระบบนี้ใช้
   `effective_from <= as_of_date < effective_to` (`effective_to` เป็น null = ยังไม่หมดอายุ)
   และต้องมี exclusion constraint กัน BOM ของ item เดียวกันมีช่วงเวลาทับกัน
3. **`alternate_of_line_id` ถูกกินเข้า explode ไหม** — ไม่
   `explode_bom` คืนเฉพาะบรรทัดหลัก และแนบรายการ alternate มาด้วยแยกฟิลด์
   คนวางแผนเป็นคนเลือกตอนออกใบสั่งผลิต ไม่ใช่ระบบเลือกให้

## ข้อกำหนดเพิ่มของ `explode_bom`

- ลายเซ็น: `explode_bom(item_id, qty, as_of_date, *, uom=None) -> list[BomRequirement]`
  `as_of_date` **ไม่มี default** (INVARIANT ข้อ 9)
- แต่ละแถวคืน: `level`, `item_id`, `qty_required`, `uom_id`, `path` (list ของ item_id
  จากรากลงมา) — `path` จำเป็นตอน debug ว่าความต้องการก้อนนี้มาจากสาขาไหน
- circular reference: error message ต้องมี `path` เต็มถึงจุดที่วน
  ไม่ใช่แค่ "circular reference detected"
- ลึกเกิน 20 ระดับให้ raise ด้วย ถือว่าข้อมูลผิด ไม่ใช่ BOM จริง
- **ห้ามคิวรีในลูป** BOM 3 ระดับ 200 บรรทัดต้องไม่ยิง 200 query
  ดึงทีละชั้นแล้ว group เอา — เฟส 4 เรียกฟังก์ชันนี้ทุกครั้งที่บันทึกผลหน้างาน
