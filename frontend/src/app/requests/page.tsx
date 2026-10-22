import Link from "next/link";
import { label, money, tryApi } from "@/lib/api";
import { SERVICE_CATEGORIES, budgetText, type ProjectRequest } from "@/lib/production";

export const metadata = { title: "Production briefs" };
export const dynamic = "force-dynamic";

export default async function RequestsBoard({ searchParams }: { searchParams: Promise<Record<string, string | undefined>> }) {
  const sp = await searchParams;
  const qs = new URLSearchParams(Object.entries(sp).filter(([, v]) => v) as [string, string][]).toString();
  const data = await tryApi<{ items: ProjectRequest[]; total: number }>(`/requests?${qs}`, { items: [], total: 0 });

  return (
    <div className="mx-auto max-w-7xl px-4 py-10">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 className="font-display text-4xl">{sp.kind === "shot_request" ? "Request This Shot board" : "Production briefs"}</h1>
          <p className="mt-2 text-ink-300">Open requests from clients. Send a proposal; your price and terms are visible only to the client.</p>
        </div>
        <Link href="/requests/new" className="btn-gold">Post a brief</Link>
      </div>
      <form method="get" className="card mt-6 grid gap-4 p-5 sm:grid-cols-2 lg:grid-cols-6">
        <div className="lg:col-span-2"><label htmlFor="q" className="label">Keyword</label><input id="q" name="q" className="input" defaultValue={sp.q} /></div>
        <div>
          <label htmlFor="kind" className="label">Type</label>
          <select id="kind" name="kind" className="input" defaultValue={sp.kind ?? ""}>
            <option value="">All</option><option value="shot_request">Request This Shot</option><option value="custom_project">Custom project</option>
          </select>
        </div>
        <div>
          <label htmlFor="category" className="label">Category</label>
          <select id="category" name="category" className="input" defaultValue={sp.category ?? ""}>
            <option value="">Any</option>{SERVICE_CATEGORIES.map((c) => <option key={c} value={c}>{label(c)}</option>)}
          </select>
        </div>
        <div><label htmlFor="city" className="label">City</label><input id="city" name="city" className="input" defaultValue={sp.city} /></div>
        <div>
          <label htmlFor="sort" className="label">Sort</label>
          <select id="sort" name="sort" className="input" defaultValue={sp.sort ?? "newest"}>
            <option value="newest">Newest</option><option value="deadline">Deadline</option><option value="budget">Budget</option>
          </select>
        </div>
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" name="remote" value="true" defaultChecked={sp.remote === "true"} /> Remote OK</label>
        <button className="btn-gold sm:col-span-2 lg:col-span-5" type="submit">Filter</button>
      </form>
      <p className="mt-6 text-sm text-ink-300">{data.total} open briefs</p>
      <ul className="mt-4 grid gap-4 md:grid-cols-2">
        {data.items.map((r) => (
          <li key={r.id}>
            <Link href={`/requests/${r.id}`} className="card block h-full p-5 transition hover:border-gold-600">
              <div className="flex flex-wrap items-center gap-2 text-xs">
                {r.kind === "shot_request" && <span className="rounded-full bg-gold-500 px-2 py-0.5 font-semibold text-ink-950">Request This Shot</span>}
                <span className="rounded-full border border-ink-600 px-2 py-0.5 text-ink-200">{label(r.category)}</span>
                <span className="text-ink-400">{r.proposal_count} proposals</span>
              </div>
              <h2 className="font-display mt-3 text-xl">{r.title}</h2>
              <p className="mt-2 line-clamp-3 text-sm text-ink-300">{r.description}</p>
              <dl className="mt-4 grid grid-cols-3 gap-2 text-xs">
                <div><dt className="text-ink-400">Budget</dt><dd>{budgetText(r, money)}</dd></div>
                <div><dt className="text-ink-400">Where</dt><dd>{[r.location_city, r.location_country].filter(Boolean).join(", ") || "Anywhere"}{r.remote_ok ? " · remote OK" : ""}</dd></div>
                <div><dt className="text-ink-400">Deadline</dt><dd>{r.deadline ? new Date(r.deadline).toLocaleDateString() : "Flexible"}</dd></div>
              </dl>
            </Link>
          </li>
        ))}
      </ul>
    </div>
  );
}
