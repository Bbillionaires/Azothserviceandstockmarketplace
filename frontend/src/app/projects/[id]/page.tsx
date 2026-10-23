"use client";

import Link from "next/link";
import { useParams, useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useState } from "react";
import { Alert } from "@/components/Alert";
import { Thread } from "@/components/Thread";
import { api, label, money } from "@/lib/api";
import { RIGHTS_LABEL, fileSize, type Project, type ProjectMilestone } from "@/lib/production";
import { uploadFile } from "@/lib/upload";

const STATUS_STYLE: Record<string, string> = {
  unfunded: "text-ink-300", funded: "text-sky-300", submitted: "text-gold-300", revision_requested: "text-amber-300",
  approved: "text-emerald-300", refunded: "text-ink-400", canceled: "text-ink-400", disputed: "text-red-300",
};

function ProjectView() {
  const { id } = useParams<{ id: string }>();
  const funded = useSearchParams().get("funded");
  const [p, setP] = useState<Project | null>(null);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [tries, setTries] = useState(0);

  const load = useCallback(async () => setP(await api<Project>(`/projects/${id}`)), [id]);
  useEffect(() => { load().catch((e) => setMsg({ ok: false, text: e.message })); }, [load]);

  // After checkout, wait for the payment webhook to mark the milestone funded.
  useEffect(() => {
    if (!funded || !p) return;
    const m = p.milestones.find((x) => x.id === funded);
    if (m?.status === "unfunded" && tries < 15) {
      const t = setTimeout(() => { setTries(tries + 1); load(); }, 1500);
      return () => clearTimeout(t);
    }
  }, [funded, p, tries, load]);

  const act = async (fn: () => Promise<unknown>, ok: string) => {
    try { await fn(); setMsg({ ok: true, text: ok }); await load(); } catch (e) { setMsg({ ok: false, text: (e as Error).message }); }
  };

  if (!p) return <p className="p-10 text-center text-ink-300">{msg?.text ?? "Loading project…"}</p>;
  const isClient = p.role === "client";
  const isCreator = p.role === "creator";
  const myReview = p.reviews.find((r) => r.direction === (isClient ? "client_to_creator" : "creator_to_client"));

  return (
    <div className="mx-auto max-w-6xl px-4 py-10">
      <p className="text-xs uppercase tracking-[0.25em] text-gold-400">Project · {label(p.status)}</p>
      <h1 className="font-display mt-2 text-4xl">{p.title}</h1>
      <p className="mt-1 text-sm text-ink-300">
        Client: {p.client_name} · Creator: <Link className="text-gold-300" href={`/creators/${p.creator.handle}`}>{p.creator.display_name}</Link> · {money(p.total_cents, p.currency)}
      </p>
      {funded && p.milestones.find((x) => x.id === funded)?.status === "unfunded" && <div className="mt-4"><Alert kind="info">Confirming your payment…</Alert></div>}
      {msg && <div className="mt-4"><Alert kind={msg.ok ? "success" : "error"}>{msg.text}</Alert></div>}

      <div className="mt-8 grid gap-8 lg:grid-cols-[1fr_360px]">
        <div className="space-y-4">
          {p.description && <p className="whitespace-pre-line text-ink-200">{p.description}</p>}
          <h2 className="font-display text-2xl">Milestones</h2>
          {p.milestones.map((m) => (
            <MilestoneCard key={m.id} m={m} project={p} act={act} isClient={isClient} isCreator={isCreator} />
          ))}
          {isClient && p.status === "active" && <AddMilestone projectId={p.id} act={act} />}

          {p.disputes.length > 0 && (
            <section className="card space-y-2 p-5 text-sm">
              <h2 className="font-display text-lg">Disputes</h2>
              {p.disputes.map((d) => (
                <div key={d.id} className="border-t border-ink-700 pt-2 first:border-0 first:pt-0">
                  <p><strong>{label(d.status)}</strong> · {label(d.reason)} · {new Date(d.created_at).toLocaleDateString()}</p>
                  <p className="text-ink-300">{d.description}</p>
                  {d.resolution_note && <p className="text-ink-300">Resolution: {d.resolution_note}</p>}
                  {d.status === "open" && d.opened_by_me && (
                    <button className="mt-1 text-xs text-gold-300 underline" onClick={() => act(() => api(`/disputes/${d.id}/withdraw`, { method: "POST" }), "Dispute withdrawn")}>Withdraw dispute</button>
                  )}
                </div>
              ))}
            </section>
          )}

          {p.status === "completed" && (isClient || isCreator) && (
            <section className="card space-y-3 p-5">
              <h2 className="font-display text-lg">Reviews</h2>
              {p.reviews.map((r, i) => (
                <p key={i} className="text-sm"><span className="text-gold-300">{"★".repeat(r.rating)}</span> {r.body} <span className="text-xs text-ink-400">({r.direction === "client_to_creator" ? "client" : "creator"})</span></p>
              ))}
              {!myReview && <ReviewForm projectId={p.id} act={act} />}
            </section>
          )}
        </div>

        <aside className="space-y-4">
          <div className="card space-y-2 p-5 text-sm">
            <h2 className="font-display text-lg">Agreed rights</h2>
            <p><strong>{RIGHTS_LABEL[p.rights_type]}</strong></p>
            <p className="whitespace-pre-line text-ink-300">{p.rights_terms}</p>
            <p className="text-xs text-ink-400">
              Accepted {p.acceptance_evidence.client_accepted_at ? new Date(String(p.acceptance_evidence.client_accepted_at)).toLocaleString() : ""}.
              {" "}{p.revisions_included} revision{p.revisions_included === 1 ? "" : "s"} per milestone. Commissioned work is not resold as stock.
            </p>
          </div>
          <div className="card space-y-2 p-5 text-xs text-ink-300">
            <p><strong className="text-white">How payment works.</strong> The client funds each milestone before work starts. Funds are held by our payment provider until the client approves the delivery (or automatically after {p.auto_approve_days} days without a response).</p>
            {isCreator && <p>A {p.commission_percent}% platform commission is deducted when a milestone is released.</p>}
          </div>
          {p.conversation_id && (isClient || isCreator) && (
            <div className="card p-4">
              <h2 className="font-display mb-3 text-lg">Messages</h2>
              <Thread conversationId={p.conversation_id} compact />
            </div>
          )}
          {p.status === "active" && (isClient || isCreator) && (
            <button className="btn-ghost w-full text-sm" onClick={() => confirm("Cancel this project? Funded milestones must be refunded or disputed first.") && act(() => api(`/projects/${p.id}/cancel`, { method: "POST" }), "Project canceled")}>Cancel project</button>
          )}
        </aside>
      </div>
    </div>
  );
}

