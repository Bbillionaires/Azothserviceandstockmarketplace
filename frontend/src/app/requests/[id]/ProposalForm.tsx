"use client";

import { useState } from "react";
import { Alert } from "@/components/Alert";
import { api, label, money } from "@/lib/api";
import { RIGHTS_LABEL, type ProjectRequest, type ProposalMilestone } from "@/lib/production";

export function ProposalForm({ request, onSaved }: { request: ProjectRequest; onSaved: () => void }) {
  const mine = request.my_proposal;
  const [milestones, setMilestones] = useState<(ProposalMilestone & { amount: string })[]>(
    (mine?.milestones ?? [{ title: "Full delivery", amount_cents: 0, due_in_days: 7 }]).map((m) => ({ ...m, amount: m.amount_cents ? String(m.amount_cents / 100) : "" })),
  );
  const [cover, setCover] = useState(mine?.cover_letter ?? "");
  const [days, setDays] = useState(String(mine?.delivery_days ?? 14));
  const [revisions, setRevisions] = useState(String(mine?.revisions_included ?? 1));
  const [rights, setRights] = useState(mine?.rights_type ?? request.rights_preference);
  const [terms, setTerms] = useState(mine?.rights_terms ?? "");
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const total = milestones.reduce((a, m) => a + Math.round(Number(m.amount || 0) * 100), 0);
  const closed = request.status !== "open";

  if (mine && mine.status !== "submitted" && mine.status !== "withdrawn") {
    return <div className="card p-5 text-sm">Your proposal ({money(mine.total_cents, mine.currency)}) was <strong>{label(mine.status)}</strong>.</div>;
  }
  if (closed) return <div className="card p-5 text-sm text-ink-300">This request is no longer accepting proposals.</div>;

  const save = async () => {
    try {
      await api(`/requests/${request.id}/proposals`, {
        method: "POST",
        json: {
          cover_letter: cover, total_cents: total, delivery_days: Number(days), revisions_included: Number(revisions),
          rights_type: rights, rights_terms: terms,
          milestones: milestones.map((m) => ({ title: m.title, description: m.description ?? "", amount_cents: Math.round(Number(m.amount || 0) * 100), due_in_days: m.due_in_days ? Number(m.due_in_days) : null })),
        },
      });
      setMsg({ ok: true, text: mine ? "Proposal updated" : "Proposal sent. Only the client can see it." });
      onSaved();
    } catch (e) {
      setMsg({ ok: false, text: (e as Error).message });
    }
  };

  return (
    <div className="card space-y-4 p-5">
      <h2 className="font-display text-lg">{mine ? "Your proposal" : "Send a proposal"}</h2>
      {msg && <Alert kind={msg.ok ? "success" : "error"}>{msg.text}</Alert>}
      <div><label htmlFor="cover" className="label">Cover letter</label><textarea id="cover" className="input min-h-28" value={cover} onChange={(e) => setCover(e.target.value)} /></div>
      <div className="space-y-2">
        <p className="label">Milestones (paid one at a time)</p>
        {milestones.map((m, i) => (
          <div key={i} className="grid grid-cols-[1fr_90px_60px_auto] gap-2">
            <input aria-label="Milestone title" className="input py-1 text-sm" value={m.title} onChange={(e) => setMilestones(milestones.map((x, j) => j === i ? { ...x, title: e.target.value } : x))} />
            <input aria-label="Amount USD" type="number" min="1" className="input py-1 text-sm" placeholder="USD" value={m.amount} onChange={(e) => setMilestones(milestones.map((x, j) => j === i ? { ...x, amount: e.target.value } : x))} />
            <input aria-label="Due in days" type="number" min="0" className="input py-1 text-sm" placeholder="day" value={m.due_in_days ?? ""} onChange={(e) => setMilestones(milestones.map((x, j) => j === i ? { ...x, due_in_days: e.target.value ? Number(e.target.value) : null } : x))} />
            <button className="text-xs text-ink-400" aria-label="Remove milestone" onClick={() => setMilestones(milestones.filter((_, j) => j !== i))} disabled={milestones.length === 1}>✕</button>
          </div>
        ))}
        <button className="text-xs text-gold-300 underline" onClick={() => setMilestones([...milestones, { title: "", amount_cents: 0, amount: "", due_in_days: null }])}>+ Add milestone</button>
        <p className="text-sm">Total: <strong>{money(total, request.currency)}</strong></p>
      </div>
      <div className="grid grid-cols-2 gap-2">
        <div><label htmlFor="days" className="label">Delivery (days)</label><input id="days" type="number" min="1" className="input" value={days} onChange={(e) => setDays(e.target.value)} /></div>
        <div><label htmlFor="rev" className="label">Revisions</label><input id="rev" type="number" min="0" max="10" className="input" value={revisions} onChange={(e) => setRevisions(e.target.value)} /></div>
      </div>
      <div>
        <label htmlFor="rights" className="label">Rights offered</label>
        <select id="rights" className="input" value={rights} onChange={(e) => setRights(e.target.value)}>
          {Object.entries(RIGHTS_LABEL).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
        </select>
      </div>
      <div><label htmlFor="terms" className="label">Rights terms</label><textarea id="terms" className="input" value={terms} onChange={(e) => setTerms(e.target.value)}
        placeholder="e.g. Client receives exclusive worldwide rights for all uses; I may show the work in my portfolio." /></div>
      <p className="text-xs text-ink-400">The platform commission is deducted when each milestone is released. Rights terms become part of the booking if the client accepts.</p>
      <button className="btn-gold w-full" onClick={save}>{mine ? "Update proposal" : "Send proposal"}</button>
      {mine?.status === "submitted" && (
        <button className="btn-ghost w-full text-sm" onClick={() => api(`/proposals/${mine.id}/withdraw`, { method: "POST" }).then(onSaved)}>Withdraw</button>
      )}
    </div>
  );
}
