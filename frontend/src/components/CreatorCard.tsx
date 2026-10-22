import Link from "next/link";
import { label } from "@/lib/api";
import type { Creator } from "@/lib/types";

export function CreatorCard({ c }: { c: Creator }) {
  return (
    <Link href={`/creators/${c.handle}`} className="card group flex flex-col gap-4 p-5 transition hover:border-gold-600">
      <div className="flex items-center gap-3">
        {c.avatar_url ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={c.avatar_url} alt="" className="h-12 w-12 rounded-full object-cover" />
        ) : (
          <span aria-hidden className="grid h-12 w-12 place-items-center rounded-full bg-ink-700 font-display text-lg text-gold-300">
            {c.display_name.charAt(0)}
          </span>
        )}
        <div className="min-w-0">
          <p className="truncate font-medium group-hover:text-gold-300">
            {c.display_name}
            {c.verification_status === "verified" && <span className="ml-1 text-gold-400" title="Verified creator">✓</span>}
          </p>
          <p className="truncate text-sm text-ink-300">{c.headline || label(c.categories[0] ?? "creator")}</p>
        </div>
      </div>
      <div className="flex flex-wrap gap-1.5 text-xs">
        {c.categories.slice(0, 3).map((cat) => (
          <span key={cat} className="rounded-full border border-ink-600 px-2 py-0.5 text-ink-200">{label(cat)}</span>
        ))}
        {c.is_emerging_talent && <span className="rounded-full bg-gold-500/15 px-2 py-0.5 text-gold-300">Emerging talent</span>}
      </div>
      <p className="text-xs text-ink-400">
        {[c.city, c.region, c.country_code].filter(Boolean).join(", ") || "Location not listed"}
        {c.remote_available && " · Remote"}
        {c.travel_available && " · Travels"}
      </p>
    </Link>
  );
}
