---
description: สร้างเอกสารใหม่ (header/lines + state machine + เทสต์) ตามแบบแผนเดิม
argument-hint: <ชื่อเอกสาร เช่น purchase_orders>
---

สร้างเอกสารใหม่ชื่อ $ARGUMENTS ตามแบบแผนเดิมของโปรเจกต์

ต้องมีครบ:
1. ตาราง header + lines พร้อม audit fields
2. ลงทะเบียนใน document_sequences
3. state machine พร้อมตารางประวัติสถานะ
4. ไม่มี hard delete มีแต่ cancel
5. เทสต์ครอบคลุมทุกเส้นทางของ state machine รวมทั้งเส้นทางที่ต้องถูกปฏิเสธ

เสนอ migration ให้ดูก่อน รอยืนยันแล้วค่อยเขียนโค้ดที่เหลือ

บนโปรเจกต์นี้แปลว่า:
- model สืบทอด `apps.common.models.AuditedModel` และ `DocumentModel`
- ประกาศ transition ใน `apps/common/state_machine.py` ที่เดียว ไม่ประกาศในแอปตัวเอง
- `<doc>_status_history` เก็บ `from_status`, `to_status`, `changed_by`, `changed_at`, `note`
- จำนวนทุกฟิลด์มี `uom` FK คู่กัน และเป็น `DecimalField(max_digits=18, decimal_places=4)`
- ถ้าเอกสารนี้แตะสต็อก ต้องเรียก `post_transaction` เท่านั้น ห้ามเขียน `stock_transactions` ตรง
