---
description: ตรวจโค้ดใน branch นี้เทียบกับ INVARIANTS ใน CLAUDE.md ทีละข้อ
---

ตรวจโค้ดที่เปลี่ยนแปลงใน branch นี้เทียบกับกฎ INVARIANTS ใน CLAUDE.md ทีละข้อ

รายงานเป็นตาราง: ข้อที่ | ผ่าน/ไม่ผ่าน | ไฟล์และบรรทัด | เหตุผล

ให้ความสำคัญเป็นพิเศษกับ:
- มี hard delete หลุดเข้ามาไหม
- มีการ join ไป bom_lines จาก work_order โดยตรงไหม
- มีคอลัมน์หรือตัวแปรยอดคงเหลือที่เขียนทับได้ไหม
- มีจำนวนที่ไม่มี uom กำกับไหม
- มี float ที่ใช้กับจำนวนหรือเงินไหม

ถ้าผ่านทุกข้อให้บอกสั้นๆ ว่าผ่าน อย่าสรุปยาว

จุดเริ่มที่ใช้ได้เร็ว (เป็นตัวช่วยหาเป้า ไม่ใช่ข้อสรุป — ต้องอ่านโค้ดยืนยันเสมอ):

```bash
BASE=$(git merge-base HEAD origin/main)
git diff --name-only $BASE...HEAD

git diff $BASE...HEAD -U0 | grep -nE '^\+' | grep -E \
  'FloatField|float\(|\.delete\(\)|on_delete=models\.CASCADE|qty_on_hand|qty_available|\.status *=|auto_now'
```

ข้อ 10 หาไม่เจอด้วย grep — ต้องไล่อ่านทุกฟังก์ชันที่เขียน `stock_transactions`
หรือเปลี่ยน status ว่าอยู่ใน `transaction.atomic()` และมี `select_for_update()`
ครบทุกเส้นทางหรือไม่ รวมทั้งเส้นทางที่ raise แล้ว rollback ด้วย
