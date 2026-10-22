"use client";

import Link from "next/link";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useState } from "react";
import { Alert } from "@/components/Alert";
import { api, label, money } from "@/lib/api";
import { RIGHTS_LABEL, budgetText, type Proposal, type ProjectRequest } from "@/lib/production";
import { useSession } from "@/lib/session";
import { ProposalForm } from "./ProposalForm";

type Match = {
  creator: { handle: string; display_name: string; headline: string; categories: string[]; city: string | null };
  score: number;
  reasons: string[];
  rating: { average: number; count: number };
};

function RequestDetail() {
  const { id } = useParams<{ id: string }>();
  const created = useSearchParams().get("created");
  const router = useRouter();
  const { user } = useSession();
  const [r, setR] = useState<ProjectRequest | null>(null);
  const [proposals, setProposals] = useState<Proposal[]>([]);
  const [matches, setMatches] = useState<Match[]>([]);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [invited, setInvited] = useState<Set<string>>(new Set());

  const load = useCallback(async () => {
    const req = await api<ProjectRequest>(`/requests/${id}`);
    setR(req);
    if (req.is_owner) {
      setProposals(await api<Proposal[]>(`/requests/${id}/proposals`));
      setMatches(await api<Match[]>(`/requests/${id}/matches`).catch(() => []));
    }
  }, [id]);

  useEffect(() => { load().catch((e) => setMsg({ ok: false, text: e.message })); }, [load, user]);

  const act = async (fn: () => Promise<unknown>, ok: string) => {
    try { await fn(); setMsg({ ok: true, text: ok }); await load(); } catch (e) { setMsg({ ok: false, text: (e as Error).message }); }
  };

  if (!r) return <p className="p-10 text-center text-ink-300">{msg?.text ?? "Loading…"}</p>;

  return (
    <div className="mx-auto max-w-6xl px-4 py-10">
      <Link href="/requests" className="text-sm text-ink-300 hover:text-gold-300">← All briefs</Link>
      {created && <div className="mt-4"><Alert kind="success">Your brief is live. Invite recommended creators below or wait for proposals.</Alert></div>}
      {msg && <div className="mt-4"><Alert kind={msg.ok ? "success" : "error"}>{msg.text}</Alert></div>}
      <div className="mt-4 grid gap-8 lg:grid-cols-[1fr_340px]">
        <article>
          <div className="flex flex-wrap gap-2 text-xs">
            {r.kind === "shot_request" && <span className="rounded-full bg-gold-500 px-2 py-0.5 font-semibold text-ink-950">Request This Shot</span>}
            <span className="rounded-full border border-ink-600 px-2 py-0.5">{label(r.category)}</span>
            <span className="rounded-full border border-ink-600 px-2 py-0.5">{label(r.status)}</span>
            {r.visibility === "invite_only" && <span className="rounded-full border border-ink-600 px-2 py-0.5">Invite only</span>}
          </div>
          <h1 className="font-display mt-3 text-4xl">{r.title}</h1>
          <p className="mt-1 text-sm text-ink-400">Posted by {r.client_name} · {new Date(r.created_at).toLocaleDateString()}</p>
          <p className="mt-6 whitespace-pre-line text-ink-200">{r.description}</p>
          {r.deliverables && <><h2 className="font-display mt-6 text-xl">Deliverables</h2><p className="mt-2 whitespace-pre-line text-ink-200">{r.deliverables}</p></>}
          {!!r.reference_urls?.length && (
            <ul className="mt-4 space-y-1 text-sm">{r.reference_urls.map((u) => <li key={u}><a className="text-gold-300 underline" href={u} rel="noopener nofollow ugc" target="_blank">{u}</a></li>)}</ul>
          )}

          {r.is_owner && (
            <section className="mt-10 space-y-4">
              <h2 className="font-display text-2xl">Proposals ({proposals.length})</h2>
              {proposals.length === 0 && <p className="text-ink-300">No proposals yet.</p>}
              {proposals.map((p) => (
                <div key={p.id} className="card space-y-3 p-5">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <Link href={`/creators/${p.creator.handle}`} className="font-medium hover:text-gold-300">
                      {p.creator.display_name}{p.creator.verification_status === "verified" && " ✓"}
                    </Link>
                    <span className="font-display text-2xl text-gold-300">{money(p.total_cents, p.currency)}</span>
                  </div>
                  <p className="text-xs text-ink-400">
                    {p.rating.count ? `${p.rating.average.toFixed(1)}★ (${p.rating.count}) · ` : ""}{p.rating.completed_projects} completed · delivers in {p.delivery_days} days · {p.revisions_included} revisions · {label(p.status)}
                  </p>
                  <p className="whitespace-pre-line text-sm text-ink-200">{p.cover_letter}</p>
                  <ol className="space-y-1 text-sm">
                    {p.milestones.map((m, i) => <li key={i} className="flex justify-between"><span>{i + 1}. {m.title}{m.due_in_days ? ` · day ${m.due_in_days}` : ""}</span><span>{money(m.amount_cents, p.currency)}</span></li>)}
                  </ol>
                  <p className="text-sm"><strong>Rights:</strong> {RIGHTS_LABEL[p.rights_type]}. <span className="text-ink-300">{p.rights_terms}</span></p>
                  {p.status === "submitted" && r.status === "open" && (
                    <div className="flex gap-2">
                      <button className="btn-gold text-sm" onClick={() => {
                        if (confirm(`Hire ${p.creator.display_name} for ${money(p.total_cents, p.currency)} on these rights terms?`)) {
                          api<{ project_id: string }>(`/proposals/${p.id}/accept`, { method: "POST" })
                            .then((x) => router.push(`/projects/${x.project_id}`))
                            .catch((e) => setMsg({ ok: false, text: e.message }));
                        }
                      }}>Accept &amp; hire</button>
                      <button className="btn-ghost text-sm" onClick={() => act(() => api(`/proposals/${p.id}/decline`, { method: "POST" }), "Declined")}>Decline</button>
                    </div>
                  )}
                </div>
              ))}
            </section>
          )}
        </article>

        <aside className="space-y-4">
          <dl className="card grid grid-cols-2 gap-3 p-5 text-sm">
            <dt className="text-ink-400">Budget</dt><dd>{budgetText(r, money)}</dd>
            <dt className="text-ink-400">Deadline</dt><dd>{r.deadline ? new Date(r.deadline).toLocaleDateString() : "Flexible"}</dd>
            <dt className="text-ink-400">Location</dt><dd>{[r.location_city, r.location_region, r.location_country].filter(Boolean).join(", ") || "Anywhere"}</dd>
            <dt className="text-ink-400">Remote OK</dt><dd>{r.remote_ok ? "Yes" : "No"}</dd>
            <dt className="text-ink-400">Rights wanted</dt><dd>{RIGHTS_LABEL[r.rights_preference]}</dd>
            <dt className="text-ink-400">Proposals</dt><dd>{r.proposal_count}</dd>
          </dl>

          {r.project_id && <Link href={`/projects/${r.project_id}`} className="btn-gold w-full">Open project</Link>}

          {r.is_owner && r.status === "open" && (
            <>
              <div className="card space-y-3 p-5">
                <h2 className="font-display text-lg">Recommended creators</h2>
                {matches.length === 0 && <p className="text-sm text-ink-300">No strong matches yet.</p>}
                {matches.map((m) => (
                  <div key={m.creator.handle} className="space-y-1 border-t border-ink-700 pt-3 text-sm first:border-0 first:pt-0">
                    <div className="flex items-center justify-between gap-2">
                      <Link href={`/creators/${m.creator.handle}`} className="font-medium hover:text-gold-300">{m.creator.display_name}</Link>
                      <button className="btn-ghost px-3 py-1 text-xs" disabled={invited.has(m.creator.handle)}
                        onClick={() => act(async () => { await api(`/requests/${r.id}/invite`, { method: "POST", json: { creator_handle: m.creator.handle, message: `Would you quote on “${r.title}”?` } }); setInvited(new Set([...invited, m.creator.handle])); }, `Invited ${m.creator.display_name}`)}>
                        {invited.has(m.creator.handle) ? "Invited" : "Invite"}
                      </button>
                    </div>
                    <p className="text-xs text-ink-400">{m.reasons.join(" · ")}</p>
                  </div>
                ))}
                <p className="text-xs text-ink-400">Matching uses specialty, location, availability, verification and verified reviews.</p>
              </div>
              <button className="btn-ghost w-full text-sm" onClick={() => act(() => api(`/requests/${r.id}/close`, { method: "POST" }), "Request closed")}>Close request</button>
            </>
          )}

          {!r.is_owner && (
            user ? (
              r.has_storefront ? (
                <ProposalForm request={r} onSaved={load} />
              ) : (
                <div className="card p-5 text-sm text-ink-300">Open a creator storefront to send proposals. <Link className="text-gold-300 underline" href="/dashboard?tab=storefront">Set it up</Link></div>
              )
            ) : (
              <Link href={`/login?next=/requests/${r.id}`} className="btn-gold w-full">Sign in to send a proposal</Link>
            )
          )}
        </aside>
      </div>
    </div>
  );
}

export default function RequestPage() {
  return <Suspense><RequestDetail /></Suspense>;
}
