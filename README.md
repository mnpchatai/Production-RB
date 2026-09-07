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
| Backend | Django 5 + Django REST Framework (Python 3.11+) |
| Database | PostgreSQL 16 |
| Frontend | React + TypeScript (Vite) |
| ภาษา UI | ไทย (ชื่อฟิลด์ในโค้ดและฐานข้อมูลเป็นภาษาอังกฤษ) |

## เริ่มใช้งานใน 3 คำสั่ง

ถ้ามี Docker:

```bash
cp .env.example .env
make up
```

- หน้าจอหน้างาน: http://localhost:5173
- API + Django admin: http://localhost:8000/admin/
- ผู้ใช้ทดสอบ: `admin` / `operator1` / `planner1` รหัสผ่าน `demo1234`

ถ้าไม่ใช้ Docker (ต้องมี PostgreSQL 16 อยู่แล้ว):

```bash
cp .env.example .env          # แก้ POSTGRES_* ให้ตรงกับเครื่อง
make setup migrate seed
make run                      # หน้าต่างหนึ่ง
make front-dev                # อีกหน้าต่างหนึ่ง
```

## สิ่งที่ทำได้แล้ว

| ส่วน | สถานะ |
|---|---|
| ข้อมูลหลัก (uom + การแปลงหน่วย, items, คลัง, work center, อัตราค่าแรงตามช่วงเวลา) | ใช้งานได้ |
| BOM หลายระดับ + Routing พร้อม `explode_bom` (scrap สะสม, ตรวจวนซ้ำ, เคารพวันที่มีผล) | ใช้งานได้ |
| ใบสั่งขาย + ใบสั่งผลิตที่ snapshot BOM/Routing ณ วันออกใบ | ใช้งานได้ |
| ธุรกรรมสต็อก + วิวยอดคงเหลือ + idempotency + กันยอดติดลบ | ใช้งานได้ |
| บันทึกผลหน้างาน + backflush + คิว exception เมื่อของไม่พอ | ใช้งานได้ |
| หน้าจอแท็บเล็ตพร้อมโหมดออฟไลน์ (IndexedDB) | ใช้งานได้ |
| ต้นทุนจริงต่อใบสั่งผลิต + drill down ถึงระดับธุรกรรม | ใช้งานได้ |
| รายงาน 4 ตัว (สถานะ WO, แผน vs จริง, ของเสีย, SO เสี่ยงส่งไม่ทัน) | ใช้งานได้ |
| Django admin สำหรับฝ่ายวางแผน/บัญชี (ไม่มีปุ่มลบเอกสาร) | ใช้งานได้ |

**ยังไม่มี:** หน้าจอเว็บสำหรับฝ่ายขาย/วางแผน/บัญชี (ตอนนี้ใช้ Django admin กับ API แทน),
การพิมพ์ใบสั่งงานและป้ายชี้บ่ง, การนำเข้าข้อมูลจริงจาก Excel เดิม

## เทสต์

```bash
make test
```

59 เทสต์ รันบน **PostgreSQL จริงเท่านั้น** ไม่ใช่ SQLite เพราะ `select_for_update`
กับ `numeric` ทำงานไม่เหมือนกัน ในนั้นมี:

- เทสต์ concurrency ด้วย thread จริงกับ connection แยก ไม่ใช่ mock
  (จองเลขเอกสาร 10 เธรด, ยิง `client_ref` เดิม 10 ครั้งพร้อมกัน, สองคนเบิกของชิ้นสุดท้าย)
- เทสต์เส้นทางที่ **ต้องล้มเหลว** (เบิกเกินสต็อก, ผลิตเกินเกณฑ์, ยกเลิกโดยไม่คืนของ,
  แก้ `qty_planned` หลัง released, transition ที่ไม่อนุญาต)
- 8 สถานการณ์จริงแบบ end-to-end ใน [`backend/tests/scenarios/`](backend/tests/scenarios/)
  ทุกตัวจบด้วยการยืนยันยอดสต็อกกับต้นทุนของใบสั่งผลิต

## API หลัก

