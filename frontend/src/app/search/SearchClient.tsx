"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";
import { MediaGrid } from "@/components/MediaGrid";
import { SearchBar } from "@/components/SearchBar";
import { api, label } from "@/lib/api";
import type { MediaCard } from "@/lib/types";

type Facet = { value: string; count: number };
type Result = {
  items: MediaCard[];
  total: number;
  page: number;
  page_size: number;
  facets: Record<string, Facet[]>;
  interpreted: Record<string, string | null>;
};

const FILTERS: { key: string; label: string; options: [string, string][] }[] = [
  { key: "type", label: "Media type", options: [["", "All"], ["photo", "Photos"], ["video", "Video"]] },
  { key: "orientation", label: "Orientation", options: [["", "Any"], ["horizontal", "Horizontal"], ["vertical", "Vertical"], ["square", "Square"]] },
  { key: "resolution", label: "Minimum resolution", options: [["", "Any"], ["HD", "HD"], ["4K", "4K"], ["8K", "8K"]] },
  { key: "license", label: "License", options: [["", "Any"], ["editorial", "Editorial"], ["standard_commercial", "Standard commercial"], ["extended_commercial", "Extended commercial"]] },
  { key: "sort", label: "Sort by", options: [["relevance", "Relevance"], ["popular", "Popular"], ["newest", "Newest"], ["price_low", "Lowest price"]] },
];

export function SearchClient() {
  const params = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const [result, setResult] = useState<Result | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const qs = params.toString();

  useEffect(() => {
    setLoading(true);
    api<Result>(`/search/media?${qs}`)
      .then((r) => { setResult(r); setError(""); })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [qs]);

  const update = (key: string, value: string) => {
    const next = new URLSearchParams(params.toString());
    if (value) next.set(key, value); else next.delete(key);
    next.delete("page");
    router.push(`${pathname}?${next.toString()}`);
  };

  const page = Number(params.get("page") ?? "1");
  const pages = result ? Math.ceil(result.total / result.page_size) : 0;
  const interpretedChips = Object.entries(result?.interpreted ?? {}).filter(([k, v]) => v && k !== "terms");

  return (
    <div className="mx-auto max-w-7xl px-4 py-10">
      <SearchBar initial={params.get("q") ?? ""} />
      <div className="mt-8 grid gap-8 lg:grid-cols-[240px_1fr]">
        <aside aria-label="Filters" className="space-y-5">
          {FILTERS.map((f) => (
            <div key={f.key}>
              <label htmlFor={`f-${f.key}`} className="label">{f.label}</label>
              <select id={`f-${f.key}`} className="input" value={params.get(f.key) ?? f.options[0][0]} onChange={(e) => update(f.key, e.target.value)}>
                {f.options.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
              </select>
            </div>
          ))}
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={params.get("free") === "true"} onChange={(e) => update("free", e.target.checked ? "true" : "")} />
            Free media only
          </label>
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={params.get("model_release") === "true"} onChange={(e) => update("model_release", e.target.checked ? "true" : "")} />
            Model release on file
          </label>
          <div>
            <label htmlFor="f-country" className="label">Location (country code)</label>
            <input id="f-country" className="input" maxLength={2} defaultValue={params.get("country") ?? ""}
              onBlur={(e) => update("country", e.target.value.toUpperCase())} placeholder="US" />
          </div>
          {result?.facets.category?.length ? (
            <div>
              <p className="label">Categories</p>
              <ul className="space-y-1 text-sm">
                {result.facets.category.map((c) => (
                  <li key={c.value}>
                    <button className={`hover:text-gold-300 ${params.get("category") === c.value ? "text-gold-400" : "text-ink-200"}`}
                      onClick={() => update("category", params.get("category") === c.value ? "" : c.value)}>
                      {label(c.value)} <span className="text-ink-400">({c.count})</span>
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
        </aside>
        <section aria-live="polite" aria-busy={loading}>
          <div className="mb-4 flex flex-wrap items-center gap-2 text-sm text-ink-300">
            <span>{loading ? "Searching…" : `${result?.total ?? 0} results`}</span>
            {interpretedChips.map(([k, v]) => (
              <span key={k} className="rounded-full bg-gold-500/15 px-2 py-0.5 text-gold-300">{label(k)}: {v}</span>
            ))}
          </div>
          {error ? <p className="text-red-300">{error}</p> : result && (
            <MediaGrid items={result.items} empty="No media matches those filters yet. Try fewer filters, or request this shot." />
          )}
          {pages > 1 && (
            <nav aria-label="Pagination" className="mt-8 flex justify-center gap-3">
              <button className="btn-ghost" disabled={page <= 1} onClick={() => update("page", String(page - 1))}>Previous</button>
              <span className="self-center text-sm text-ink-300">Page {page} of {pages}</span>
              <button className="btn-ghost" disabled={page >= pages} onClick={() => update("page", String(page + 1))}>Next</button>
            </nav>
          )}
        </section>
      </div>
    </div>
  );
}
