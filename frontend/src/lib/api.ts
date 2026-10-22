/**
 * API client. In the browser it calls same-origin /api/v1 (proxied by Next.js
 * rewrites) with the httpOnly session cookie. On the server it calls the
 * backend directly. Authoritative data (balances, permissions, prices) always
 * comes from the API; the frontend never computes it.
 */
export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

function baseUrl() {
  if (typeof window === "undefined") return `${process.env.BACKEND_URL ?? "http://localhost:8000"}/api/v1`;
  return "/api/v1";
}

function errorMessage(body: unknown, status: number): string {
  if (body && typeof body === "object" && "detail" in body) {
    const detail = (body as { detail: unknown }).detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail) && detail[0]?.msg) {
      const d = detail[0];
      const field = Array.isArray(d.loc) ? d.loc[d.loc.length - 1] : "";
      return field ? `${field}: ${d.msg}` : d.msg;
    }
  }
  return status === 0 ? "Network error" : `Request failed (${status})`;
}

export async function api<T>(path: string, init: RequestInit & { json?: unknown } = {}): Promise<T> {
  const { json, headers, ...rest } = init;
  const h = new Headers(headers);
  h.set("X-Requested-With", "fetch");
  if (json !== undefined) h.set("Content-Type", "application/json");
  const res = await fetch(`${baseUrl()}${path}`, {
    credentials: "include",
    cache: "no-store",
    ...rest,
    headers: h,
    body: json !== undefined ? JSON.stringify(json) : rest.body,
  });
  const text = await res.text();
  const body = text ? safeJson(text) : null;
  if (!res.ok) throw new ApiError(res.status, errorMessage(body, res.status));
  return body as T;
}

function safeJson(text: string) {
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}

/** Server-side fetch that degrades gracefully when the API is unreachable. */
export async function tryApi<T>(path: string, fallback: T): Promise<T> {
  try {
    return await api<T>(path);
  } catch {
    return fallback;
  }
}

export const money = (cents: number | null | undefined, currency = "USD") =>
  cents == null
    ? ""
    : new Intl.NumberFormat("en-US", { style: "currency", currency }).format(cents / 100);

export const label = (s: string) => s.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());

export const duration = (s: number | null) => {
  if (!s) return "";
  const m = Math.floor(s / 60);
  const sec = Math.round(s % 60);
  return `${m}:${sec.toString().padStart(2, "0")}`;
};
