"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { api, label, money } from "@/lib/api";
import type { ProjectRequest } from "@/lib/production";

type ProjectRow = { id: string; title: string; status: string; role: string; total_cents: number; currency: string; creator_name: string; client_name: string; next_milestone: { title: string; status: string } | null };

export function ProjectsPanel({ isCreator }: { isCreator: boolean }) {
  const [projects, setProjects] = useState<ProjectRow[]>([]);
  const [requests, setRequests] = useState<ProjectRequest[]>([]);
  const [invites, setInvites] = useState<ProjectRequest[]>([]);
  useEffect(() => {
    api<ProjectRow[]>("/projects/mine").then(setProjects).catch(() => {});
    api<ProjectRequest[]>("/requests/mine").then(setRequests).catch(() => {});
    if (isCreator) api<ProjectRequest[]>("/requests/invitations").then(setInvites).catch(() => {});
  }, [isCreator]);

  return (
    <div className="space-y-8">
      <section>
        <div className="mb-3 flex items-center justify-between"><h2 className="font-display text-xl">Projects</h2>
          <Link href="/requests/new" className="btn-gold text-sm">Post a brief</Link></div>
        {projects.length === 0 ? <p className="card p-6 text-center text-ink-300">No projects yet. Post a brief or book a creator&apos;s package.</p> : (
          <ul className="space-y-2">
            {projects.map((p) => (
              <li key={p.id}>
                <Link href={`/projects/${p.id}`} className="card flex flex-wrap items-center justify-between gap-2 p-4 hover:border-gold-600">
                  <span><span className="font-medium">{p.title}</span>
                    <span className="block text-xs text-ink-400">{p.role === "client" ? `Creator: ${p.creator_name}` : `Client: ${p.client_name}`} · {label(p.status)}{p.next_milestone ? ` · next: ${p.next_milestone.title} (${label(p.next_milestone.status)})` : ""}</span></span>
                  <span className="font-semibold">{money(p.total_cents, p.currency)}</span>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </section>
      {invites.length > 0 && (
        <section>
          <h2 className="font-display mb-3 text-xl">Invitations to quote</h2>
          <ul className="space-y-2">{invites.map((r) => <li key={r.id}><Link className="card block p-4 hover:border-gold-600" href={`/requests/${r.id}`}>{r.title} <span className="text-xs text-ink-400">· {label(r.status)}</span></Link></li>)}</ul>
        </section>
      )}
      {requests.length > 0 && (
        <section>
          <h2 className="font-display mb-3 text-xl">My briefs</h2>
          <ul className="space-y-2">{requests.map((r) => <li key={r.id}><Link className="card block p-4 hover:border-gold-600" href={`/requests/${r.id}`}>{r.title} <span className="text-xs text-ink-400">· {label(r.status)} · {r.proposal_count} proposals</span></Link></li>)}</ul>
        </section>
      )}
    </div>
  );
}
