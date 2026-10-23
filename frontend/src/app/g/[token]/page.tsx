"use client";

import { useParams, useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useState } from "react";
import { Alert } from "@/components/Alert";
import { Turnstile, captchaEnabled } from "@/components/Turnstile";
import { ApiError, api, money } from "@/lib/api";
import type { Gallery, GalleryItem, GalleryOrder } from "@/lib/gallery";

type CartLine = { item_id: string; kind: "digital" | "print"; print_option_id?: string; quantity: number };

/** Client proofing view. No account needed: the link (and optional password) grants access. */
export default function ClientGalleryPage() {
  return <Suspense><ClientGallery /></Suspense>;
}

function ClientGallery() {
  const { token } = useParams<{ token: string }>();
  const params = useSearchParams();
  const [cart, setCart] = useState<CartLine[]>([]);
  const [captcha, setCaptcha] = useState<string | null>(null);
  const [captchaReset, setCaptchaReset] = useState(0);
  const [placed, setPlaced] = useState<GalleryOrder | null>(null);
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
      const r = await api<{ key: string }>(`/galleries/public/${token}/unlock`, { method: "POST", json: { password, captcha_token: captcha } });
      try { sessionStorage.setItem(`gallery.${token}`, r.key); } catch {}
      setKey(r.key);
    } catch (err) {
      setMsg({ ok: false, text: (err as Error).message });
      setCaptchaReset((n) => n + 1);
    }
  };

  // Returning from checkout: show the order (the webhook may take a moment).
  const orderId = params.get("order");
  useEffect(() => {
    if (!orderId || !g) return;
    let tries = 0;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const o = await api<GalleryOrder>(`/galleries/public/${token}/orders/${orderId}`, { headers: headers() });
        setPlaced(o);
        if (o.status === "pending" && ++tries < 10) timer = setTimeout(poll, 2000);
        else load();
      } catch {}
    };
    poll();
    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [orderId, g === null, token]);

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
        <Turnstile onToken={setCaptcha} resetKey={captchaReset} />
        <button className="btn-gold w-full" disabled={captchaEnabled && !captcha}>View gallery</button>
      </form>
    );
  }
  if (!g) return <p className="p-16 text-center text-ink-300">{msg?.text ?? "Loading gallery…"}</p>;
  const approved = g.status === "approved";
  const items = onlySelected ? g.items.filter((i) => i.is_selected) : g.items;
  const canDownload = (i: GalleryItem) => g.allow_downloads || i.download_unlocked;
  const sellsDownloads = g.payments_enabled && !g.allow_downloads && !!g.download_price_cents;
  const sellsPrints = g.payments_enabled && g.print_options.length > 0;
  const inCart = (i: GalleryItem) => cart.some((c) => c.item_id === i.id && c.kind === "digital");
  const addDigital = (i: GalleryItem) => setCart((c) => (inCart(i) ? c : [...c, { item_id: i.id, kind: "digital", quantity: 1 }]));
  const addPrint = (i: GalleryItem, optionId: string) =>
    setCart((c) => [...c, { item_id: i.id, kind: "print", print_option_id: optionId, quantity: 1 }]);

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
              {sellsDownloads && !canDownload(i) && (
                <button className="text-xs text-gold-300 underline disabled:no-underline disabled:opacity-60" disabled={inCart(i)} onClick={() => addDigital(i)}>
                  {inCart(i) ? "In cart" : `Buy ${money(g.download_price_cents, g.currency)}`}
                </button>
              )}
              {canDownload(i) && !g.allow_downloads && <span className="text-xs text-emerald-300">Purchased</span>}
              <button aria-pressed={i.is_selected} disabled={approved} className={`rounded-full px-3 py-0.5 text-xs ${i.is_selected ? "bg-gold-500 text-ink-950" : "border border-ink-600"}`} onClick={() => flag(i, { is_selected: !i.is_selected })}>
                {i.is_selected ? "Selected" : "Select"}
              </button>
            </figcaption>
          </figure>
        ))}
      </div>

      {placed && (
        <div className="mt-6">
          <Alert kind={placed.status === "pending" ? "info" : "success"}>
            {placed.status === "pending"
              ? "Confirming your payment…"
              : `Thank you! Order of ${money(placed.total_cents, placed.currency)} confirmed.${placed.items.some((l) => l.kind === "digital") ? " Your downloads are unlocked." : ""}${placed.items.some((l) => l.kind === "print") ? " The photographer will ship your prints and email tracking details." : ""}`}
          </Alert>
        </div>
      )}

      {(sellsDownloads || sellsPrints) && (
        <GalleryCart g={g} token={token} headers={headers} cart={cart} setCart={setCart} onError={(text) => setMsg({ ok: false, text })} />
      )}

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
            {sellsPrints && (
              <select aria-label="Order a print" className="input w-auto py-1 text-sm" value="" onChange={(e) => { if (e.target.value) { addPrint(open, e.target.value); setMsg({ ok: true, text: "Print added to your order" }); } }}>
                <option value="">Order a print…</option>
                {g.print_options.map((o) => <option key={o.id} value={o.id}>{o.name} · {money(o.price_cents, g.currency)}</option>)}
              </select>
            )}
            {sellsDownloads && !canDownload(open) && (
              <button className="btn-ghost text-sm" disabled={inCart(open)} onClick={() => addDigital(open)}>{inCart(open) ? "In cart" : `Buy download · ${money(g.download_price_cents, g.currency)}`}</button>
            )}
            {canDownload(open) && (
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

function GalleryCart({ g, token, headers, cart, setCart, onError }: {
  g: Gallery; token: string; headers: () => Record<string, string>; cart: CartLine[];
  setCart: (fn: (c: CartLine[]) => CartLine[]) => void; onError: (text: string) => void;
}) {
  const [form, setForm] = useState({ client_name: g.client_name, client_email: "", name: g.client_name, line1: "", line2: "", city: "", region: "", postal_code: "", country: "US" });
  const [busy, setBusy] = useState(false);
  const name = (id: string) => g.items.find((i) => i.id === id)?.filename ?? "Image";
  const option = (id?: string) => g.print_options.find((o) => o.id === id);
  const price = (l: CartLine) => (l.kind === "digital" ? g.download_price_cents ?? 0 : option(l.print_option_id)?.price_cents ?? 0) * l.quantity;
  const total = cart.reduce((sum, l) => sum + price(l), 0);
  const hasPrints = cart.some((l) => l.kind === "print");
  const set = (k: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement>) => setForm({ ...form, [k]: e.target.value });

  const checkout = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    try {
      const { client_name, client_email, ...addr } = form;
      const r = await api<{ checkout_url: string }>(`/galleries/public/${token}/orders`, {
        method: "POST", headers: headers(),
        json: { client_name, client_email, items: cart, shipping_address: hasPrints ? addr : null },
      });
      window.location.href = r.checkout_url;
    } catch (err) {
      onError((err as Error).message);
      setBusy(false);
    }
  };

  return (
    <section className="card mt-8 max-w-2xl space-y-4 p-5" aria-label="Your order">
      <div>
        <h2 className="font-display text-lg">Downloads &amp; prints</h2>
        <p className="text-xs text-ink-300">
          {g.download_price_cents && !g.allow_downloads ? `Full-resolution downloads ${money(g.download_price_cents, g.currency)} each. ` : ""}
          {g.print_options.length ? `Prints are made and shipped by ${g.creator_name}.` : ""}
        </p>
      </div>
      {cart.length === 0 ? <p className="text-sm text-ink-400">Choose “Buy” on an image, or open it to order a print.</p> : (
        <form onSubmit={checkout} className="space-y-4">
          <ul className="divide-y divide-ink-700 text-sm">
            {cart.map((l, idx) => (
              <li key={idx} className="flex items-center justify-between gap-2 py-2">
                <span className="truncate">{l.kind === "digital" ? "Download" : option(l.print_option_id)?.name} · {name(l.item_id)}</span>
                <span className="flex items-center gap-2">
                  {l.kind === "print" && (
                    <input aria-label="Quantity" type="number" min={1} max={50} className="input w-16 py-1" value={l.quantity}
                      onChange={(e) => setCart((c) => c.map((x, j) => (j === idx ? { ...x, quantity: Math.max(1, Math.min(50, Number(e.target.value) || 1)) } : x)))} />
                  )}
                  <span>{money(price(l), g.currency)}</span>
                  <button type="button" className="text-ink-400 hover:text-red-300" aria-label="Remove" onClick={() => setCart((c) => c.filter((_, j) => j !== idx))}>✕</button>
                </span>
              </li>
            ))}
          </ul>
          <div className="grid gap-3 sm:grid-cols-2">
            <div><label htmlFor="cn" className="label">Your name</label><input id="cn" className="input" required value={form.client_name} onChange={set("client_name")} /></div>
            <div><label htmlFor="ce" className="label">Email for your receipt</label><input id="ce" type="email" className="input" required value={form.client_email} onChange={set("client_email")} /></div>
          </div>
          {hasPrints && (
            <fieldset className="grid gap-3 sm:grid-cols-2">
              <legend className="label">Shipping address</legend>
              <div className="sm:col-span-2"><label htmlFor="sn" className="label">Recipient</label><input id="sn" className="input" required value={form.name} onChange={set("name")} /></div>
              <div className="sm:col-span-2"><label htmlFor="s1" className="label">Address</label><input id="s1" className="input" required value={form.line1} onChange={set("line1")} /></div>
              <div className="sm:col-span-2"><label htmlFor="s2" className="label">Apartment, suite (optional)</label><input id="s2" className="input" value={form.line2} onChange={set("line2")} /></div>
              <div><label htmlFor="sc" className="label">City</label><input id="sc" className="input" required value={form.city} onChange={set("city")} /></div>
              <div><label htmlFor="sr" className="label">State / region</label><input id="sr" className="input" value={form.region} onChange={set("region")} /></div>
              <div><label htmlFor="sp" className="label">Postal code</label><input id="sp" className="input" value={form.postal_code} onChange={set("postal_code")} /></div>
              <div><label htmlFor="sy" className="label">Country code</label><input id="sy" className="input" required maxLength={2} value={form.country} onChange={set("country")} /></div>
            </fieldset>
          )}
          <div className="flex items-center justify-between">
            <span className="font-semibold">Subtotal {money(total, g.currency)} <span className="text-xs font-normal text-ink-400">+ tax at checkout</span></span>
            <button className="btn-gold" disabled={busy}>{busy ? "Redirecting…" : "Checkout"}</button>
          </div>
        </form>
      )}
    </section>
  );
}
