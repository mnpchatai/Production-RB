#!/usr/bin/env python3
"""
อัปโหลด CSV ที่ได้จาก etl.py ขึ้น Supabase ผ่าน REST API (ไม่ต้องมี psql)

ใช้งาน:
    export SUPABASE_URL="https://xxxx.supabase.co"
    export SUPABASE_SERVICE_KEY="secret key (sb_secret_...) จาก Project Settings > API Keys"
    python3 load.py --data data

ต้องรัน schema.sql ในหน้า SQL Editor ของ Supabase ให้เสร็จก่อน

ต้องใช้ secret key หรือ service_role key เท่านั้น (คีย์ฝั่งผู้ใช้จะโดน RLS บล็อก)
คีย์นี้ข้าม RLS ได้ทั้งหมด
อย่าเก็บไว้ในไฟล์ที่ commit ขึ้น git และอย่าใส่ในหน้าเว็บฝั่ง client
"""

import argparse, csv, json, os, sys, urllib.error, urllib.request

# ลำดับนำเข้า — ตารางแม่ต้องมาก่อนลูก (ลบก็ไล่ย้อนกลับ)
ORDER = ["rb_books", "rb_colors", "rb_customers", "rb_products", "rb_formulas",
         "rb_item_standards", "rb_bom_lines", "rb_work_order_lines", "rb_doc_log"]

# คอลัมน์ที่เป็น jsonb ต้อง parse ก่อนส่ง ไม่งั้นจะถูกเก็บเป็นสตริง
JSONB = {("rb_books", "settings"), ("rb_work_order_lines", "std_snapshot")}

BATCH = 500


def request(method, url, key, body=None, prefer=None):
    headers = {"apikey": key, "Authorization": f"Bearer {key}",
               "Content-Type": "application/json"}
    if prefer:
        headers["Prefer"] = prefer
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")


def read_rows(path, table):
    with open(path, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            rec = {}
            for k, v in row.items():
                if v == "":
                    rec[k] = None
                elif (table, k) in JSONB:
                    rec[k] = json.loads(v)
                else:
                    rec[k] = v
            yield rec


def main():
    ap = argparse.ArgumentParser(description="อัปโหลด CSV ขึ้น Supabase ผ่าน REST")
    ap.add_argument("--data", default="data", help="โฟลเดอร์ที่มีไฟล์ CSV")
    ap.add_argument("--url", default=os.environ.get("SUPABASE_URL"))
    ap.add_argument("--key", default=os.environ.get("SUPABASE_SERVICE_KEY"))
    ap.add_argument("--keep", action="store_true",
                    help="ไม่ลบข้อมูลเดิมก่อนนำเข้า (ค่าปกติคือลบทิ้งแล้วใส่ใหม่)")
    a = ap.parse_args()

    if not a.url or not a.key:
        sys.exit("ต้องตั้ง SUPABASE_URL และ SUPABASE_SERVICE_KEY ก่อน")
    base = a.url.rstrip("/") + "/rest/v1"

    missing = [t for t in ORDER if not os.path.exists(os.path.join(a.data, f"{t}.csv"))]
    if missing:
        sys.exit(f"ไม่พบไฟล์ CSV ของตาราง: {', '.join(missing)}")

    if not a.keep:
        # ลบไล่จากตารางลูกขึ้นไปหาแม่ กัน foreign key ขัด
        for t in reversed(ORDER):
            col = "code" if t == "rb_books" else "book_code"
            st, body = request("DELETE", f"{base}/{t}?{col}=not.is.null", a.key)
            if st >= 300:
                sys.exit(f"ลบ {t} ไม่สำเร็จ ({st}): {body[:300]}")
            print(f"ล้าง {t}")

    for t in ORDER:
        rows = list(read_rows(os.path.join(a.data, f"{t}.csv"), t))
        sent = 0
        for i in range(0, len(rows), BATCH):
            chunk = rows[i:i + BATCH]
            st, body = request("POST", f"{base}/{t}", a.key, chunk,
                               prefer="return=minimal,resolution=merge-duplicates")
            if st >= 300:
                sys.exit(f"\nนำเข้า {t} ไม่สำเร็จ ({st}): {body[:500]}")
            sent += len(chunk)
            print(f"\r{t:22s} {sent}/{len(rows)}", end="", flush=True)
        print(f"\r{t:22s} {sent}/{len(rows)}  ✓")


if __name__ == "__main__":
    main()
