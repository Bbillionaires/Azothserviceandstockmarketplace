import { CreatorCard } from "@/components/CreatorCard";
import { tryApi } from "@/lib/api";
import type { Creator, Page } from "@/lib/types";

export const metadata = { title: "Hire creators" };
export const dynamic = "force-dynamic";

const CATS = ["photographer", "videographer", "filmmaker", "drone_operator", "editor", "production_studio", "media_agency"];

export default async function CreatorsPage({ searchParams }: { searchParams: Promise<Record<string, string | undefined>> }) {
  const sp = await searchParams;
  const qs = new URLSearchParams(Object.entries(sp).filter(([, v]) => v) as [string, string][]).toString();
  const data = await tryApi<Page<Creator>>(`/creators?${qs}`, { items: [], total: 0, page: 1, page_size: 24 });

  return (
    <div className="mx-auto max-w-7xl px-4 py-10">
      <h1 className="font-display text-4xl">{sp.emerging === "true" ? "Hire emerging talent" : "Hire creators"}</h1>
      <p className="mt-2 text-ink-300">Search by city, country, specialty and availability. Exact addresses are never shown.</p>
      <form className="card mt-6 grid gap-4 p-5 sm:grid-cols-2 lg:grid-cols-6" method="get">
        <div className="lg:col-span-2">
          <label htmlFor="q" className="label">Name or keyword</label>
          <input id="q" name="q" className="input" defaultValue={sp.q} />
        </div>
        <div>
          <label htmlFor="category" className="label">Specialty</label>
          <select id="category" name="category" className="input" defaultValue={sp.category ?? ""}>
            <option value="">Any</option>
            {CATS.map((c) => <option key={c} value={c}>{c.replace(/_/g, " ")}</option>)}
          </select>
        </div>
        <div>
          <label htmlFor="city" className="label">City</label>
          <input id="city" name="city" className="input" defaultValue={sp.city} />
        </div>
        <div>
          <label htmlFor="country" className="label">Country</label>
          <input id="country" name="country" maxLength={2} className="input" defaultValue={sp.country} placeholder="US" />
        </div>
        <div className="flex flex-col justify-end gap-2 text-sm">
          <label className="flex items-center gap-2"><input type="checkbox" name="remote" value="true" defaultChecked={sp.remote === "true"} /> Remote</label>
          <label className="flex items-center gap-2"><input type="checkbox" name="emerging" value="true" defaultChecked={sp.emerging === "true"} /> Emerging talent</label>
        </div>
        <button className="btn-gold sm:col-span-2 lg:col-span-6" type="submit">Search creators</button>
      </form>
      <p className="mt-6 text-sm text-ink-300">{data.total} creators</p>
      <div className="mt-4 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {data.items.map((c) => <CreatorCard key={c.id} c={c} />)}
      </div>
    </div>
  );
}
