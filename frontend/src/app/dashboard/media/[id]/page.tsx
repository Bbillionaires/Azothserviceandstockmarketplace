"use client";

import Link from "next/link";
import { useParams, useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useState } from "react";
import { Alert } from "@/components/Alert";
import { api, label, money } from "@/lib/api";
import type { LicenseType, MediaDetail } from "@/lib/types";

type Row = { license_code: string; size_tier: string; price: string; subscription_credit_eligible: boolean };
type Decision = { id: string; action: string; reason: string; created_at: string };

function Manage() {
  const { id } = useParams<{ id: string }>();
  const uploaded = useSearchParams().get("uploaded");
  const [m, setM] = useState<MediaDetail | null>(null);
  const [types, setTypes] = useState<LicenseType[]>([]);
  const [free, setFree] = useState("");
  const [rows, setRows] = useState<Row[]>([]);
  const [decisions, setDecisions] = useState<Decision[]>([]);
  const [appeal, setAppeal] = useState("");
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);

  const load = useCallback(async () => {
    const d = await api<MediaDetail>(`/media/${id}`);
    setM(d);
    setFree(d.free_license_codes[0] ?? "");
    setRows(d.prices.map((p) => ({ license_code: p.license_code, size_tier: p.size_tier, price: (p.price_cents / 100).toFixed(2), subscription_credit_eligible: p.subscription_credit_eligible })));
    setDecisions(await api<Decision[]>(`/media/${id}/decisions`).catch(() => []));
  }, [id]);

  useEffect(() => {
    load().catch((e) => setMsg({ ok: false, text: e.message }));
    api<LicenseType[]>("/license-types").then(setTypes);
  }, [load]);

  useEffect(() => {
    if (m?.status !== "processing") return;
    const t = setTimeout(load, 2500);
    return () => clearTimeout(t);
  }, [m, load]);

  if (!m) return <p className="p-10 text-center text-ink-300">{msg?.text ?? "Loading…"}</p>;

  const paidTypes = types.filter((t) => !t.is_free && !t.is_exclusive && t.code !== "negotiated" && !(m.is_editorial_only && t.allows_commercial_use));
  const freeTypes = types.filter((t) => t.is_free && !(m.is_editorial_only && t.allows_commercial_use));

  const savePricing = async () => {
    try {
      const prices = rows.map((r) => ({ license_code: r.license_code, size_tier: r.size_tier, price_cents: Math.round(Number(r.price) * 100), currency: "USD", subscription_credit_eligible: r.subscription_credit_eligible }));
      setM(await api<MediaDetail>(`/media/${id}/pricing`, { method: "PUT", json: { free_license_code: free || null, prices } }));
      setMsg({ ok: true, text: "Pricing saved." });
    } catch (e) {
      setMsg({ ok: false, text: (e as Error).message });
    }
  };

  const act = async (fn: () => Promise<unknown>, text: string) => {
    try { await fn(); setMsg({ ok: true, text }); await load(); } catch (e) { setMsg({ ok: false, text: (e as Error).message }); }
  };

  const thumb = m.files.find((f) => f.kind === "preview" && f.content_type.startsWith("image")) ?? m.files.find((f) => f.kind === "poster");
  const latest = decisions[0];

  return (
    <div className="mx-auto max-w-5xl px-4 py-10">
      <Link href="/dashboard" className="text-sm text-ink-300 hover:text-gold-300">← Dashboard</Link>
      <div className="mt-4 grid gap-8 md:grid-cols-[320px_1fr]">
        <div>
          {thumb
            // eslint-disable-next-line @next/next/no-img-element
            ? <img src={thumb.url} alt="" className="w-full rounded-xl border border-ink-800" />
            : <div className="grid aspect-video place-items-center rounded-xl bg-ink-800 text-sm text-ink-300">{m.status === "processing" ? "Processing…" : "No preview"}</div>}
          <h1 className="font-display mt-4 text-2xl">{m.title}</h1>
          <p className="text-sm text-ink-300">Status: <strong>{label(m.status)}</strong></p>
          {m.processing_error && <p className="mt-2 text-sm text-red-300">{m.processing_error}</p>}
          {m.rejection_reason && <p className="mt-2 text-sm text-amber-300">Reviewer note: {m.rejection_reason}</p>}
          {m.status === "approved" && <Link className="mt-3 inline-block text-sm text-gold-300 underline" href={`/media/${m.id}`}>View public page</Link>}
          <div className="mt-4 flex flex-wrap gap-2">
            {["approved", "pending_review"].includes(m.status) && (
              <button className="btn-ghost text-sm" onClick={() => act(() => api(`/media/${id}/withdraw`, { method: "POST" }), "Withdrawn. Existing licenses remain valid.")}>Withdraw from sale</button>
            )}
            {["withdrawn", "changes_requested"].includes(m.status) && (
              <button className="btn-ghost text-sm" onClick={() => act(() => api(`/media/${id}/resubmit`, { method: "POST" }), "Resubmitted for review.")}>Resubmit for review</button>
            )}
          </div>
        </div>
        <div className="space-y-6">
          {uploaded && <Alert kind="success">Upload received. We generate watermarked previews, then a moderator reviews it.</Alert>}
          {msg && <Alert kind={msg.ok ? "success" : "error"}>{msg.text}</Alert>}

          <section className="card space-y-4 p-6" aria-labelledby="pricing-title">
            <h2 id="pricing-title" className="font-display text-xl">Pricing & licenses</h2>
            <p className="text-sm text-ink-300">You set every price. The platform never changes your prices without your action.</p>
            <div>
              <label htmlFor="free" className="label">Free distribution</label>
              <select id="free" className="input" value={free} onChange={(e) => setFree(e.target.value)}>
                <option value="">Not offered free</option>
                {freeTypes.map((t) => <option key={t.code} value={t.code}>{t.name}</option>)}
              </select>
            </div>
            <div className="space-y-2">
              <p className="label">Paid licenses</p>
              {rows.map((r, i) => (
                <div key={i} className="grid grid-cols-[1fr_110px_110px_auto] items-center gap-2">
                  <select aria-label="License" className="input" value={r.license_code} onChange={(e) => setRows(rows.map((x, j) => j === i ? { ...x, license_code: e.target.value } : x))}>
                    {paidTypes.map((t) => <option key={t.code} value={t.code}>{t.name}</option>)}
                  </select>
                  <select aria-label="Size" className="input" value={r.size_tier} onChange={(e) => setRows(rows.map((x, j) => j === i ? { ...x, size_tier: e.target.value } : x))}>
                    {["original", "web", "hd", "4k", "8k"].map((s) => <option key={s} value={s}>{label(s)}</option>)}
                  </select>
                  <input aria-label="Price in USD" className="input" type="number" min="1" step="0.01" value={r.price} onChange={(e) => setRows(rows.map((x, j) => j === i ? { ...x, price: e.target.value } : x))} />
                  <button className="text-sm text-ink-400 hover:text-red-300" onClick={() => setRows(rows.filter((_, j) => j !== i))} aria-label="Remove price">✕</button>
                </div>
              ))}
              {paidTypes.length > 0 && (
                <button className="btn-ghost text-sm" onClick={() => setRows([...rows, { license_code: paidTypes[0].code, size_tier: "original", price: "29.00", subscription_credit_eligible: false }])}>+ Add price</button>
              )}
            </div>
            <button className="btn-gold" onClick={savePricing}>Save pricing</button>
            {m.prices.length > 0 && <p className="text-xs text-ink-400">Current: {m.prices.map((p) => `${p.license_name} ${money(p.price_cents, p.currency)}`).join(" · ")}</p>}
          </section>

          {decisions.length > 0 && (
            <section className="card space-y-3 p-6" aria-labelledby="history-title">
              <h2 id="history-title" className="font-display text-xl">Review history</h2>
              <ul className="space-y-2 text-sm">
                {decisions.map((d) => <li key={d.id}><strong>{label(d.action)}</strong> · {new Date(d.created_at).toLocaleString()} {d.reason && `— ${d.reason}`}</li>)}
              </ul>
              {latest && ["reject", "disable"].includes(latest.action) && (
                <div className="space-y-2">
                  <label htmlFor="appeal" className="label">Appeal this decision</label>
                  <textarea id="appeal" className="input" value={appeal} onChange={(e) => setAppeal(e.target.value)} />
                  <button className="btn-ghost text-sm" onClick={() => act(() => api("/appeals", { method: "POST", json: { decision_id: latest.id, statement: appeal } }), "Appeal submitted.")}>Submit appeal</button>
                </div>
              )}
            </section>
          )}
        </div>
      </div>
    </div>
  );
}

export default function ManageMediaPage() {
  return <Suspense><Manage /></Suspense>;
}
