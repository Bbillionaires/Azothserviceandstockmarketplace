"use client";

import { useCallback, useEffect, useState } from "react";
import { Alert } from "@/components/Alert";
import { api, label, money } from "@/lib/api";
import type { Order } from "@/lib/orders";

type Overview = Record<string, number | string>;
type AdminOrder = Order & { buyer_email: string; processing_fee_cents: number };
type Run = { id: string; status: string; started_at: string; checks: Record<string, unknown>; findings: Record<string, unknown>[] };
type FailedEvent = { id: string; provider_event_id: string; type: string; error: string };

const MONEY_KEYS = ["gmv_cents", "platform_revenue_cents", "fee_recovery_cents", "processing_fees_cents", "refunds_cents",
  "creator_earnings_cents", "affiliate_commissions_cents", "owed_to_payees_cents", "paid_out_cents", "tax_payable_cents"];

export function FinancePanel() {
  const [o, setO] = useState<Overview | null>(null);
  const [orders, setOrders] = useState<AdminOrder[]>([]);
  const [runs, setRuns] = useState<Run[]>([]);
  const [events, setEvents] = useState<FailedEvent[]>([]);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);

  const load = useCallback(async () => {
    const [ov, ord, rec, ev] = await Promise.all([
      api<Overview>("/admin/finance/overview"),
      api<{ items: AdminOrder[] }>("/admin/finance/orders?page_size=50"),
      api<Run[]>("/admin/finance/reconciliation"),
      api<FailedEvent[]>("/admin/finance/events"),
    ]);
    setO(ov); setOrders(ord.items); setRuns(rec); setEvents(ev);
  }, []);

  useEffect(() => { load().catch((e) => setMsg({ ok: false, text: e.message })); }, [load]);

  const act = async (fn: () => Promise<unknown>, text: (r: unknown) => string) => {
    try { const r = await fn(); setMsg({ ok: true, text: text(r) }); await load(); } catch (e) { setMsg({ ok: false, text: (e as Error).message }); }
  };

  if (!o) return <p className="mt-6 text-ink-300">{msg?.text ?? "Loading finance…"}</p>;
  const cur = String(o.currency);
  const latest = runs[0];

  return (
    <div className="mt-6 space-y-8">
      {msg && <Alert kind={msg.ok ? "success" : "error"}>{msg.text}</Alert>}
      <dl className="grid grid-cols-2 gap-3 md:grid-cols-4 lg:grid-cols-5">
        {MONEY_KEYS.map((k) => (
          <div key={k} className="card p-4"><dt className="text-xs text-ink-400">{label(k.replace("_cents", ""))}</dt><dd className="font-display mt-1 text-xl">{money(Number(o[k]), cur)}</dd></div>
        ))}
        {["orders", "paying_customers", "repeat_customer_rate", "failed_events"].map((k) => (
          <div key={k} className="card p-4"><dt className="text-xs text-ink-400">{label(k)}</dt>
            <dd className="font-display mt-1 text-xl">{k === "repeat_customer_rate" ? `${Math.round(Number(o[k]) * 100)}%` : String(o[k])}</dd></div>
        ))}
      </dl>

      <div className="flex flex-wrap gap-2">
        <button className="btn-gold text-sm" onClick={() => act(() => api("/admin/finance/payouts/run", { method: "POST" }), (r) => `Payout run: ${JSON.stringify(r)}`)}>Run payouts now</button>
        <button className="btn-ghost text-sm" onClick={() => act(() => api<Run>("/admin/finance/reconciliation/run", { method: "POST" }), (r) => `Reconciliation: ${(r as Run).status}`)}>Run reconciliation</button>
      </div>

      {latest && (
        <section className={`card p-5 text-sm ${latest.status === "ok" ? "" : "border-red-500/40"}`}>
          <p className="font-medium">Last reconciliation: <span className={latest.status === "ok" ? "text-emerald-300" : "text-red-300"}>{label(latest.status)}</span> · {new Date(latest.started_at).toLocaleString()}</p>
          <ul className="mt-2 grid gap-1 text-xs text-ink-300 sm:grid-cols-2">
            {Object.entries(latest.checks).map(([k, v]) => <li key={k}>{label(k)}: {typeof v === "object" ? JSON.stringify(v) : String(v)}</li>)}
          </ul>
          {latest.findings.length > 0 && <pre className="mt-3 max-h-48 overflow-auto rounded bg-ink-950 p-3 text-xs text-red-200">{JSON.stringify(latest.findings, null, 2)}</pre>}
        </section>
      )}

      {events.length > 0 && (
        <section className="space-y-2">
          <h3 className="font-display text-lg">Failed payment events</h3>
          {events.map((e) => (
            <div key={e.id} className="card flex flex-wrap items-center justify-between gap-2 p-3 text-sm">
              <span>{e.type} · {e.provider_event_id}<span className="block text-xs text-red-300">{e.error}</span></span>
              <button className="btn-ghost text-xs" onClick={() => act(() => api(`/admin/finance/events/${e.id}/retry`, { method: "POST" }), (r) => `Retry: ${JSON.stringify(r)}`)}>Retry</button>
            </div>
          ))}
        </section>
      )}

      <section className="space-y-2">
        <h3 className="font-display text-lg">Recent orders</h3>
        {orders.length === 0 && <p className="text-ink-300">No orders yet.</p>}
        {orders.map((ord) => (
          <div key={ord.id} className="card p-4 text-sm">
            <div className="flex flex-wrap justify-between gap-2">
              <span>{new Date(ord.created_at).toLocaleString()} · {ord.buyer_email} · <strong>{label(ord.status)}</strong></span>
              <span>{money(ord.total_cents, ord.currency)} <span className="text-xs text-ink-400">(fee {money(ord.processing_fee_cents, ord.currency)})</span></span>
            </div>
            <ul className="mt-2 space-y-1 text-ink-300">
              {ord.lines.map((l) => (
                <li key={l.id} className="flex flex-wrap items-center justify-between gap-2">
                  <span>{l.asset_title} · {l.license_name} · {money(l.unit_price_cents, ord.currency)} · {label(l.status)}</span>
                  {l.status === "fulfilled" && (
                    <button className="text-xs text-red-300 underline" onClick={() => {
                      if (confirm(`Refund ${money(l.unit_price_cents + l.tax_cents, ord.currency)} to the buyer? Their license will be revoked.`)) {
                        act(() => api(`/admin/finance/orders/${ord.id}/refund`, { method: "POST", json: { line_ids: [l.id], reason: "requested_by_customer" } }), () => "Refund issued");
                      }
                    }}>Refund line</button>
                  )}
                </li>
              ))}
            </ul>
          </div>
        ))}
      </section>
    </div>
  );
}
