const TOKEN_KEY = "mes.token";
const USER_KEY = "mes.user";

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly payload: unknown,
    message: string,
  ) {
    super(message);
  }

  /** 4xx = คำขอผิดเอง ส่งซ้ำกี่ครั้งก็ผิดเหมือนเดิม ต้องหยุดและแสดงให้พนักงานเห็น */
  get isPermanent() {
    return this.status >= 400 && this.status < 500;
  }
}

export function getToken() {
  return localStorage.getItem(TOKEN_KEY);
}

export function getUsername() {
  return localStorage.getItem(USER_KEY) ?? "";
}

export function clearToken() {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(USER_KEY);
}

function describe(payload: unknown): string {
  if (typeof payload === "string") return payload;
  if (payload && typeof payload === "object") {
    const record = payload as Record<string, unknown>;
    if (typeof record.detail === "string") return record.detail;
    const parts = Object.entries(record).map(([key, value]) =>
      Array.isArray(value) ? `${key}: ${value.join(" ")}` : `${key}: ${String(value)}`,
    );
    if (parts.length) return parts.join(" | ");
  }
  return "เกิดข้อผิดพลาดที่ไม่รู้จัก";
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const token = getToken();
  const response = await fetch(path, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Token ${token}` } : {}),
      ...(init.headers ?? {}),
    },
  });

  const text = await response.text();
  const payload = text ? JSON.parse(text) : null;
  if (!response.ok) {
    throw new ApiError(response.status, payload, describe(payload));
  }
  return payload as T;
}

export async function login(username: string, password: string) {
  const data = await api<{ token: string }>("/api/auth/token/", {
    method: "POST",
    body: JSON.stringify({ username, password }),
  });
  localStorage.setItem(TOKEN_KEY, data.token);
  localStorage.setItem(USER_KEY, username);
  return data.token;
}

export interface Operation {
  sequence: number;
  name: string;
  work_center_code: string;
  work_center_name: string;
  status: string;
  qty_good: string;
  qty_scrap: string;
}

export interface WorkOrder {
  wo_no: string;
  item_code: string;
  item_name: string;
  qty_planned: string;
  qty_completed: string;
  qty_remaining: string;
  uom_code: string;
  due_date: string;
  status: string;
  operations: Operation[];
}

export interface ScrapReason {
  id: number;
  code: string;
  name: string;
}

export function fetchOpenWorkOrders() {
  return api<WorkOrder[]>("/api/work-orders/open/");
}

export function fetchScrapReasons(workCenter?: string) {
  const query = workCenter ? `?work_center=${encodeURIComponent(workCenter)}` : "";
  return api<{ results: ScrapReason[] }>(`/api/scrap-reasons/${query}`).then((d) => d.results);
}

export function fetchWorkCenters() {
  return api<{ results: { id: number; code: string; name: string }[] }>(
    "/api/work-centers/",
  ).then((d) => d.results);
}
