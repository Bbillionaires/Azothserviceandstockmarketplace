import { notFound } from "next/navigation";
import { MediaGrid } from "@/components/MediaGrid";
import { ApiError, api, label, tryApi } from "@/lib/api";
import type { Creator, MediaCard } from "@/lib/types";
import { FollowButton } from "./FollowButton";
import { StorefrontServices } from "./StorefrontServices";
import type { Package } from "@/lib/production";

export const dynamic = "force-dynamic";

export async function generateMetadata({ params }: { params: Promise<{ handle: string }> }) {
  const { handle } = await params;
  const c = await tryApi<Creator | null>(`/creators/${handle}`, null);
  return { title: c ? c.display_name : "Creator" };
}

export default async function Storefront({ params }: { params: Promise<{ handle: string }> }) {
  const { handle } = await params;
  let c: Creator;
  try {
    c = await api<Creator>(`/creators/${handle}`);
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) notFound();
    throw e;
  }
  const [media, stats, packages, reputation] = await Promise.all([
    tryApi<{ items: MediaCard[] }>(`/search/media?creator=${handle}&sort=newest&page_size=48`, { items: [] }),
    tryApi<{ approved_media: number; total_downloads: number; total_views: number }>(`/creators/${handle}/stats`,
      { approved_media: 0, total_downloads: 0, total_views: 0 }),
    tryApi<Package[]>(`/creators/${handle}/packages`, []),
    tryApi(`/creators/${handle}/reputation`, { average: 0, count: 0, completed_projects: 0, reviews: [] }),
  ]);

  return (
    <div>
      <div className="relative h-56 overflow-hidden border-b border-ink-800 sm:h-72">
        {c.banner_url ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={c.banner_url} alt="" className="h-full w-full object-cover opacity-70" />
        ) : (
          <div className="h-full w-full bg-[radial-gradient(ellipse_at_top_left,rgba(200,161,90,0.35),transparent_60%),linear-gradient(135deg,#15151c,#07070a)]" />
        )}
      </div>
      <div className="mx-auto max-w-7xl px-4">
        <div className="-mt-12 flex flex-col gap-6 sm:flex-row sm:items-end sm:justify-between">
          <div className="flex items-end gap-4">
            {c.avatar_url ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img src={c.avatar_url} alt="" className="h-24 w-24 rounded-full border-4 border-ink-950 object-cover" />
            ) : (
              <span aria-hidden className="grid h-24 w-24 place-items-center rounded-full border-4 border-ink-950 bg-ink-700 font-display text-4xl text-gold-300">
                {c.display_name.charAt(0)}
              </span>
            )}
            <div>
              <h1 className="font-display text-3xl">
                {c.display_name}
                {c.verification_status === "verified" && <span className="ml-2 text-lg text-gold-400" title="Verified">✓</span>}
              </h1>
              <p className="text-ink-300">{c.headline}</p>
            </div>
          </div>
          <FollowButton handle={c.handle} followers={c.follower_count} />
        </div>

        <div className="mt-8 grid gap-8 lg:grid-cols-[1fr_300px]">
          <div>
            {c.bio && <p className="whitespace-pre-line text-ink-200">{c.bio}</p>}
            <div className="mt-8"><StorefrontServices handle={c.handle} name={c.display_name} packages={packages} reputation={reputation} /></div>
            <h2 className="font-display mt-10 mb-4 text-2xl">Portfolio & stock media</h2>
            <MediaGrid items={media.items} empty="No published media yet." />
          </div>
          <aside className="card h-fit space-y-4 p-6 text-sm">
            <div>
              <p className="text-ink-400">Specialties</p>
              <p>{[...c.categories.map(label), ...c.specialties].join(" · ") || "—"}</p>
            </div>
            <div>
              <p className="text-ink-400">Based in</p>
              <p>{[c.city, c.region, c.country_code].filter(Boolean).join(", ") || "—"}</p>
              <p className="text-ink-300">
                {c.remote_available && "Remote work · "}{c.travel_available && "Available to travel · "}
                {c.service_radius_km ? `${c.service_radius_km} km service radius` : ""}
              </p>
            </div>
            <div className="grid grid-cols-3 gap-2 text-center">
              <div><p className="text-lg font-semibold">{stats.approved_media}</p><p className="text-xs text-ink-400">Media</p></div>
              <div><p className="text-lg font-semibold">{stats.total_downloads}</p><p className="text-xs text-ink-400">Downloads</p></div>
              <div><p className="text-lg font-semibold">{c.follower_count}</p><p className="text-xs text-ink-400">Followers</p></div>
            </div>
            {c.website && <a href={c.website} rel="noopener nofollow ugc" target="_blank" className="block text-gold-300 underline">Website</a>}
            {reputation.count > 0 && <p><span className="text-gold-300">★ {reputation.average.toFixed(1)}</span> <span className="text-ink-400">({reputation.count} verified reviews)</span></p>}
          </aside>
        </div>
      </div>
    </div>
  );
}
