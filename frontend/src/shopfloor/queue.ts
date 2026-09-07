/**
 * คิวบันทึกผลหน้างานสำหรับโหมดออฟไลน์
 *
 * กฎที่ห้ามพลาด:
 * - client_ref สร้างตอน "กดปุ่มบันทึก" ไม่ใช่ตอนส่ง ถ้าสร้างตอนส่ง การ retry
 *   จะได้ uuid ใหม่ทุกครั้ง = ธุรกรรมซ้ำที่ฝั่ง server
 * - ส่งเรียงตามลำดับที่บันทึก ไม่ส่งขนานกัน
 * - server ตอบ 4xx ต้องหยุด retry แล้วแสดงให้พนักงานเห็น ไม่วนซ้ำไม่รู้จบ
 */

import { ApiError, api } from "../api/client";

const DB_NAME = "mes-shopfloor";
const STORE = "queue";
const VERSION = 1;

export type QueueState = "pending" | "sending" | "failed";

export interface QueuedReport {
  client_ref: string;
  wo_no: string;
  operation_seq: number;
  qty_good: string;
  qty_scrap: string;
  scrap_reason_code?: string;
  started_at?: string;
  finished_at?: string;
  queued_at: string;
  state: QueueState;
  attempts: number;
  last_error?: string;
}

function openDb(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DB_NAME, VERSION);
    request.onupgradeneeded = () => {
      const db = request.result;
      if (!db.objectStoreNames.contains(STORE)) {
        const store = db.createObjectStore(STORE, { keyPath: "client_ref" });
        store.createIndex("queued_at", "queued_at");
      }
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

async function withStore<T>(
  mode: IDBTransactionMode,
  run: (store: IDBObjectStore) => IDBRequest<T>,
): Promise<T> {
  const db = await openDb();
  return new Promise<T>((resolve, reject) => {
    const transaction = db.transaction(STORE, mode);
    const request = run(transaction.objectStore(STORE));
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
    transaction.oncomplete = () => db.close();
  });
}

export function newClientRef() {
  if (typeof crypto.randomUUID === "function") return crypto.randomUUID();
  // สำรองสำหรับเบราว์เซอร์เก่าบนแท็บเล็ตหน้างาน
  return "10000000-1000-4000-8000-100000000000".replace(/[018]/g, (c) => {
    const n = Number(c);
    return (n ^ (crypto.getRandomValues(new Uint8Array(1))[0] & (15 >> (n / 4)))).toString(16);
  });
}

export async function enqueue(
  report: Omit<QueuedReport, "queued_at" | "state" | "attempts">,
): Promise<QueuedReport> {
  const entry: QueuedReport = {
    ...report,
    queued_at: new Date().toISOString(),
    state: "pending",
    attempts: 0,
  };
  await withStore("readwrite", (store) => store.put(entry));
  return entry;
}

export function listQueue(): Promise<QueuedReport[]> {
  return withStore<QueuedReport[]>("readonly", (store) => store.getAll()).then((rows) =>
    rows.sort((a, b) => a.queued_at.localeCompare(b.queued_at)),
  );
}

export function removeFromQueue(clientRef: string) {
  return withStore("readwrite", (store) => store.delete(clientRef));
}

async function markFailed(entry: QueuedReport, message: string) {
  await withStore("readwrite", (store) =>
    store.put({ ...entry, state: "failed", attempts: entry.attempts + 1, last_error: message }),
  );
}

async function markRetryable(entry: QueuedReport, message: string) {
  await withStore("readwrite", (store) =>
    store.put({ ...entry, state: "pending", attempts: entry.attempts + 1, last_error: message }),
  );
}

export interface FlushResult {
  sent: number;
  remaining: number;
  failed: number;
  stopped?: string;
}

/** ส่งคิวทีละรายการเรียงตามเวลา — หยุดทันทีเมื่อเจอปัญหาเครือข่าย */
export async function flushQueue(): Promise<FlushResult> {
  const entries = await listQueue();
  let sent = 0;
  let stopped: string | undefined;

  for (const entry of entries) {
    if (entry.state === "failed") continue;
    try {
      await api("/api/shop-floor/report", {
        method: "POST",
        body: JSON.stringify({
          client_ref: entry.client_ref,
          wo_no: entry.wo_no,
          operation_seq: entry.operation_seq,
          qty_good: entry.qty_good,
          qty_scrap: entry.qty_scrap,
          ...(entry.scrap_reason_code ? { scrap_reason_code: entry.scrap_reason_code } : {}),
          ...(entry.started_at ? { started_at: entry.started_at } : {}),
          ...(entry.finished_at ? { finished_at: entry.finished_at } : {}),
        }),
      });
      await removeFromQueue(entry.client_ref);
      sent += 1;
    } catch (error) {
      if (error instanceof ApiError && error.isPermanent) {
        // คำขอผิดเอง ส่งซ้ำก็ผิดเหมือนเดิม
        await markFailed(entry, error.message);
        continue;
      }
      const message = error instanceof Error ? error.message : String(error);
      await markRetryable(entry, message);
      stopped = message;
      break; // เครือข่ายมีปัญหา หยุดทั้งคิวไว้ก่อน ไม่ยิงรัว
    }
  }

  const remaining = await listQueue();
  return {
    sent,
    remaining: remaining.filter((row) => row.state !== "failed").length,
    failed: remaining.filter((row) => row.state === "failed").length,
    stopped,
  };
}
