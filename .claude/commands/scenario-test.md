---
description: เขียน integration test จำลองสถานการณ์จริงแบบ end-to-end
argument-hint: <สถานการณ์ เช่น "ยกเลิก WO หลังเบิกของแล้ว">
---

เขียน integration test จำลองสถานการณ์จริง: $ARGUMENTS

ต้องเป็นเทสต์แบบ end to end ผ่าน service layer จริง ไม่ใช่ mock
และต้องยืนยันยอดสต็อกท้ายสุดกับต้นทุนของใบสั่งผลิตด้วยเสมอ

บนโปรเจกต์นี้:
- วางไว้ที่ `backend/tests/scenarios/` ชื่อไฟล์สื่อสถานการณ์
- ใช้ `pytest.mark.django_db(transaction=True)` เพราะต้องทดสอบ commit จริง
- เรียกผ่าน `apps/*/services.py` เท่านั้น ห้ามสร้าง object ด้วย ORM ตรง
  ยกเว้นข้อมูลหลัก (items, uoms, warehouses, work_centers)
- ทุกเทสต์จบด้วยการ assert สองอย่างนี้เสมอ:
  1. ยอดจาก view `stock_balances` ตรงกับผลรวมของ `stock_transactions` ที่คำนวณเอง
  2. ต้นทุนรวมของ WO เท่ากับผลรวมของธุรกรรมที่ drill down ได้จริง
- ถ้าสถานการณ์มีการยิงพร้อมกัน ใช้ `ThreadPoolExecutor` กับ connection แยก
  ห้ามใช้ mock แทน race condition

รายการสถานการณ์ที่ต้องมีครบอยู่ใน `docs/scenarios.md` — อัปเดตสถานะในไฟล์นั้นด้วย
