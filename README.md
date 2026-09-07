# ระบบวางแผนและติดตามการผลิต

ระบบวางแผนและติดตามการผลิตในองค์กร ครอบตั้งแต่ใบสั่งขายจนถึงต้นทุนจริงต่อใบสั่งผลิต

```
ใบสั่งขาย → วางแผนความต้องการ → ใบสั่งผลิต → เบิกวัตถุดิบ →
บันทึกผลรายขั้นตอน → รับเข้าคลัง → ปิดงานและคิดต้นทุน
```

| | |
|---|---|
| รูปแบบการผลิต | MTO (ผลิตตามสั่ง) |
| ระดับสอบย้อนกลับ | ระดับ lot |
| Backend | Django 5 + Django REST Framework (Python 3.12) |
| Database | PostgreSQL 16 |
| Frontend | React + TypeScript (Vite) |
| ภาษา UI | ไทย (ชื่อฟิลด์ในโค้ดและฐานข้อมูลเป็นภาษาอังกฤษ) |

## สถานะ

**ยังไม่เริ่มเฟส 0** — repo นี้มีแต่กฎ เอกสาร และ prompt ของแต่ละเฟส ยังไม่มีโค้ด

repo นี้เคยเป็นระบบใบสั่งงานแผนกขึ้นรูปยาง (RB Shop Floor) แบบหน้าเว็บเดียว
โค้ดเดิมทั้งหมดยังอยู่ใน git history ที่ commit `75d9e35`
เหตุผลที่เริ่มใหม่อยู่ใน [ADR-0002](docs/decisions/0002-replace-legacy-rb-app.md)

## เริ่มยังไง

1. อ่าน [`CLAUDE.md`](CLAUDE.md) — กฎ 10 ข้อที่ห้ามละเมิด และวิธีบังคับใช้บน Django
2. เปิดเซสชัน Claude Code ใหม่ วาง prompt จาก [`docs/phases/phase-0-master-data.md`](docs/phases/phase-0-master-data.md)
3. รันทีละเฟส ตรวจให้ผ่านก่อนขึ้นเฟสถัดไป — [เกณฑ์ผ่าน](docs/phases/README.md)

**อย่ารันหลายเฟสรวดเดียว** โครงสร้างข้อมูลที่ผิดตั้งแต่เฟสต้นจะลามไปทั้งระบบ

## แผนที่เอกสาร

| ไฟล์ | ใช้เมื่อไหร่ |
|---|---|
| [`CLAUDE.md`](CLAUDE.md) | Claude อ่านทุกเซสชัน — INVARIANTS, การตั้งชื่อ, โครงสร้างโปรเจกต์ |
| [`docs/phases/`](docs/phases/) | prompt ของแต่ละเฟส พร้อมรายละเอียดที่ห้ามพลาด |
| [`docs/scenarios.md`](docs/scenarios.md) | 8 สถานการณ์ที่ต้องมี integration test ครบ |
| [`docs/decisions/`](docs/decisions/) | ADR — เลือกอะไร เพราะอะไร ตัดทางไหนทิ้ง |
| [`docs/working-with-claude.md`](docs/working-with-claude.md) | ข้อควรระวังและรอบการทำงานต่อหนึ่งเฟส |
| `docs/schema.md` | ER diagram — เฟส 0 เป็นคนสร้าง อัปเดตทุกเฟส |

## คำสั่งลัด

| คำสั่ง | ทำอะไร |
|---|---|
| `/check-invariants` | ตรวจ diff เทียบ INVARIANTS ทีละข้อ — รันก่อน merge ทุกครั้ง |
| `/pre-merge-review` | code review เรียงตามความเสี่ยงของข้อมูล |
| `/new-doc-entity <ชื่อ>` | สร้างเอกสารใหม่ตามแบบแผนเดิม (header/lines + state machine + เทสต์) |
| `/trace-stock <item>` | ไล่ที่มาของยอดสต็อกรายธุรกรรม หาจุดที่ยอดเริ่มไม่ตรง |
| `/scenario-test <สถานการณ์>` | เขียน integration test แบบ end-to-end |
