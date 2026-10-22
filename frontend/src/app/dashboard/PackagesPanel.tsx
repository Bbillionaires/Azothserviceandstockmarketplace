"use client";

import { useEffect, useState } from "react";
import { Alert } from "@/components/Alert";
import { api, label, money } from "@/lib/api";
import { RIGHTS_LABEL, SERVICE_CATEGORIES, type Package } from "@/lib/production";

const EMPTY = { title: "", description: "", category: "real_estate", deliverables: "", price: "", delivery_days: "7", revisions_included: "1", rights_type: "nonexclusive", rights_terms: "", is_active: true };

export function PackagesPanel() {
  const [packages, setPackages] = useState<Package[]>([]);
  const [editing, setEditing] = useState<string | null>(null);
  const [f, setF] = useState(EMPTY);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const load = () => api<Package[]>("/packages/mine").then(setPackages).catch(() => {});
  useEffect(() => { load(); }, []);

  const edit = (p?: Package) => {
    setEditing(p?.id ?? "new");
    setF(p ? { ...p, price: String(p.price_cents / 100), delivery_days: String(p.delivery_days), revisions_included: String(p.revisions_included) } : EMPTY);
  };

  const save = async () => {
    const body = { ...f, price_cents: Math.round(Number(f.price) * 100), delivery_days: Number(f.delivery_days), revisions_included: Number(f.revisions_included), currency: "USD" };
    try {
      if (editing === "new") await api("/packages", { method: "POST", json: body });
      else await api(`/packages/${editing}`, { method: "PUT", json: body });
      setMsg({ ok: true, text: "Package saved. Existing bookings keep the terms they were booked on." });
      setEditing(null);
      load();
    } catch (e) {
      setMsg({ ok: false, text: (e as Error).message });
    }
  };

  return (
    <div className="space-y-4">
      {msg && <Alert kind={msg.ok ? "success" : "error"}>{msg.text}</Alert>}
      <div className="flex items-center justify-between">
        <p className="text-sm text-ink-300">Fixed-price offers clients can book straight from your storefront.</p>
        <button className="btn-gold text-sm" onClick={() => edit()}>New package</button>
      </div>
      {packages.map((p) => (
        <div key={p.id} className="card flex flex-wrap items-center justify-between gap-2 p-4">
          <span><span className="font-medium">{p.title}</span> <span className="text-xs text-ink-400">· {label(p.category)} · {p.delivery_days} days · {p.is_active ? "Active" : "Hidden"}</span></span>
          <span className="flex items-center gap-3"><strong>{money(p.price_cents, p.currency)}</strong><button className="text-sm text-gold-300 underline" onClick={() => edit(p)}>Edit</button></span>
        </div>
      ))}
      {editing && (
        <div className="card grid gap-4 p-6 md:grid-cols-2">
          <div className="md:col-span-2"><label htmlFor="pk-t" className="label">Title</label><input id="pk-t" className="input" value={f.title} onChange={(e) => setF({ ...f, title: e.target.value })} /></div>
          <div className="md:col-span-2"><label htmlFor="pk-d" className="label">Description</label><textarea id="pk-d" className="input" value={f.description} onChange={(e) => setF({ ...f, description: e.target.value })} /></div>
          <div><label htmlFor="pk-c" className="label">Category</label><select id="pk-c" className="input" value={f.category} onChange={(e) => setF({ ...f, category: e.target.value })}>{SERVICE_CATEGORIES.map((c) => <option key={c} value={c}>{label(c)}</option>)}</select></div>
          <div><label htmlFor="pk-p" className="label">Price (USD)</label><input id="pk-p" type="number" min="1" className="input" value={f.price} onChange={(e) => setF({ ...f, price: e.target.value })} /></div>
          <div><label htmlFor="pk-dd" className="label">Delivery (days)</label><input id="pk-dd" type="number" min="1" className="input" value={f.delivery_days} onChange={(e) => setF({ ...f, delivery_days: e.target.value })} /></div>
          <div><label htmlFor="pk-r" className="label">Revisions included</label><input id="pk-r" type="number" min="0" max="10" className="input" value={f.revisions_included} onChange={(e) => setF({ ...f, revisions_included: e.target.value })} /></div>
          <div className="md:col-span-2"><label htmlFor="pk-del" className="label">Deliverables</label><textarea id="pk-del" className="input" value={f.deliverables} onChange={(e) => setF({ ...f, deliverables: e.target.value })} /></div>
          <div><label htmlFor="pk-rt" className="label">Rights</label><select id="pk-rt" className="input" value={f.rights_type} onChange={(e) => setF({ ...f, rights_type: e.target.value })}>{Object.entries(RIGHTS_LABEL).map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select></div>
          <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={f.is_active} onChange={(e) => setF({ ...f, is_active: e.target.checked })} /> Show on storefront</label>
          <div className="md:col-span-2"><label htmlFor="pk-terms" className="label">Rights terms</label><textarea id="pk-terms" className="input" value={f.rights_terms} onChange={(e) => setF({ ...f, rights_terms: e.target.value })} /></div>
          <div className="flex gap-2 md:col-span-2"><button className="btn-gold" onClick={save}>Save package</button><button className="btn-ghost" onClick={() => setEditing(null)}>Cancel</button></div>
        </div>
      )}
    </div>
  );
}
