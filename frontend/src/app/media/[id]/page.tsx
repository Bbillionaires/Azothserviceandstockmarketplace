import Link from "next/link";
import { notFound } from "next/navigation";
import { ApiError, api, duration, label } from "@/lib/api";
import type { MediaDetail } from "@/lib/types";
import { MediaActions } from "./MediaActions";

export const dynamic = "force-dynamic";

async function load(id: string): Promise<MediaDetail> {
  try {
    return await api<MediaDetail>(`/media/${id}`);
  } catch (e) {
    if (e instanceof ApiError && (e.status === 404 || e.status === 422)) notFound();
    throw e;
  }
}

export async function generateMetadata({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  try {
    const m = await api<MediaDetail>(`/media/${id}`);
    return { title: m.title, description: m.description || m.title };
  } catch {
    return { title: "Media" };
  }
}

export default async function MediaPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const m = await load(id);
  const preview = m.files.find((f) => f.kind === "preview");
  const poster = m.files.find((f) => f.kind === "poster");
  const specs: [string, string | null][] = [
    ["Type", label(m.media_type)],
    ["Dimensions", m.width && m.height ? `${m.width} × ${m.height}` : null],
    ["Resolution", m.resolution_label],
    ["Duration", m.duration_seconds ? duration(m.duration_seconds) : null],
    ["Frame rate", m.frame_rate ? `${m.frame_rate} fps` : null],
    ["Format", m.file_format?.toUpperCase() ?? null],
    ["Orientation", m.orientation ? label(m.orientation) : null],
    ["Category", label(m.category)],
    ["Location", [m.location_city, m.location_region, m.location_country].filter(Boolean).join(", ") || null],
    ["Model release", m.has_model_release ? "Yes" : "No"],
    ["Property release", m.has_property_release ? "Yes" : "No"],
  ];

  return (
    <div className="mx-auto max-w-7xl px-4 py-10">
      <div className="grid gap-10 lg:grid-cols-[1fr_380px]">
        <div>
          <div className="overflow-hidden rounded-2xl border border-ink-800 bg-black">
            {m.media_type === "video" && preview ? (
              <video src={preview.url} poster={poster?.url} controls muted playsInline className="mx-auto max-h-[75vh] w-full" />
            ) : preview ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img src={preview.url} alt={m.title} className="mx-auto max-h-[75vh] w-auto" />
            ) : (
              <p className="p-20 text-center text-ink-300">Preview is being generated…</p>
            )}
          </div>
          <p className="mt-2 text-xs text-ink-400">Watermarked preview. Licensed downloads are the full-quality, unwatermarked original.</p>
          <h1 className="font-display mt-6 text-3xl">{m.title}</h1>
          <p className="mt-2 text-sm text-ink-300">
            by <Link className="text-gold-300 hover:underline" href={`/creators/${m.creator.handle}`}>{m.creator.display_name}</Link>
            {m.creator.verification_status === "verified" && " ✓"}
          </p>
          {m.description && <p className="mt-4 whitespace-pre-line text-ink-200">{m.description}</p>}
          <div className="mt-4 flex flex-wrap gap-2">
            {m.is_editorial_only && <span className="rounded-full bg-amber-500/15 px-2 py-0.5 text-xs text-amber-300">Editorial use only</span>}
            {(m.is_ai_generated || m.is_materially_altered) && (
              <span className="rounded-full bg-sky-500/15 px-2 py-0.5 text-xs text-sky-300">
                {m.is_ai_generated ? "AI-generated" : "Materially altered"} (creator disclosure)
              </span>
            )}
            {m.keywords.map((k) => (
              <Link key={k} href={`/search?q=${encodeURIComponent(k)}`} className="rounded-full border border-ink-600 px-2 py-0.5 text-xs text-ink-200 hover:border-gold-500">{k}</Link>
            ))}
          </div>
          <dl className="card mt-8 grid grid-cols-2 gap-x-6 gap-y-3 p-6 text-sm sm:grid-cols-3">
            {specs.filter(([, v]) => v).map(([k, v]) => (
              <div key={k}><dt className="text-ink-400">{k}</dt><dd>{v}</dd></div>
            ))}
          </dl>
        </div>
        <MediaActions media={m} />
      </div>
    </div>
  );
}
