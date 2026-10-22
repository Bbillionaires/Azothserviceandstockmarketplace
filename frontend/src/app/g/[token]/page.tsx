"use client";

import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { Alert } from "@/components/Alert";
import { ApiError, api } from "@/lib/api";
import type { Gallery, GalleryItem } from "@/lib/gallery";

/** Client proofing view. No account needed: the link (and optional password) grants access. */
export default function ClientGalleryPage() {
  const { token } = useParams<{ token: string }>();
  const [key, setKey] = useState<string | null>(null);
  const [g, setG] = useState<Gallery | null>(null);
  const [needsPassword, setNeedsPassword] = useState(false);
  const [password, setPassword] = useState("");
  const [open, setOpen] = useState<GalleryItem | null>(null);
  const [comment, setComment] = useState("");
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [onlySelected, setOnlySelected] = useState(false);

  const headers = useCallback((): Record<string, string> => (key ? { "X-Gallery-Key": key } : {}), [key]);

  const load = useCallback(async () => {
    try {
      setG(await api<Gallery>(`/galleries/public/${token}`, { headers: headers() }));
      setNeedsPassword(false);
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) setNeedsPassword(true);
      else setMsg({ ok: false, text: (e as Error).message });
    }
  }, [token, headers]);

  useEffect(() => {
    try { const k = sessionStorage.getItem(`gallery.${token}`); if (k) setKey(k); } catch {}
  }, [token]);
  useEffect(() => { load(); }, [load]);

  const unlock = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      const r = await api<{ key: string }>(`/galleries/public/${token}/unlock`, { method: "POST", json: { password } });
      try { sessionStorage.setItem(`gallery.${token}`, r.key); } catch {}
      setKey(r.key);
    } catch (err) {
      setMsg({ ok: false, text: (err as Error).message });
    }
  };

  const flag = async (item: GalleryItem, patch: Partial<Pick<GalleryItem, "is_favorite" | "is_selected">>) => {
    try {
      await api(`/galleries/public/${token}/items/${item.id}`, { method: "PATCH", json: patch, headers: headers() });
      await load();
    } catch (e) {
      setMsg({ ok: false, text: (e as Error).message });
    }
  };

  const post = async (body: string, itemId: string | null, revision: boolean) => {
    await api(`/galleries/public/${token}/comments`, { method: "POST", json: { body, item_id: itemId, is_revision_request: revision }, headers: headers() });
    setComment("");
    setMsg({ ok: true, text: revision ? "Revision request sent to the photographer" : "Comment sent" });
    await load();
  };

  if (needsPassword) {
    return (
      <form onSubmit={unlock} className="mx-auto max-w-sm space-y-4 px-4 py-24">
        <h1 className="font-display text-3xl">Private gallery</h1>
        {msg && <Alert kind="error">{msg.text}</Alert>}
        <div><label htmlFor="pw" className="label">Password</label><input id="pw" type="password" className="input" value={password} onChange={(e) => setPassword(e.target.value)} autoFocus /></div>
        <button className="btn-gold w-full">View gallery</button>
      </form>
    );
  }
  if (!g) return <p className="p-16 text-center text-ink-300">{msg?.text ?? "Loading gallery…"}</p>;
  const approved = g.status === "approved";
  const items = onlySelected ? g.items.filter((i) => i.is_selected) : g.items;

  return (
    <div className="mx-auto max-w-7xl px-4 py-10">
      <p className="text-xs uppercase tracking-[0.25em] text-gold-400">{g.creator_name} · Client gallery</p>
      <h1 className="font-display mt-2 text-4xl">{g.title}</h1>
      {g.message && <p className="mt-3 max-w-2xl whitespace-pre-line text-ink-200">{g.message}</p>}
      <div className="mt-4 flex flex-wrap items-center gap-3 text-sm">
        <span>{g.selected_count} selected{g.selection_limit ? ` of ${g.selection_limit}` : ""}</span>
        <label className="flex items-center gap-2"><input type="checkbox" checked={onlySelected} onChange={(e) => setOnlySelected(e.target.checked)} /> Show selected only</label>
        {approved ? <span className="text-emerald-300">Selection approved {g.client_approved_at ? new Date(g.client_approved_at).toLocaleDateString() : ""}</span> : (
          <button className="btn-gold text-sm" disabled={!g.selected_count} onClick={() => confirm("Approve your selection? The photographer will be notified.") &&
            api(`/galleries/public/${token}/approve`, { method: "POST", headers: headers() }).then(() => { setMsg({ ok: true, text: "Selection approved. Thank you!" }); load(); }).catch((e) => setMsg({ ok: false, text: e.message }))}>
            Approve selection
          </button>
        )}
      </div>
      {msg && <div className="mt-4"><Alert kind={msg.ok ? "success" : "error"}>{msg.text}</Alert></div>}

      <div className="masonry mt-6">
        {items.map((i) => (
          <figure key={i.id} className={`card relative overflow-hidden ${i.is_selected ? "border-gold-500" : ""}`}>
            <button className="block w-full" onClick={() => setOpen(i)} aria-label={`Open ${i.filename}`}>
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src={i.thumbnail_url ?? ""} alt={i.filename} loading="lazy" className="w-full" />
            </button>
            <figcaption className="flex items-center justify-between p-2 text-sm">
              <button aria-pressed={i.is_favorite} className={i.is_favorite ? "text-red-400" : "text-ink-400"} onClick={() => flag(i, { is_favorite: !i.is_favorite })}>♥ <span className="sr-only">Favorite</span></button>
              <button aria-pressed={i.is_selected} disabled={approved} className={`rounded-full px-3 py-0.5 text-xs ${i.is_selected ? "bg-gold-500 text-ink-950" : "border border-ink-600"}`} onClick={() => flag(i, { is_selected: !i.is_selected })}>
                {i.is_selected ? "Selected" : "Select"}
              </button>
            </figcaption>
          </figure>
        ))}
      </div>

      <section className="card mt-8 max-w-2xl space-y-3 p-5">
        <h2 className="font-display text-lg">Message the photographer</h2>
        {g.comments.filter((c) => !c.item_id).map((c) => <p key={c.id} className="text-sm"><strong>{c.author === "client" ? "You" : g.creator_name}:</strong> {c.body}</p>)}
        <textarea aria-label="Comment" className="input" value={comment} onChange={(e) => setComment(e.target.value)} />
        <div className="flex gap-2">
          <button className="btn-ghost text-sm" disabled={!comment.trim()} onClick={() => post(comment, null, false)}>Send comment</button>
          <button className="btn-ghost text-sm" disabled={!comment.trim()} onClick={() => post(comment, null, true)}>Request a revision</button>
        </div>
      </section>

      {open && (
        <div role="dialog" aria-modal="true" aria-label={open.filename} className="fixed inset-0 z-50 flex flex-col bg-black/95 p-4" onKeyDown={(e) => e.key === "Escape" && setOpen(null)}>
          <div className="flex justify-between text-sm">
            <span>{open.filename}</span>
            <button onClick={() => setOpen(null)} autoFocus>Close ✕</button>
          </div>
          <div className="flex min-h-0 flex-1 items-center justify-center py-4">
            {open.media_type === "video"
              ? <video src={open.preview_url ?? ""} controls className="max-h-full max-w-full" />
              // eslint-disable-next-line @next/next/no-img-element
              : <img src={open.preview_url ?? ""} alt={open.filename} className="max-h-full max-w-full object-contain" />}
          </div>
          <div className="mx-auto flex w-full max-w-3xl flex-wrap items-center gap-2">
            {g.comments.filter((c) => c.item_id === open.id).map((c) => <p key={c.id} className="w-full text-xs text-ink-300">{c.author}: {c.body}</p>)}
            <input aria-label="Comment on this image" className="input flex-1" placeholder="Comment on this image…" value={comment} onChange={(e) => setComment(e.target.value)} />
            <button className="btn-ghost text-sm" disabled={!comment.trim()} onClick={() => post(comment, open.id, true)}>Request edit</button>
            {g.allow_downloads && (
              <button className="btn-gold text-sm" onClick={async () => {
                const r = await api<{ url: string }>(`/galleries/public/${token}/items/${open.id}/download`, { method: "POST", headers: headers() });
                window.location.href = r.url;
              }}>Download original</button>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