function MilestoneCard({ m, project, act, isClient, isCreator }: {
  m: ProjectMilestone; project: Project; act: (fn: () => Promise<unknown>, ok: string) => void; isClient: boolean; isCreator: boolean;
}) {
  const [note, setNote] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [disputing, setDisputing] = useState(false);
  const [reason, setReason] = useState("quality");
  const held = ["funded", "submitted", "revision_requested"].includes(m.status);

  const [progress, setProgress] = useState<number | null>(null);
  const upload = async () => {
    if (!file) return;
    setProgress(0);
    try {
      const uploadId = await uploadFile(file, "deliverable", m.id, setProgress);
      await api(`/milestones/${m.id}/deliverables/from-upload`, { method: "POST", json: { upload_id: uploadId, note } });
      setFile(null);
    } finally {
      setProgress(null);
    }
  };

  const download = async (id: string) => {
    const r = await api<{ url: string }>(`/deliverables/${id}/link`, { method: "POST" });
    window.location.href = r.url;
  };

  return (
    <div className="card space-y-3 p-5">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <p className="font-medium">{m.position + 1}. {m.title}</p>
          <p className="text-xs text-ink-400">{m.due_date ? `Due ${new Date(m.due_date).toLocaleDateString()} · ` : ""}{m.revisions_used}/{project.revisions_included} revisions used</p>
        </div>
        <div className="text-right">
          <p className="font-semibold">{money(m.amount_cents, project.currency)}</p>
          <p className={`text-xs ${STATUS_STYLE[m.status] ?? ""}`}>{label(m.status)}</p>
        </div>
      </div>
      {m.description && <p className="whitespace-pre-line text-sm text-ink-300">{m.description}</p>}
      {m.status === "submitted" && m.auto_approve_at && <p className="text-xs text-ink-400">Approves automatically on {new Date(m.auto_approve_at).toLocaleDateString()} unless the client responds.</p>}
      {m.revision_requests.map((r, i) => <p key={i} className="rounded bg-amber-500/10 p-2 text-xs text-amber-200">Revision requested: {r.note}</p>)}
      {m.deliverables.length > 0 && (
        <ul className="space-y-1 text-sm">
          {m.deliverables.map((d) => (
            <li key={d.id} className="flex items-center justify-between gap-2">
              <span>{d.filename} <span className="text-xs text-ink-400">{fileSize(d.size_bytes)}{d.note ? ` · ${d.note}` : ""}</span></span>
              {d.scan_status === "pending"
                ? <span className="text-xs text-ink-400">Checking file…</span>
                : <button className="text-xs text-gold-300 underline" onClick={() => download(d.id)}>Download</button>}
            </li>
          ))}
        </ul>
      )}

      <div className="flex flex-wrap gap-2">
        {isClient && m.status === "unfunded" && project.status === "active" && (
          <button className="btn-gold text-sm" onClick={() => act(async () => {
            const r = await api<{ checkout_url: string }>(`/milestones/${m.id}/fund`, { method: "POST" });
            window.location.href = r.checkout_url;
          }, "Redirecting to payment…")}>Fund milestone</button>
        )}
        {isClient && m.status === "submitted" && (
          <>
            <button className="btn-gold text-sm" onClick={() => confirm(`Approve and release ${money(m.amount_cents, project.currency)} to the creator?`) && act(() => api(`/milestones/${m.id}/approve`, { method: "POST" }), "Approved and released")}>Approve &amp; release</button>
            <button className="btn-ghost text-sm" disabled={m.revisions_used >= project.revisions_included}
              onClick={() => { const n = prompt("What should change?"); if (n) act(() => api(`/milestones/${m.id}/revision`, { method: "POST", json: { note: n } }), "Revision requested"); }}>
              Request revision
            </button>
          </>
        )}
        {isCreator && ["funded", "revision_requested"].includes(m.status) && (
          <div className="w-full space-y-2 rounded-lg border border-ink-700 p-3">
            <label htmlFor={`f-${m.id}`} className="label">Upload deliverable</label>
            <input id={`f-${m.id}`} type="file" className="text-sm" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
            <input aria-label="Delivery note" className="input py-1 text-sm" placeholder="Note for the client (optional)" value={note} onChange={(e) => setNote(e.target.value)} />
            <div className="flex gap-2">
              <button className="btn-ghost text-sm" disabled={!file || progress !== null} onClick={() => act(upload, "File uploaded")}>{progress !== null ? `Uploading ${progress}%` : "Upload"}</button>
              <button className="btn-gold text-sm" disabled={!m.deliverables.length} onClick={() => act(() => api(`/milestones/${m.id}/submit`, { method: "POST", json: { note } }), "Delivered to the client")}>Submit delivery</button>
            </div>
          </div>
        )}
        {isCreator && held && (
          <button className="btn-ghost text-sm" onClick={() => { const n = prompt("Refund this milestone to the client. Reason:"); if (n !== null) act(() => api(`/milestones/${m.id}/refund`, { method: "POST", json: { note: n } }), "Refunded"); }}>Refund client</button>
        )}
        {(isClient || isCreator) && held && !disputing && (
          <button className="text-xs text-red-300 underline" onClick={() => setDisputing(true)}>Open a dispute</button>
        )}
      </div>
      {disputing && (
        <div className="space-y-2 rounded-lg border border-red-500/30 p-3">
          <select aria-label="Reason" className="input py-1 text-sm" value={reason} onChange={(e) => setReason(e.target.value)}>
            {["not_delivered", "quality", "scope", "late", "unresponsive", "other"].map((r) => <option key={r} value={r}>{label(r)}</option>)}
          </select>
          <textarea aria-label="Describe the problem" className="input text-sm" placeholder="Describe the problem (at least 20 characters)" value={note} onChange={(e) => setNote(e.target.value)} />
          <p className="text-xs text-ink-400">Funds stay held while our team reviews. Try messaging the other party first.</p>
          <div className="flex gap-2">
            <button className="btn-gold text-sm" onClick={() => act(() => api(`/projects/${project.id}/disputes`, { method: "POST", json: { milestone_id: m.id, reason, description: note } }).then(() => setDisputing(false)), "Dispute opened")}>Submit dispute</button>
            <button className="btn-ghost text-sm" onClick={() => setDisputing(false)}>Cancel</button>
          </div>
        </div>
      )}
    </div>
  );
}