| Endpoint | ใช้ทำอะไร |
|---|---|
| `POST /api/auth/token/` | ขอ token |
| `GET /api/work-orders/open/` | ใบสั่งงานที่หน้างานยังต้องทำ |
| `POST /api/shop-floor/report` | บันทึกผลหน้างาน (idempotent ด้วย `client_ref`) |
| `GET /api/stock/balances/?nonzero=1` | ยอดคงเหลือ (จากวิว ไม่ใช่คอลัมน์) |
| `GET /api/stock/trace/<item_code>` | ไล่ธุรกรรมพร้อมยอดสะสมทีละบรรทัด |
| `GET /api/work-orders/<wo_no>/cost` | ต้นทุนจริงพร้อมรายบรรทัดที่กางกลับไปหาต้นทางได้ |
| `GET /api/reports/wo-status` | สถานะใบสั่งผลิต แยกตามขั้นตอนที่ค้าง |
| `GET /api/reports/plan-vs-actual` | เทียบต้นทุนแผนกับจริง แยกวัตถุดิบ/ค่าแรง |
| `GET /api/reports/scrap` | ของเสียแยกตามสาเหตุและ work center |
| `GET /api/reports/so-at-risk` | ใบสั่งขายที่เสี่ยงส่งไม่ทัน พร้อมจำนวนวันที่ขาด |

## โครงสร้าง

```
backend/
  config/          settings (base/dev/test/prod), urls
  apps/
    common/        AuditedModel, DocumentModel, state_machine, เลขที่เอกสาร, แปลงหน่วย
    masterdata/    uoms, items, คลัง, work center, อัตราค่าแรง, สาเหตุของเสีย, ลูกค้า
    bom/           BOM, Routing, explode_bom
    sales/         ใบสั่งขาย
    production/    ใบสั่งผลิต, snapshot, บันทึกผลหน้างาน, backflush
    inventory/     ธุรกรรมสต็อก, วิวยอดคงเหลือ, post_transactions
    costing/       ต้นทุนจริงและรายงาน
  tests/scenarios/ 8 สถานการณ์ end-to-end
frontend/src/
  api/             client + token
  shopfloor/       หน้าจอแท็บเล็ต + คิว IndexedDB
docs/              schema, phases, decisions, scenarios
```

## เอกสาร

| ไฟล์ | ใช้เมื่อไหร่ |
|---|---|
| [`CLAUDE.md`](CLAUDE.md) | Claude อ่านทุกเซสชัน — INVARIANTS 10 ข้อ และวิธีบังคับใช้บน Django |
| [`docs/schema.md`](docs/schema.md) | ER diagram + constraint ทั้งหมดที่อยู่ในฐานข้อมูล |
| [`docs/decisions/`](docs/decisions/) | ADR — เลือกอะไร เพราะอะไร ตัดทางไหนทิ้ง |
| [`docs/phases/`](docs/phases/) | ข้อกำหนดรายเฟสและรายละเอียดที่ห้ามพลาด |
| [`docs/scenarios.md`](docs/scenarios.md) | 8 สถานการณ์ที่ต้องมีเทสต์ พร้อมลิงก์ไปเทสต์จริง |
| [`docs/working-with-claude.md`](docs/working-with-claude.md) | ข้อควรระวังและรอบการทำงาน |

## คำสั่งลัดสำหรับ Claude Code

| คำสั่ง | ทำอะไร |
|---|---|
| `/check-invariants` | ตรวจ diff เทียบ INVARIANTS ทีละข้อ — รันก่อน merge ทุกครั้ง |
| `/pre-merge-review` | code review เรียงตามความเสี่ยงของข้อมูล |
| `/new-doc-entity <ชื่อ>` | สร้างเอกสารใหม่ตามแบบแผนเดิม |
| `/trace-stock <item>` | ไล่ที่มาของยอดสต็อกรายธุรกรรม |
| `/scenario-test <สถานการณ์>` | เขียน integration test แบบ end-to-end |

## ประวัติ

repo นี้เคยเป็นระบบใบสั่งงานแผนกขึ้นรูปยาง (RB Shop Floor) แบบหน้าเว็บเดียว
โค้ดเดิมอยู่ที่ commit `75d9e35` เหตุผลที่เริ่มใหม่อยู่ใน
[ADR-0002](docs/decisions/0002-replace-legacy-rb-app.md)
