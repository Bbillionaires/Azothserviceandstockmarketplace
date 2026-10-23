"use client";

import { Fragment, useEffect, useState } from "react";
import { Alert } from "@/components/Alert";
import { api, label, money } from "@/lib/api";

type Summary = {
  currency: string;
  currencies: string[];
  pending_cents: number;
  available_cents: number;
  paid_cents: number;
  lifetime_cents: number;
  by_kind: Record<string, number>;
  next_release_at: string | null;
  hold_days: number;
  min_payout_cents: number;
  payout_account: { status: string; payouts_enabled: boolean; requirements_due: string[]; tax_info_status: string } | null;
};
type Row = {
  id: string; kind: string; status: string; amount_cents: number; currency: string; available_at: string;
  created_at: string; asset_title: string; license_name: string; gross_cents: number; rule: string;
  explanation: string[]; is_clawback: boolean;
};
type PayoutRow = { id: string; amount_cents: number; currency: string; status: string; created_at: string; failure_reason: string | null };

export function EarningsPanel() {
  const [s, setS] = useState<Summary | null>(null);
  const [rows, setRows] = useState<Row[]>([]);
  const [payouts, setPayouts] = useState<PayoutRow[]>([]);
  const [open, setOpen] = useState<string | null>(null);
  const [country, setCountry] = useState("US");
  const [error, setError] = useState("");
  const month = new Date().toISOString().slice(0, 7);
  const [statementMonth, setStatementMonth] = useState(month);
  const [currency, setCurrency] = useState("USD");

  useEffect(() => {
    api<Summary>(`/earnings/summary?currency=${currency}`).then(setS).catch((e) => setError(e.message));
  }, [currency]);

  useEffect(() => {
    Promise.all([
      api<{ items: Row[] }>("/earnings?page_size=100"),
      api<PayoutRow[]>("/payouts"),
      api("/payouts/account").catch(() => null), // refreshes the account state from the provider
    ]).then(([r, p]) => { setRows(r.items); setPayouts(p); }).catch((e) => setError(e.message));
  }, []);

  const onboard = async () => {
    try {
      const r = await api<{ url: string }>("/payouts/account/onboard", { method: "POST", json: { country } });
      window.location.href = r.url;
    } catch (e) {
      setError((e as Error).message);
    }
  };

  if (!s) return <p className="text-ink-300">{error || "Loading earnings…"}</p>;
  const acct = s.payout_account;

  return (
    <div className="space-y-8">
      {error && <Alert>{error}</Alert>}
      {s.currencies.length > 1 && (
        <div className="flex items-center gap-2 text-sm">
          <label htmlFor="ecur" className="text-ink-300">Currency</label>
          <select id="ecur" className="input w-auto py-1" value={s.currency} onChange={(e) => setCurrency(e.target.value)}>
            {s.currencies.map((c) => <option key={c}>{c}</option>)}
          </select>
          <span className="text-xs text-ink-400">Balances and payouts are kept separately per currency.</span>
        </div>
      )}
      <dl className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        {[
          ["Pending", s.pending_cents, `Held ${s.hold_days} days for refunds and chargebacks`],
          ["Available", s.available_cents, `Paid out when at least ${money(s.min_payout_cents, s.currency)}`],
          ["Paid out", s.paid_cents, "Transferred to your payout account"],
          ["Lifetime", s.lifetime_cents, Object.entries(s.by_kind).map(([k, v]) => `${label(k)} ${money(v, s.currency)}`).join(" · ") || "No sales yet"],
        ].map(([k, v, hint]) => (
          <div key={k as string} className="card p-5">
            <dt className="text-sm text-ink-400">{k}</dt>
            <dd className={`font-display mt-1 text-3xl ${(v as number) < 0 ? "text-red-300" : ""}`}>{money(v as number, s.currency)}</dd>
            <p className="mt-1 text-xs text-ink-400">{hint}</p>
          </div>
        ))}
      </dl>
      {s.next_release_at && <p className="text-xs text-ink-400">Next earnings become available on {new Date(s.next_release_at).toLocaleDateString()}.</p>}

      <section className="card space-y-3 p-6">
        <h2 className="font-display text-xl">Payout account</h2>
        {acct?.status === "enabled" ? (
          <p className="text-sm text-emerald-300">Payouts enabled. Available earnings are transferred automatically.</p>
        ) : (
          <>
            <p className="text-sm text-ink-300">
              {acct ? `Status: ${label(acct.status)}. ${acct.requirements_due.length ? "More information is required by our payment provider." : ""}` :
                "Connect a payout account to receive your earnings. Identity verification and bank details are handled securely by our payment provider."}
            </p>
            <div className="flex flex-wrap items-end gap-2">
              {!acct && (
                <div>
                  <label htmlFor="country" className="label">Country</label>
                  <input id="country" className="input w-24" maxLength={2} value={country} onChange={(e) => setCountry(e.target.value.toUpperCase())} />
                </div>
              )}
              <button className="btn-gold" onClick={onboard}>{acct ? "Continue setup" : "Set up payouts"}</button>
            </div>
          </>
        )}
        {acct && (
          <p className="text-xs text-ink-400">
            Tax information: <span className={acct.tax_info_status === "required" ? "text-amber-300" : acct.tax_info_status === "provided" ? "text-emerald-300" : ""}>
              {{ required: "action required", provided: "provided", pending: "not yet submitted" }[acct.tax_info_status] ?? acct.tax_info_status}
            </span>. Tax forms (W-9 / W-8) are collected by our payment provider during payout setup{acct.tax_info_status === "required" ? "; use “Continue setup” to complete them" : ""}.
          </p>
        )}
      </section>

      <section className="space-y-3">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <h2 className="font-display text-xl">Earnings activity</h2>
          <div className="flex items-end gap-2">
            <div>
              <label htmlFor="month" className="label">Statement month</label>
              <input id="month" type="month" className="input" value={statementMonth} onChange={(e) => setStatementMonth(e.target.value)} />
            </div>
            <a className="btn-ghost text-sm" href={`/api/v1/earnings/statement.csv?month=${statementMonth}`}>Download CSV</a>
          </div>
        </div>
        {rows.length === 0 ? <p className="card p-8 text-center text-ink-300">No earnings yet.</p> : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="text-ink-400"><tr><th className="p-2">Date</th><th className="p-2">Media</th><th className="p-2">Type</th><th className="p-2">Sale</th><th className="p-2">You</th><th className="p-2">Status</th><th className="p-2"><span className="sr-only">Details</span></th></tr></thead>
              <tbody>
                {rows.map((r) => (
                  <Fragment key={r.id}>
                    <tr className="border-t border-ink-800">
                      <td className="p-2">{new Date(r.created_at).toLocaleDateString()}</td>
                      <td className="p-2">{r.asset_title}<span className="block text-xs text-ink-400">{r.license_name}</span></td>
                      <td className="p-2">{label(r.kind)}{r.is_clawback && <span className="block text-xs text-red-300">Refund clawback</span>}</td>
                      <td className="p-2">{money(r.gross_cents, r.currency)}</td>
                      <td className={`p-2 font-semibold ${r.amount_cents < 0 ? "text-red-300" : "text-gold-300"}`}>{money(r.amount_cents, r.currency)}</td>
                      <td className="p-2">{label(r.status)}{r.status === "pending" && <span className="block text-xs text-ink-400">until {new Date(r.available_at).toLocaleDateString()}</span>}</td>
                      <td className="p-2"><button className="text-xs text-gold-300 underline" aria-expanded={open === r.id} onClick={() => setOpen(open === r.id ? null : r.id)}>How calculated</button></td>
                    </tr>
                    {open === r.id && (
                      <tr><td colSpan={7} className="bg-ink-950 p-3"><pre className="whitespace-pre-wrap text-xs text-ink-200">{r.explanation.join("\n")}</pre></td></tr>
                    )}
                  </Fragment>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {payouts.length > 0 && (
        <section className="space-y-3">
          <h2 className="font-display text-xl">Payouts</h2>
          <ul className="space-y-2 text-sm">
            {payouts.map((p) => (
              <li key={p.id} className="card flex justify-between p-3">
                <span>{new Date(p.created_at).toLocaleDateString()} · {label(p.status)}{p.failure_reason && <span className="block text-xs text-red-300">{p.failure_reason}</span>}</span>
                <span className="font-semibold">{money(p.amount_cents, p.currency)}</span>
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}
