"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { Alert } from "@/components/Alert";
import { api, label } from "@/lib/api";
import type { Gallery } from "@/lib/gallery";

export default function ManageGallery() {
  const { id } = useParams<{ id: string }>();
  const [g, setG] = useState<Gallery | null>(null);
  const [form, setForm] = useState({ title: "", message: "", client_name: "", client_email: "", password: "", clear_password: false, expires_at: "", allow_downloads: false, selection_limit: "" });
  const [uploading, setUploading] = useState(0);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);

  const load = useCallback(async () => {
    const data = await api<Gallery>(`/galleries/${id}`);
    setG(data);
    return data;
  }, [id]);

  useEffect(() => {
    load().then((d) => setForm({ title: d.title, message: d.message, client_name: d.client_name, client_email: d.client_email ?? "", password: "", clear_password: false,
      expires_at: d.expires_at ? d.expires_at.slice(0, 10) : "", allow_downloads: d.allow_downloads, selection_limit: d.selection_limit ? String(d.selection_limit) : "" }))
      .catch((e) => setMsg({ ok: false, text: e.message }));
  }, [load]);

  useEffect(() => {
    if (!g?.items.some((i) => i.status === "processing")) return;
    const t = setTimeout(load, 2500);
    return () => clearTimeout(t);
  }, [g, load]);

  const act = async (fn: () => Promise<unknown>, ok: string) => {
    try { await fn(); setMsg({ ok: true, text: ok }); await load(); } catch (e) { setMsg({ ok: false, text: (e as Error).message }); }
  };

  const save = () => act(() => api(`/galleries/${id}`, { method: "PUT", json: {
    ...form, client_email: form.client_email || null, password: form.password || null, expires_at: form.expires_at || null,
    selection_limit: form.selection_limit ? Number(form.selection_limit) : null,
  } }), "Settings saved");

  const upload = async (files: FileList | null) => {
    if (!files) return;
    setUploading(files.length);
    for (const file of Array.from(files)) {
      const data = new FormData();
      data.set("file", file);
      const res = await fetch(`/api/v1/galleries/${id}/items`, { method: "POST", body: data, credentials: "include", headers: { "X-Requested-With": "fetch" } });
      if (!res.ok) setMsg({ ok: false, text: `${file.name}: ${(await res.json().catch(() => ({}))).detail ?? "upload failed"}` });
      setUploading((n) => n - 1);
    }
    await load();
  };

  if (!g) return <p className="p-10 text-center text-ink-300">{msg?.text ?? "Loading…"}</p>;
  const commentsFor = (itemId: string | null) => g.comments.filter((c) => c.item_id === itemId);

  return (
    <div className="mx-auto max-w-7xl px-4 py-10">
      <Link href="/dashboard?tab=galleries" className="text-sm text-ink-300 hover:text-gold-300">← Galleries</Link>
      <div className="mt-2 flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="font-display text-4xl">{g.title}</h1>
          <p className="text-sm text-ink-300">{label(g.status)} · {g.items.length} items · {g.selected_count} selected by client{g.last_viewed_at ? ` · last viewed ${new Date(g.last_viewed_at).toLocaleString()}` : ""}</p>
        </div>
        <div className="flex gap-2">
          <button className="btn-gold" onClick={() => act(() => api(`/galleries/${id}/share`, { method: "POST" }), g.client_email ? "Shared and emailed to the client" : "Gallery is live")}>{g.status === "draft" ? "Share with client" : "Resend link"}</button>
          {g.status !== "archived" && <button className="btn-ghost" onClick={() => act(() => api(`/galleries/${id}/archive`, { method: "POST" }), "Archived")}>Archive</button>}
        </div>
      </div>
      {msg && <div className="mt-4"><Alert kind={msg.ok ? "success" : "error"}>{msg.text}</Alert></div>}
      {g.status !== "draft" && g.share_url && (
        <div className="card mt-4 flex flex-wrap items-center gap-2 p-4 text-sm">
          <span className="text-ink-300">Client link:</span>
          <input className="input flex-1" readOnly value={g.share_url} aria-label="Client link" />
          <button className="btn-ghost text-sm" onClick={() => navigator.clipboard.writeText(g.share_url!)}>Copy</button>
          {g.has_password && <span className="text-xs text-ink-400">Password protected; send the password separately.</span>}
        </div>
      )}

      <div className="mt-8 grid gap-8 lg:grid-cols-[1fr_340px]">
        <section>
          <label className="card flex cursor-pointer flex-col items-center justify-center gap-2 border-dashed p-8 text-center text-ink-300 hover:border-gold-600">
            <span className="font-medium text-white">Add photos or video</span>
            <span className="text-xs">JPEG, PNG, TIFF, WebP, MP4, MOV. Clients see watermarked proofs; originals stay private.</span>
            <input type="file" multiple accept="image/jpeg,image/png,image/tiff,image/webp,video/mp4,video/quicktime" className="sr-only" onChange={(e) => upload(e.target.files)} />
            {uploading > 0 && <span className="text-gold-300">Uploading… {uploading} left</span>}
          </label>
          <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
            {g.items.map((i) => (
              <figure key={i.id} className={`card overflow-hidden ${i.is_selected ? "border-gold-500" : ""}`}>
                {i.thumbnail_url
                  // eslint-disable-next-line @next/next/no-img-element
                  ? <img src={i.thumbnail_url} alt={i.filename} className="aspect-[4/3] w-full object-cover" />
                  : <div className="grid aspect-[4/3] place-items-center bg-ink-800 text-xs text-ink-300">{i.status === "failed" ? i.processing_error : "Processing…"}</div>}
                <figcaption className="flex items-center justify-between gap-1 p-2 text-xs">
                  <span className="truncate">{i.is_selected && "✓ "}{i.is_favorite && "♥ "}{i.filename}</span>
                  <button className="text-ink-400 hover:text-red-300" aria-label={`Remove ${i.filename}`} onClick={() => act(() => api(`/galleries/${id}/items/${i.id}`, { method: "DELETE" }), "Removed")}>✕</button>
                </figcaption>
                {commentsFor(i.id).map((c) => <p key={c.id} className={`px-2 pb-2 text-xs ${c.is_revision_request ? "text-amber-300" : "text-ink-300"}`}>{c.author}: {c.body}</p>)}
              </figure>
            ))}
          </div>
        </section>
        <aside className="space-y-4">
          <div className="card space-y-3 p-5">
            <h2 className="font-display text-lg">Settings</h2>
            <div><label htmlFor="gt" className="label">Title</label><input id="gt" className="input" value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} /></div>
            <div><label htmlFor="gm" className="label">Message to client</label><textarea id="gm" className="input" value={form.message} onChange={(e) => setForm({ ...form, message: e.target.value })} /></div>
            <div><label htmlFor="gcn" className="label">Client name</label><input id="gcn" className="input" value={form.client_name} onChange={(e) => setForm({ ...form, client_name: e.target.value })} /></div>
            <div><label htmlFor="gce" className="label">Client email</label><input id="gce" type="email" className="input" value={form.client_email} onChange={(e) => setForm({ ...form, client_email: e.target.value })} /></div>
            <div><label htmlFor="gp" className="label">{g.has_password ? "New password (leave blank to keep)" : "Password (optional)"}</label><input id="gp" type="password" className="input" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} /></div>
            {g.has_password && <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={form.clear_password} onChange={(e) => setForm({ ...form, clear_password: e.target.checked })} /> Remove password</label>}
            <div><label htmlFor="gx" className="label">Link expires</label><input id="gx" type="date" className="input" value={form.expires_at} onChange={(e) => setForm({ ...form, expires_at: e.target.value })} /></div>
            <div><label htmlFor="gl" className="label">Selection limit</label><input id="gl" type="number" min="1" className="input" value={form.selection_limit} onChange={(e) => setForm({ ...form, selection_limit: e.target.value })} /></div>
            <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={form.allow_downloads} onChange={(e) => setForm({ ...form, allow_downloads: e.target.checked })} /> Allow original downloads</label>
            <button className="btn-gold w-full" onClick={save}>Save settings</button>
          </div>
          {commentsFor(null).length > 0 && (
            <div className="card space-y-2 p-5 text-sm">
              <h2 className="font-display text-lg">General comments</h2>
              {commentsFor(null).map((c) => <p key={c.id} className={c.is_revision_request ? "text-amber-300" : ""}>{c.author}: {c.body}</p>)}
            </div>
          )}
        </aside>
      </div>
    </div>
  );
}
