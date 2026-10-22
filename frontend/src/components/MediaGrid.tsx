import Link from "next/link";
import { duration, label, money } from "@/lib/api";
import type { MediaCard } from "@/lib/types";

export function MediaTile({ item }: { item: MediaCard }) {
  const ratio = item.width && item.height ? `${item.width} / ${item.height}` : "4 / 3";
  return (
    <Link
      href={`/media/${item.id}`}
      className="group relative block overflow-hidden rounded-xl border border-ink-800 bg-ink-900"
    >
      <div style={{ aspectRatio: ratio }} className="relative w-full overflow-hidden">
        {item.thumbnail_url ? (
          // Watermarked previews come from the CDN; plain <img> keeps them out of
          // Next's image optimizer (which would otherwise need remote patterns).
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={item.thumbnail_url}
            alt={item.title}
            loading="lazy"
            className="h-full w-full object-cover transition duration-500 group-hover:scale-105"
          />
        ) : (
          <div className="h-full w-full bg-gradient-to-br from-ink-700 to-ink-900" />
        )}
        <div className="absolute left-2 top-2 flex gap-1.5 text-[11px] font-semibold">
          {item.media_type === "video" && (
            <span className="rounded bg-black/70 px-1.5 py-0.5">▶ {duration(item.duration_seconds)}</span>
          )}
          {item.resolution_label && <span className="rounded bg-black/70 px-1.5 py-0.5">{item.resolution_label}</span>}
          {item.is_free && <span className="rounded bg-gold-500 px-1.5 py-0.5 text-ink-950">FREE</span>}
        </div>
      </div>
      <div className="absolute inset-x-0 bottom-0 translate-y-1 bg-gradient-to-t from-black/90 via-black/50 to-transparent p-3 opacity-0 transition group-hover:translate-y-0 group-hover:opacity-100 group-focus-visible:opacity-100">
        <p className="truncate text-sm font-medium">{item.title}</p>
        <p className="flex justify-between text-xs text-ink-200">
          <span>{item.creator.display_name}</span>
          <span>{item.starting_price_cents ? `from ${money(item.starting_price_cents, item.currency)}` : label(item.category)}</span>
        </p>
      </div>
    </Link>
  );
}

export function MediaGrid({ items, empty }: { items: MediaCard[]; empty?: React.ReactNode }) {
  if (!items.length) {
    return <div className="card p-10 text-center text-ink-300">{empty ?? "No media yet."}</div>;
  }
  return (
    <div className="masonry">
      {items.map((m) => <MediaTile key={m.id} item={m} />)}
    </div>
  );
}
