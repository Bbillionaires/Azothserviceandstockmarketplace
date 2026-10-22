"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { Alert } from "@/components/Alert";
import { api, label, money } from "@/lib/api";

type D = { id: string; project_id: string; project_title: string; milestone: string; amount_cents: number; currency: string; reason: string; description: string; status: string; opened_by: string; created_at: string };

export function DisputesPanel() {
  const [rows, setRows] = useState<D[]>([]);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [form, setForm] = useState<Record<string, { outcome: string; share: string; note: string }>>({});
  const load = useCallback(() => api<D[]>("/admin/production/disputes").then(setRows).catch((e) => setMsg({ ok: false, text: e.message })), []);
  useEffect(() => { load(); }, [load]);

  return (
    <div className="mt-6 space-y-4">
      {msg && <Alert kind={msg.ok ? "success" : "error"}>{msg.text}</Alert>}
      {rows.length === 0 && <p className="text-ink-300">No open project disputes.</p>}
      {rows.map((d) => {
        const f = form[d.id] ?? { outcome: "release", share: "5000", note: "" };
        const set = (patch: Partial<typeof f>) => setForm({ ...form, [d.id]: { ...f, ...patch } });
        return (
          <div key={d.id} className="card space-y-3 p-5 text-sm">
            <p><Link className="font-medium text-gold-300" href={`/projects/${d.project_id}`}>{d.project_title}</Link> · {d.milestone} · {money(d.amount_cents, d.currency)} · opened by {d.opened_by} · {label(d.reason)}</p>
            <p className="text-ink-300">{d.description}</p>
            <div className="flex flex-wrap items-end gap-2">
              <select aria-label="Outcome" className="input w-auto" value={f.outcome} onChange={(e) => set({ outcome: e.target.value })}>
                <option value="release">Release to creator</option><option value="refund">Refund client</option><option value="split">Split</option>
              </select>
              {f.outcome === "split" && <input aria-label="Creator share in percent" className="input w-28" type="number" min="1" max="99" value={Number(f.share) / 100} onChange={(e) => set({ share: String(Math.round(Number(e.target.value) * 100)) })} />}
              {f.outcome === "split" && <span className="text-xs text-ink-400">% to creator</span>}
              <input aria-label="Resolution note" className="input flex-1" placeholder="Resolution note (shared with both parties)" value={f.note} onChange={(e) => set({ note: e.target.value })} />
              <button className="btn-gold text-sm" onClick={() => api(`/admin/production/disputes/${d.id}/resolve`, { method: "POST", json: { outcome: f.outcome, creator_share_bps: f.outcome === "split" ? Number(f.share) : null, note: f.note } })
                .then(() => { setMsg({ ok: true, text: "Dispute resolved" }); load(); }).catch((e) => setMsg({ ok: false, text: e.message }))}>Resolve</button>
            </div>
          </div>
        );
      })}
    </div>
  );
}
