"use client";

import { useState } from "react";
import { Alert } from "@/components/Alert";
import { api, label } from "@/lib/api";
import type { Creator } from "@/lib/types";

const CATEGORIES = [
  "photographer", "videographer", "filmmaker", "drone_operator", "editor", "retoucher", "colorist",
  "motion_designer", "sound_engineer", "director", "cinematographer", "production_studio", "media_agency", "copyright_owner",
];

export function StorefrontForm({ creator, defaultName, disabled, onSaved }: { creator: Creator | null; defaultName: string; disabled: boolean; onSaved: (c: Creator) => void }) {
  const [f, setF] = useState({
    handle: creator?.handle ?? "",
    display_name: creator?.display_name ?? defaultName,
    headline: creator?.headline ?? "",
    bio: creator?.bio ?? "",
    categories: creator?.categories ?? [],
    specialties: (creator?.specialties ?? []).join(", "),
    city: creator?.city ?? "",
    region: creator?.region ?? "",
    country_code: creator?.country_code ?? "",
    service_radius_km: creator?.service_radius_km?.toString() ?? "",
    remote_available: creator?.remote_available ?? false,
    travel_available: creator?.travel_available ?? false,
    website: creator?.website ?? "",
    avatar_url: creator?.avatar_url ?? "",
    banner_url: creator?.banner_url ?? "",
    is_emerging_talent: creator?.is_emerging_talent ?? false,
  });
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);

  const set = (k: string, v: unknown) => setF((p) => ({ ...p, [k]: v }));

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    const body = {
      ...f,
      specialties: f.specialties.split(",").map((s) => s.trim()).filter(Boolean),
      service_radius_km: f.service_radius_km ? Number(f.service_radius_km) : null,
      country_code: f.country_code || null,
      website: f.website || null,
      avatar_url: f.avatar_url || null,
      banner_url: f.banner_url || null,
    };
    try {
      const c = creator
        ? await api<Creator>("/creators/me", { method: "PATCH", json: { ...body, handle: undefined } })
        : await api<Creator>("/creators", { method: "POST", json: body });
      setMsg({ ok: true, text: creator ? "Storefront saved." : "Storefront created. Next: accept a contributor agreement." });
      onSaved(c);
    } catch (err) {
      setMsg({ ok: false, text: (err as Error).message });
    }
  };

  return (
    <form onSubmit={submit} className="card grid gap-5 p-6 md:grid-cols-2">
      {msg && <div className="md:col-span-2"><Alert kind={msg.ok ? "success" : "error"}>{msg.text}</Alert></div>}
      {!creator && (
        <div>
          <label htmlFor="handle" className="label">Storefront address</label>
          <div className="flex items-center gap-1 text-sm text-ink-400">/creators/
            <input id="handle" className="input" value={f.handle} onChange={(e) => set("handle", e.target.value.toLowerCase())} pattern="[a-z0-9][a-z0-9\-]{1,38}[a-z0-9]" required />
          </div>
        </div>
      )}
      <div>
        <label htmlFor="dn" className="label">Display name</label>
        <input id="dn" className="input" value={f.display_name} onChange={(e) => set("display_name", e.target.value)} required minLength={2} />
      </div>
      <div className="md:col-span-2">
        <label htmlFor="headline" className="label">Headline</label>
        <input id="headline" className="input" value={f.headline} onChange={(e) => set("headline", e.target.value)} maxLength={200} />
      </div>
      <div className="md:col-span-2">
        <label htmlFor="bio" className="label">Biography</label>
        <textarea id="bio" className="input min-h-28" value={f.bio} onChange={(e) => set("bio", e.target.value)} />
      </div>
      <fieldset className="md:col-span-2">
        <legend className="label">Professional categories</legend>
        <div className="flex flex-wrap gap-2">
          {CATEGORIES.map((c) => (
            <label key={c} className={`cursor-pointer rounded-full border px-3 py-1 text-sm ${f.categories.includes(c) ? "border-gold-500 text-gold-300" : "border-ink-600 text-ink-200"}`}>
              <input type="checkbox" className="sr-only" checked={f.categories.includes(c)}
                onChange={(e) => set("categories", e.target.checked ? [...f.categories, c] : f.categories.filter((x) => x !== c))} />
              {label(c)}
            </label>
          ))}
        </div>
      </fieldset>
      <div className="md:col-span-2">
        <label htmlFor="spec" className="label">Specialties (comma-separated)</label>
        <input id="spec" className="input" value={f.specialties} onChange={(e) => set("specialties", e.target.value)} placeholder="weddings, real estate, FAA Part 107" />
      </div>
      <div><label htmlFor="city" className="label">City</label><input id="city" className="input" value={f.city} onChange={(e) => set("city", e.target.value)} /></div>
      <div><label htmlFor="region" className="label">State / region</label><input id="region" className="input" value={f.region} onChange={(e) => set("region", e.target.value)} /></div>
      <div><label htmlFor="cc" className="label">Country code</label><input id="cc" className="input" maxLength={2} value={f.country_code} onChange={(e) => set("country_code", e.target.value.toUpperCase())} placeholder="US" /></div>
      <div><label htmlFor="radius" className="label">Service radius (km)</label><input id="radius" type="number" min={0} className="input" value={f.service_radius_km} onChange={(e) => set("service_radius_km", e.target.value)} /></div>
      <div><label htmlFor="web" className="label">Website</label><input id="web" type="url" className="input" value={f.website} onChange={(e) => set("website", e.target.value)} /></div>
      <div><label htmlFor="avatar" className="label">Profile image URL</label><input id="avatar" type="url" className="input" value={f.avatar_url} onChange={(e) => set("avatar_url", e.target.value)} /></div>
      <div className="md:col-span-2"><label htmlFor="banner" className="label">Banner image URL</label><input id="banner" type="url" className="input" value={f.banner_url} onChange={(e) => set("banner_url", e.target.value)} /></div>
      <div className="flex flex-wrap gap-5 text-sm md:col-span-2">
        <label className="flex items-center gap-2"><input type="checkbox" checked={f.remote_available} onChange={(e) => set("remote_available", e.target.checked)} /> Available for remote work</label>
        <label className="flex items-center gap-2"><input type="checkbox" checked={f.travel_available} onChange={(e) => set("travel_available", e.target.checked)} /> Available to travel</label>
        <label className="flex items-center gap-2"><input type="checkbox" checked={f.is_emerging_talent} onChange={(e) => set("is_emerging_talent", e.target.checked)} /> List me as emerging talent</label>
      </div>
      <p className="text-xs text-ink-400 md:col-span-2">Only city, region and country are shown publicly. Never enter a home address.</p>
      <button className="btn-gold md:col-span-2" disabled={disabled}>{creator ? "Save storefront" : "Create storefront"}</button>
    </form>
  );
}