function AddMilestone({ projectId, act }: { projectId: string; act: (fn: () => Promise<unknown>, ok: string) => void }) {
  const [open, setOpen] = useState(false);
  const [title, setTitle] = useState("");
  const [amount, setAmount] = useState("");
  if (!open) return <button className="text-sm text-gold-300 underline" onClick={() => setOpen(true)}>+ Add a paid milestone (extra scope or revisions)</button>;
  return (
    <div className="card flex flex-wrap items-end gap-2 p-4">
      <div className="flex-1"><label htmlFor="am-t" className="label">Title</label><input id="am-t" className="input" value={title} onChange={(e) => setTitle(e.target.value)} /></div>
      <div className="w-32"><label htmlFor="am-a" className="label">Amount (USD)</label><input id="am-a" type="number" min="1" className="input" value={amount} onChange={(e) => setAmount(e.target.value)} /></div>
      <button className="btn-gold" onClick={() => act(() => api(`/projects/${projectId}/milestones`, { method: "POST", json: { title, amount_cents: Math.round(Number(amount) * 100) } }).then(() => setOpen(false)), "Milestone added")}>Add</button>
    </div>
  );
}

function ReviewForm({ projectId, act }: { projectId: string; act: (fn: () => Promise<unknown>, ok: string) => void }) {
  const [rating, setRating] = useState(5);
  const [body, setBody] = useState("");
  return (
    <div className="space-y-2">
      <fieldset className="flex gap-1" aria-label="Rating">
        {[1, 2, 3, 4, 5].map((n) => (
          <button key={n} type="button" aria-label={`${n} stars`} aria-pressed={rating === n} className={`text-2xl ${n <= rating ? "text-gold-400" : "text-ink-600"}`} onClick={() => setRating(n)}>★</button>
        ))}
      </fieldset>
      <textarea aria-label="Review" className="input text-sm" placeholder="How did it go?" value={body} onChange={(e) => setBody(e.target.value)} />
      <button className="btn-gold text-sm" onClick={() => act(() => api(`/projects/${projectId}/reviews`, { method: "POST", json: { rating, body } }), "Thanks for your review")}>Post review</button>
    </div>
  );
}

export default function ProjectPage() {
  return <Suspense><ProjectView /></Suspense>;
}
