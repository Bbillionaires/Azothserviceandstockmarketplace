"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { Alert } from "@/components/Alert";
import { api, label } from "@/lib/api";
import { RIGHTS_LABEL, SERVICE_CATEGORIES, type ProjectRequest } from "@/lib/production";
import { useSession } from "@/lib/session";

const dollars = (v: FormDataEntryValue | null) => (v && String(v).trim() ? Math.round(Number(v) * 100) : null);

function NewRequest() {
  const params = useSearchParams();
  const router = useRouter();
  const { user, loading } = useSession();
  const [kind, setKind] = useState(params.get("kind") === "shot_request" ? "shot_request" : "custom_project");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    setBusy(true);
    setError("");
    try {
      const r = await api<ProjectRequest>("/requests", {
        method: "POST",
        json: {
          kind, title: f.get("title"), description: f.get("description"), category: f.get("category"),
          deliverables: f.get("deliverables") || "",
          reference_urls: String(f.get("refs") || "").split(/\s+/).filter(Boolean),
          location_city: f.get("city") || null, location_region: f.get("region") || null,
          location_country: f.get("country") || null, remote_ok: f.get("remote") === "on",
          budget_min_cents: dollars(f.get("budget_min")), budget_max_cents: dollars(f.get("budget_max")),
          deadline: f.get("deadline") || null, rights_preference: f.get("rights"),
          visibility: f.get("visibility"),
        },
      });
      router.push(`/requests/${r.id}?created=1`);
    } catch (err) {
      setError((err as Error).message);
      setBusy(false);
    }
  };

  if (!loading && !user) {
    return <div className="mx-auto max-w-xl p-16 text-center"><a className="btn-gold" href="/login?next=/requests/new">Sign in to post a brief</a></div>;
  }

  return (
    <div className="mx-auto max-w-3xl px-4 py-10">
      <h1 className="font-display text-4xl">{kind === "shot_request" ? "Request This Shot" : "Post a production brief"}</h1>
      <p className="mt-2 text-ink-300">Describe what you need. Matching creators can send proposals; you choose who to hire. Posting is free.</p>
      <form onSubmit={submit} className="card mt-8 space-y-5 p-6">
        {error && <Alert>{error}</Alert>}
        <fieldset className="flex flex-wrap gap-4 text-sm">
          <legend className="label">What do you need?</legend>
          <label className="flex items-center gap-2"><input type="radio" checked={kind === "shot_request"} onChange={() => setKind("shot_request")} /> A specific shot or footage that doesn&apos;t exist yet</label>
          <label className="flex items-center gap-2"><input type="radio" checked={kind === "custom_project"} onChange={() => setKind("custom_project")} /> A custom production or service</label>
        </fieldset>
        <div><label htmlFor="title" className="label">Title</label><input id="title" name="title" className="input" required minLength={5} maxLength={200}
          placeholder={kind === "shot_request" ? "Drone footage of the riverfront tower at sunset" : "60-second promo video for our restaurant opening"} /></div>
        <div><label htmlFor="description" className="label">Description</label><textarea id="description" name="description" className="input min-h-32" required minLength={20} /></div>
        <div className="grid gap-4 sm:grid-cols-2">
          <div>
            <label htmlFor="category" className="label">Category</label>
            <select id="category" name="category" className="input" defaultValue={kind === "shot_request" ? "drone_services" : "commercial_production"}>
              {SERVICE_CATEGORIES.map((c) => <option key={c} value={c}>{label(c)}</option>)}
            </select>
          </div>
          <div><label htmlFor="deadline" className="label">Deadline</label><input id="deadline" name="deadline" type="date" className="input" /></div>
        </div>
        <div><label htmlFor="deliverables" className="label">Deliverables</label><textarea id="deliverables" name="deliverables" className="input" placeholder="e.g. 3 clips, 4K ProRes, 20–30 seconds each" /></div>
        <div className="grid gap-4 sm:grid-cols-3">
          <div><label htmlFor="city" className="label">City</label><input id="city" name="city" className="input" /></div>
          <div><label htmlFor="region" className="label">State / region</label><input id="region" name="region" className="input" /></div>
          <div><label htmlFor="country" className="label">Country code</label><input id="country" name="country" maxLength={2} className="input" placeholder="US" /></div>
        </div>
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" name="remote" /> Remote work is fine (editing, animation, etc.)</label>
        <div className="grid gap-4 sm:grid-cols-2">
          <div><label htmlFor="bmin" className="label">Budget from (USD)</label><input id="bmin" name="budget_min" type="number" min="0" step="1" className="input" /></div>
          <div><label htmlFor="bmax" className="label">Budget up to (USD)</label><input id="bmax" name="budget_max" type="number" min="1" step="1" className="input" /></div>
        </div>
        <fieldset className="space-y-2 text-sm">
          <legend className="label">Rights you want in the result</legend>
          {Object.entries(RIGHTS_LABEL).map(([v, l]) => (
            <label key={v} className="flex items-center gap-2"><input type="radio" name="rights" value={v} defaultChecked={v === "exclusive"} required /> {l}</label>
          ))}
          <p className="text-xs text-ink-400">Final rights are agreed in the proposal you accept. Commissioned work is never resold as stock without your agreement.</p>
        </fieldset>
        <div><label htmlFor="refs" className="label">Reference links (optional, one per line)</label><textarea id="refs" name="refs" className="input" placeholder="https://…" /></div>
        <div>
          <label htmlFor="visibility" className="label">Visibility</label>
          <select id="visibility" name="visibility" className="input">
            <option value="public">Public: any creator can propose</option>
            <option value="invite_only">Invite only: I&apos;ll invite creators</option>
          </select>
        </div>
        <button className="btn-gold w-full" disabled={busy}>{busy ? "Posting…" : "Post brief"}</button>
      </form>
    </div>
  );
}

export default function NewRequestPage() {
  return <Suspense><NewRequest /></Suspense>;
}
