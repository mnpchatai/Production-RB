import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  ApiError,
  type Operation,
  type ScrapReason,
  type WorkOrder,
  fetchOpenWorkOrders,
  fetchScrapReasons,
} from "../api/client";
import {
  type FlushResult,
  type QueuedReport,
  enqueue,
  flushQueue,
  listQueue,
  newClientRef,
  removeFromQueue,
} from "./queue";

type Banner = { kind: "ok" | "warn" | "error"; text: string } | null;

function nextOperation(order: WorkOrder): Operation | undefined {
  return order.operations.find((op) => op.status !== "completed") ?? order.operations[0];
}

function remainingFor(order: WorkOrder, operation: Operation | undefined) {
  if (!operation) return order.qty_remaining;
  const left = Number(order.qty_planned) - Number(operation.qty_good);
  return left > 0 ? String(left) : "0";
}

export default function ShopFloor({ onLogout }: { onLogout: () => void }) {
  const [orders, setOrders] = useState<WorkOrder[]>([]);
  const [reasons, setReasons] = useState<ScrapReason[]>([]);
  const [queue, setQueue] = useState<QueuedReport[]>([]);
  const [online, setOnline] = useState(navigator.onLine);
  const [banner, setBanner] = useState<Banner>(null);
  const [loading, setLoading] = useState(true);

  const [selectedWo, setSelectedWo] = useState<string>("");
  const [selectedSeq, setSelectedSeq] = useState<number | null>(null);
  const [qtyGood, setQtyGood] = useState("0");
  const [qtyScrap, setQtyScrap] = useState("0");
  const [reasonCode, setReasonCode] = useState<string>("");
  const startedAt = useRef<string>(new Date().toISOString());

  const order = useMemo(() => orders.find((o) => o.wo_no === selectedWo), [orders, selectedWo]);
  const operation = useMemo(
    () => order?.operations.find((op) => op.sequence === selectedSeq),
    [order, selectedSeq],
  );

  const refreshQueue = useCallback(async () => setQueue(await listQueue()), []);

  const reload = useCallback(async () => {
    try {
      const [openOrders, scrapReasons] = await Promise.all([
        fetchOpenWorkOrders(),
        fetchScrapReasons(),
      ]);
      setOrders(openOrders);
      setReasons(scrapReasons);
      setBanner(null);
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) {
        onLogout();
        return;
      }
      setBanner({ kind: "warn", text: "โหลดรายการงานไม่ได้ — ทำงานต่อในโหมดออฟไลน์ได้" });
    } finally {
      setLoading(false);
    }
  }, [onLogout]);

  const sync = useCallback(
    async (announce: boolean) => {
      const result: FlushResult = await flushQueue();
      await refreshQueue();
      if (result.sent > 0) {
        setBanner({ kind: "ok", text: `ส่งขึ้นระบบแล้ว ${result.sent} รายการ` });
        await reload();
      } else if (result.stopped && announce) {
        setBanner({ kind: "warn", text: `ยังส่งไม่ได้ (${result.stopped}) — เก็บไว้ในคิวแล้ว` });
      }
      if (result.failed > 0) {
        setBanner({
          kind: "error",
          text: `มี ${result.failed} รายการที่ระบบปฏิเสธ ต้องให้หัวหน้ากะตรวจ`,
        });
      }
    },
    [refreshQueue, reload],
  );

  useEffect(() => {
    void reload();
    void refreshQueue();
  }, [reload, refreshQueue]);

  useEffect(() => {
    const goOnline = () => {
      setOnline(true);
      void sync(false);
    };
    const goOffline = () => setOnline(false);
    window.addEventListener("online", goOnline);
    window.addEventListener("offline", goOffline);
    const timer = window.setInterval(() => {
      if (navigator.onLine) void sync(false);
    }, 20000);
    return () => {
      window.removeEventListener("online", goOnline);
      window.removeEventListener("offline", goOffline);
      window.clearInterval(timer);
    };
  }, [sync]);

  function pickOrder(wo: WorkOrder) {
    const operationToDo = nextOperation(wo);
    setSelectedWo(wo.wo_no);
    setSelectedSeq(operationToDo?.sequence ?? null);
    // เติมยอดคงเหลือตามแผนไว้ให้ก่อน พนักงานแค่กดบันทึกถ้าตรง
    setQtyGood(remainingFor(wo, operationToDo));
    setQtyScrap("0");
    setReasonCode("");
    startedAt.current = new Date().toISOString();
  }

  function pickOperation(op: Operation) {
    setSelectedSeq(op.sequence);
    if (order) setQtyGood(remainingFor(order, op));
  }

  function step(delta: number) {
    setQtyGood((current) => String(Math.max(0, (Number(current) || 0) + delta)));
  }

  async function save() {
    if (!order || selectedSeq === null) return;
    const good = Number(qtyGood) || 0;
    const scrap = Number(qtyScrap) || 0;
    if (good <= 0 && scrap <= 0) {
      setBanner({ kind: "error", text: "ต้องกรอกจำนวนอย่างน้อยหนึ่งช่อง" });
      return;
    }
    if (scrap > 0 && !reasonCode) {
      setBanner({ kind: "error", text: "มีของเสียต้องเลือกสาเหตุ" });
      return;
    }

    // client_ref เกิดตรงนี้ — ตอนกดปุ่ม ไม่ใช่ตอนส่ง
    await enqueue({
      client_ref: newClientRef(),
      wo_no: order.wo_no,
      operation_seq: selectedSeq,
      qty_good: String(good),
      qty_scrap: String(scrap),
      scrap_reason_code: reasonCode || undefined,
      started_at: startedAt.current,
      finished_at: new Date().toISOString(),
    });

    setBanner({ kind: "ok", text: "บันทึกแล้ว" });
    setQtyGood("0");
    setQtyScrap("0");
    setReasonCode("");
    startedAt.current = new Date().toISOString();
    await refreshQueue();
    if (navigator.onLine) void sync(true);
  }

  const pendingCount = queue.filter((row) => row.state !== "failed").length;
  const failed = queue.filter((row) => row.state === "failed");

  return (
    <div className="app">
      <div className="topbar">
        <h1>บันทึกผลหน้างาน</h1>
        <span className={`pill ${online ? "online" : "offline"}`}>
          {online ? "ออนไลน์" : "ออฟไลน์"}
        </span>
        <span className="pill queue">คิว {pendingCount}</span>
        {failed.length > 0 && <span className="pill failed">ตีกลับ {failed.length}</span>}
        <button className="linkish" onClick={onLogout}>
          ออก
        </button>
      </div>

      {banner && <div className={`banner ${banner.kind}`}>{banner.text}</div>}

      <div className="card">
        <h2>1. เลือกใบสั่งงาน</h2>
        {loading && <p>กำลังโหลด…</p>}
        {!loading && orders.length === 0 && <p>ยังไม่มีใบสั่งงานที่ปล่อยเข้าไลน์</p>}
        <div className="grid two">
          {orders.map((wo) => (
            <button
              key={wo.wo_no}
              className="choice"
              aria-pressed={wo.wo_no === selectedWo}
              onClick={() => pickOrder(wo)}
            >
              <strong>{wo.wo_no}</strong>
              <small>
                {wo.item_code} · เหลือ {Number(wo.qty_remaining)} {wo.uom_code} · ครบกำหนด{" "}
                {wo.due_date}
              </small>
            </button>
          ))}
        </div>
      </div>

      {order && (
        <div className="card">
          <h2>2. ขั้นตอน</h2>
          <div className="grid two">
            {order.operations.map((op) => (
              <button
                key={op.sequence}
                className={`choice${op.status === "completed" ? " done" : ""}`}
                aria-pressed={op.sequence === selectedSeq}
                onClick={() => pickOperation(op)}
              >
                <strong>
                  {op.sequence} · {op.name}
                </strong>
                <small>
                  {op.work_center_name} · ทำแล้ว {Number(op.qty_good)}
                </small>
              </button>
            ))}
          </div>
        </div>
      )}

      {order && operation && (
        <>
          <div className="card">
            <h2>3. จำนวนงานดี</h2>
            <div className="label">
              <span>
                {order.item_code} · {operation.work_center_name}
              </span>
              <span>
                แผน {Number(order.qty_planned)} {order.uom_code}
              </span>
            </div>
            <div className="qty-row">
              <button className="step" onClick={() => step(-10)}>
                −10
              </button>
              <input
                inputMode="decimal"
                value={qtyGood}
                onChange={(event) => setQtyGood(event.target.value)}
                onFocus={(event) => event.target.select()}
              />
              <button className="step" onClick={() => step(10)}>
                +10
              </button>
            </div>
          </div>

          <div className="card">
            <h2>4. ของเสีย (ถ้ามี)</h2>
            <div className="qty-row">
              <button
                className="step"
                onClick={() => setQtyScrap((c) => String(Math.max(0, (Number(c) || 0) - 1)))}
              >
                −1
              </button>
              <input
                inputMode="decimal"
                value={qtyScrap}
                onChange={(event) => setQtyScrap(event.target.value)}
                onFocus={(event) => event.target.select()}
              />
              <button
                className="step"
                onClick={() => setQtyScrap((c) => String((Number(c) || 0) + 1))}
              >
                +1
              </button>
            </div>
            {Number(qtyScrap) > 0 && (
              <div className="grid reasons" style={{ marginTop: 12 }}>
                {reasons.map((reason) => (
                  <button
                    key={reason.code}
                    className="choice"
                    aria-pressed={reason.code === reasonCode}
                    onClick={() => setReasonCode(reason.code)}
                  >
                    <strong>{reason.name}</strong>
                    <small>{reason.code}</small>
                  </button>
                ))}
              </div>
            )}
          </div>
        </>
      )}

      {failed.length > 0 && (
        <div className="card">
          <h2>รายการที่ระบบปฏิเสธ — ต้องให้หัวหน้ากะตรวจ</h2>
          {failed.map((row) => (
            <div className="queue-row" key={row.client_ref}>
              <div>
                <div>
                  {row.wo_no} · ขั้นที่ {row.operation_seq} · ดี {row.qty_good} เสีย {row.qty_scrap}
                </div>
                <div className="why">{row.last_error}</div>
              </div>
              <button className="linkish" onClick={() => void removeFromQueue(row.client_ref).then(refreshQueue)}>
                ทิ้ง
              </button>
            </div>
          ))}
        </div>
      )}

      <div className="submit">
        <button disabled={!order || selectedSeq === null} onClick={() => void save()}>
          บันทึกผล
        </button>
      </div>
    </div>
  );
}
