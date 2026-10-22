"use client";

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { Alert } from "@/components/Alert";
import { api, label } from "@/lib/api";
import { hasRole, useSession } from "@/lib/session";
import { DisputesPanel } from "./DisputesPanel";
import { FinancePanel } from "./FinancePanel";

type QueueItem = {
  id: string; title: string; media_type: string; category: string; status: string; thumbnail_url: string | null;
  preview_url: string | null; creator_handle: string; created_at: string; scan_status: string;
  automated_signals: Record<string, unknown>; declaration: Record<string, unknown> | null;
};
type Complaint = { id: string; asset_id: string; complainant_name: string; work: string; status: string; counter_notice: unknown; created_at: string };
type Appeal = { id: string; asset_id: string; action: string; reason: string; statement: string };
type Tab = "queue" | "complaints" | "appeals" | "stats" | "finance" | "disputes";

export default function AdminPage() {
  const { user, loading } = useSession();
  const router = useRouter();
  const [tab, setTab] = useState<Tab | null>(null);
  const [queue, setQueue] = useState<QueueItem[]>([]);
  const [complaints, setComplaints] = useState<Complaint[]>([]);
  const [appeals, setAppeals] = useState<Appeal[]>([]);
  const [stats, setStats] = useState<Record<string, unknown> | null>(null);
  const [reasons, setReasons] = useState<Record<string, string>>({});
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);

  const load = useCallback(async () => {
    const [q, c, a, s] = await Promise.all([
      api<{ items: QueueItem[] }>("/admin/moderation/queue"),
      api<Complaint[]>("/admin/complaints"),
      api<Appeal[]>("/admin/appeals"),
      api<Record<string, unknown>>("/admin/stats"),
    ]);
    setQueue(q.items); setComplaints(c); setAppeals(a); setStats(s);
  }, []);

  useEffect(() => {
    if (loading) return;
    if (!hasRole(user, "moderator", "finance_admin")) { router.push("/"); return; }
    if (hasRole(user, "moderator")) load().catch((e) => setMsg({ ok: false, text: e.message }));
  }, [user, loading, router, load]);

  const act = async (fn: () => Promise<{ detail: string }>) => {
    try { setMsg({ ok: true, text: (await fn()).detail }); await load(); } catch (e) { setMsg({ ok: false, text: (e as Error).message }); }
  };

  if (loading || !hasRole(user, "moderator", "finance_admin")) return <p className="p-10 text-center text-ink-300">Loading…</p>;
  const tabs: [Tab, string][] = [
    ...(hasRole(user, "moderator") ? [["queue", `Review queue (${queue.length})`], ["complaints", `Copyright (${complaints.length})`],
      ["appeals", `Appeals (${appeals.length})`], ["stats", "Overview"]] as [Tab, string][] : []),
    ["disputes", "Project disputes"],
    ...(hasRole(user, "finance_admin") ? [["finance", "Finance"]] as [Tab, string][] : []),
  ];
  const current = tab ?? tabs[0][0];

  return (
    <div className="mx-auto max-w-7xl px-4 py-10">
      <h1 className="font-display text-4xl">Control center</h1>
      <p className="text-sm text-ink-300">Automated signals are advisory. Decide on the evidence; never remove lawful content on an unverified allegation.</p>
      <div role="tablist" className="mt-8 flex gap-2 border-b border-ink-800">
        {tabs.map(([t, l]) => (
          <button key={t} role="tab" aria-selected={current === t} onClick={() => setTab(t)} className={`-mb-px border-b-2 px-4 py-2 text-sm ${current === t ? "border-gold-500 text-gold-300" : "border-transparent text-ink-300"}`}>{l}</button>
        ))}
      </div>
      {msg && <div className="mt-4"><Alert kind={msg.ok ? "success" : "error"}>{msg.text}</Alert></div>}

      {current === "queue" && (
        <div className="mt-6 space-y-4">
          {queue.length === 0 && <p className="text-ink-300">Queue is empty.</p>}
          {queue.map((q) => (
            <div key={q.id} className="card grid gap-5 p-5 md:grid-cols-[260px_1fr]">
              {q.media_type === "video" && q.preview_url
                ? <video src={q.preview_url} poster={q.thumbnail_url ?? undefined} controls muted className="w-full rounded-lg" />
                // eslint-disable-next-line @next/next/no-img-element
                : <img src={q.preview_url ?? q.thumbnail_url ?? ""} alt="" className="w-full rounded-lg" />}
              <div className="space-y-3 text-sm">
                <p className="font-display text-xl">{q.title}</p>
                <p className="text-ink-300">@{q.creator_handle} · {label(q.media_type)} · {label(q.category)} · scan: {q.scan_status}</p>
                {q.declaration && (
                  <p className="text-ink-300">Declared owner: {String(q.declaration.rights_owner_name)} · original author: {q.declaration.is_original_author ? "yes" : "no"}
                    {q.declaration.existing_licenses_disclosure ? ` · disclosed: ${String(q.declaration.existing_licenses_disclosure)}` : ""}</p>
                )}
                {Object.keys(q.automated_signals).length > 0 && (
                  <ul className="rounded-lg border border-amber-500/30 bg-amber-500/5 p-3 text-amber-200">
                    {Object.entries(q.automated_signals).map(([k, v]) => <li key={k}><strong>{label(k)}:</strong> {Array.isArray(v) ? `${v.length} match(es)` : String(v)}</li>)}
                  </ul>
                )}
                <textarea aria-label="Reason" className="input" placeholder="Reason (required unless approving)" value={reasons[q.id] ?? ""} onChange={(e) => setReasons({ ...reasons, [q.id]: e.target.value })} />
                <div className="flex flex-wrap gap-2">
                  {(["approve", "request_changes", "reject"] as const).map((a) => (
                    <button key={a} className={a === "approve" ? "btn-gold text-sm" : "btn-ghost text-sm"}
                      onClick={() => act(() => api(`/admin/media/${q.id}/decision`, { method: "POST", json: { action: a, reason: reasons[q.id] ?? "" } }))}>
                      {label(a)}
                    </button>
                  ))}
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      {current === "complaints" && (
        <div className="mt-6 space-y-4">
          {complaints.length === 0 && <p className="text-ink-300">No complaints.</p>}
          {complaints.map((c) => (
            <div key={c.id} className="card space-y-2 p-5 text-sm">
              <p><strong>{c.complainant_name}</strong> · {label(c.status)} · <a className="underline" href={`/media/${c.asset_id}`}>asset</a></p>
              <p className="text-ink-300">{c.work}</p>
              {c.counter_notice ? <p className="text-sky-300">Counter-notice received.</p> : null}
              <div className="flex flex-wrap gap-2">
                {["under_review", "content_disabled", "rejected", "restored", "closed"].map((s) => (
                  <button key={s} className="btn-ghost text-xs" onClick={() => act(() => api(`/admin/complaints/${c.id}/status`, { method: "POST", json: { status: s, note: reasons[c.id] ?? "" } }))}>{label(s)}</button>
                ))}
              </div>
              <input aria-label="Note" className="input" placeholder="Internal note" value={reasons[c.id] ?? ""} onChange={(e) => setReasons({ ...reasons, [c.id]: e.target.value })} />
            </div>
          ))}
        </div>
      )}

      {current === "appeals" && (
        <div className="mt-6 space-y-4">
          {appeals.length === 0 && <p className="text-ink-300">No open appeals.</p>}
          {appeals.map((a) => (
            <div key={a.id} className="card space-y-2 p-5 text-sm">
              <p>Original decision: <strong>{label(a.action)}</strong> — {a.reason} · <a className="underline" href={`/media/${a.asset_id}`}>asset</a></p>
              <p className="text-ink-200">Creator: “{a.statement}”</p>
              <input aria-label="Resolution note" className="input" value={reasons[a.id] ?? ""} onChange={(e) => setReasons({ ...reasons, [a.id]: e.target.value })} placeholder="Resolution note" />
              <div className="flex gap-2">
                <button className="btn-gold text-sm" onClick={() => act(() => api(`/admin/appeals/${a.id}/resolve`, { method: "POST", json: { overturn: true, note: reasons[a.id] ?? "" } }))}>Overturn</button>
                <button className="btn-ghost text-sm" onClick={() => act(() => api(`/admin/appeals/${a.id}/resolve`, { method: "POST", json: { overturn: false, note: reasons[a.id] ?? "" } }))}>Uphold</button>
              </div>
            </div>
          ))}
        </div>
      )}

      {current === "finance" && <FinancePanel />}
      {current === "disputes" && <DisputesPanel />}

      {current === "stats" && stats && (
        <pre className="card mt-6 overflow-x-auto p-5 text-sm text-ink-200">{JSON.stringify(stats, null, 2)}</pre>
      )}
    </div>
  );
}
