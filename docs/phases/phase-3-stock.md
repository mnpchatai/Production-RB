# เฟส 3 — ธุรกรรมสต็อก

เฟสนี้เป็นแกนกลาง ผิดตรงนี้กู้คืนยากที่สุดในระบบ ให้เวลากับมันมากที่สุด

```
งาน: ระบบธุรกรรมสต็อก เป็นแกนกลางของทั้งระบบ

stock_transactions:
  txn_no, txn_type, doc_type, doc_no, doc_line_id,
  item_id, lot_no, serial_no,
  from_location_id, to_location_id, qty, uom_id,
  unit_cost, total_cost, posted_at, posted_by, client_ref

txn_type อย่างน้อย: receipt, issue_to_wo, return_from_wo, wo_output,
                    transfer, adjustment, delivery, scrap

ข้อกำหนด:
- ห้ามมีคอลัมน์ยอดคงเหลือที่แก้ได้ ให้สร้าง view สำหรับยอดคงเหลือแทน
- unique constraint บน client_ref เพื่อ idempotency
- ฟังก์ชัน post_transaction ต้องอยู่ใน db transaction เดียว
  และ lock แถวสต็อกที่เกี่ยวข้อง
- ห้ามยอดติดลบสำหรับสินค้าที่ตั้งค่า allow_negative = false

เขียนเทสต์: ยิง post ซ้ำด้วย client_ref เดิม 10 ครั้งพร้อมกัน
ต้องได้ธุรกรรมเดียวและยอดสต็อกถูกต้อง
```

## เรื่องที่ต้องทำให้ถูกตั้งแต่ครั้งแรก

### ล็อกอะไร

`stock_balances` เป็น view — `select_for_update()` บน view ใช้ไม่ได้
ให้ล็อกที่ตารางจริงที่เป็นเจ้าของยอด แล้วค่อยอ่านยอดจาก view ในล็อกเดียวกัน

```
with transaction.atomic():
    # ล็อกเรียงตาม item_id เสมอ เพื่อกัน deadlock ตอนธุรกรรมหลายบรรทัด
    Item.objects.select_for_update().filter(id__in=sorted(item_ids))
    # อ่านยอดหลังล็อก แล้วค่อยตรวจว่าติดลบไหม
```

ลำดับการล็อกต้องเรียงตาม `item_id` ทุกที่ ถ้าโค้ดคนละจุดล็อกคนละลำดับ
ระบบจะ deadlock ตอนมีคนใช้พร้อมกันจริง และจะไม่โผล่ในเทสต์ที่รันทีละอัน

### idempotency ที่ทนการยิงพร้อมกัน

`unique constraint` บน `client_ref` อย่างเดียวไม่พอ — โค้ดต้องรับมือกับ
`IntegrityError` ให้ถูก:

```
try:
    with transaction.atomic():
        txn = StockTransaction.objects.create(client_ref=..., ...)
except IntegrityError:
    txn = StockTransaction.objects.get(client_ref=...)   # คนอื่นสร้างไปแล้ว
```

ตรวจก่อนด้วย `SELECT` แล้วค่อย `INSERT` ไม่พอ เพราะสองคำสั่งไม่ atomic
และ **ต้องมี `transaction.atomic()` ซ้อนใน `try`** ไม่งั้น `IntegrityError`
จะทำให้ transaction ชั้นนอกพังทั้งอัน

`client_ref` ครอบคลุม "หนึ่งการกระทำของผู้ใช้" ซึ่งอาจสร้างหลายธุรกรรม
(เช่น backflush ตัดวัตถุดิบ 5 ตัว) — ออกแบบให้ `client_ref` อยู่บนตาราง
"กลุ่มธุรกรรม" หรือใช้ `(client_ref, line_seq)` เป็น unique key
อย่าให้หนึ่ง `client_ref` สร้างได้แค่ธุรกรรมเดียวแล้วติดขัดตอนเฟส 4

### ทิศทางของ qty

`qty` เก็บเป็นค่าบวกเสมอ ทิศทางมาจาก `from_location_id` / `to_location_id`

| txn_type | from | to |
|---|---|---|
| receipt | – | คลังรับ |
| issue_to_wo | คลัง | wip |
| return_from_wo | wip | คลัง |
| wo_output | wip | คลัง |
| transfer | คลัง A | คลัง B |
| adjustment | อย่างใดอย่างหนึ่ง (อีกข้างเป็น null) | |
| delivery | คลัง | – |
| scrap | wip หรือคลัง | scrap location |

บังคับด้วย `CheckConstraint` ว่าแต่ละ `txn_type` มีข้างไหนบ้าง
ไม่ใช่ปล่อยให้ service จำเอง

### หน่วยนับ

`qty` + `uom_id` บันทึกตามที่ผู้ใช้กรอกจริง (INVARIANT ข้อ 4)
view ยอดคงเหลือแปลงเป็นหน่วยหลักของ item ตอนสะสม
**ห้ามแปลงแล้วทับค่าที่ผู้ใช้กรอก** เพราะสอบย้อนกลับไม่ได้ว่าหน้างานกรอกอะไรมา

### ต้นทุน

`unit_cost` / `total_cost` เฟสนี้แค่บันทึกตามที่รับมา ยังไม่ต้องคิดวิธีตีราคา
(FIFO / moving average) — นั่นคือเฟส 5 แต่ **ต้องตัดสินใจตอนนี้ว่าจะใช้วิธีไหน**
แล้วเขียน ADR เพราะมันกำหนดว่าเฟสนี้ต้องเก็บอะไรเพิ่ม
ถ้าเลือก FIFO ต้องมีทางอ้างถึง layer ที่ตัดไป ซึ่งเพิ่มทีหลังแพง

## เทสต์ที่ต้องมี

- ยิง `post_transaction` ด้วย `client_ref` เดิม 10 thread พร้อมกัน
  → ธุรกรรมเดียว ยอดถูก (ใช้ thread จริง + connection แยก ไม่ใช่ mock)
- เบิกเกินยอดคงเหลือ กับ item ที่ `allow_negative = false` → raise และไม่มีแถวค้าง
- เบิกพร้อมกันสองคน ของเหลือพอสำหรับคนเดียว → คนหนึ่งสำเร็จ คนหนึ่ง raise
  ห้ามสำเร็จทั้งคู่
- item ที่ `is_lot_controlled = true` แต่ไม่ส่ง `lot_no` → raise
- ยอดจาก view ตรงกับผลรวมที่คำนวณเองจากทุกแถวเสมอ (property test ก็ได้)
