"use client";

import { useEffect, useState } from "react";
import { Alert } from "@/components/Alert";
import { api, money } from "@/lib/api";

type Stats = {
  code: string | null; link: string | null; referred_accounts: number; rejected_referrals: number;
  paying_customers: number; commission_cents: number; terms: string;
};

export function ReferralsPanel({ verified }: { verified: boolean }) {
  const [s, setS] = useState<Stats | null>(null);
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => { api<Stats>("/referrals/me").then(setS).catch((e) => setError(e.message)); }, []);
  if (!s) return <p className="text-ink-300">{error || "Loading…"}</p>;
  return (
    <div className="max-w-2xl space-y-5">
      {error && <Alert>{error}</Alert>}
      {s.link ? (
        <div className="card space-y-3 p-6">
          <p className="label">Your referral link</p>
          <div className="flex gap-2">
            <input className="input" readOnly value={s.link} aria-label="Referral link" />
            <button className="btn-gold" onClick={async () => { await navigator.clipboard.writeText(s.link!); setCopied(true); }}>{copied ? "Copied" : "Copy"}</button>
          </div>
        </div>
      ) : (
        <button className="btn-gold" disabled={!verified}
          onClick={async () => { try { setS(await api<Stats>("/referrals/code", { method: "POST" })); } catch (e) { setError((e as Error).message); } }}>
          Get my referral link
        </button>
      )}
      <dl className="grid grid-cols-3 gap-4">
        {[["Sign-ups", s.referred_accounts], ["Paying customers", s.paying_customers], ["Commission", money(s.commission_cents)]].map(([k, v]) => (
          <div key={k as string} className="card p-4"><dt className="text-xs text-ink-400">{k}</dt><dd className="font-display mt-1 text-2xl">{v}</dd></div>
        ))}
      </dl>
      <p className="text-sm text-ink-300">{s.terms}</p>
      <p className="text-xs text-ink-400">Commission earnings appear in the Earnings tab and follow the same hold and payout schedule. Only direct referrals count; there are no multi-level commissions.</p>
    </div>
  );
}
