"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { Alert } from "@/components/Alert";
import { api, label, money } from "@/lib/api";
import { RIGHTS_LABEL, type Package } from "@/lib/production";
import { useSession } from "@/lib/session";

type Reputation = { average: number; count: number; completed_projects: number; reviews: { id: string; rating: number; body: string; created_at: string; project_title: string; reviewer_name: string }[] };

export function StorefrontServices({ handle, name, packages, reputation }: { handle: string; name: string; packages: Package[]; reputation: Reputation }) {
  const { user } = useSession();
  const router = useRouter();
  const [booking, setBooking] = useState<Package | null>(null);
  const [brief, setBrief] = useState("");
  const [agree, setAgree] = useState(false);
  const [contact, setContact] = useState(false);
  const [message, setMessage] = useState("");
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const own = user?.creator_handle === handle;

  const book = async () => {
    try {
      const r = await api<{ project_id: string }>(`/packages/${booking!.id}/book`, { method: "POST", json: { brief, accept_terms: agree } });
      router.push(`/projects/${r.project_id}`);
    } catch (e) {
      setMsg({ ok: false, text: (e as Error).message });
    }
  };

  return (
    <div className="space-y-8">
      {msg && <Alert kind={msg.ok ? "success" : "error"}>{msg.text}</Alert>}
      {packages.length > 0 && (
        <section>
          <h2 className="font-display mb-4 text-2xl">Services</h2>
          <div className="grid gap-4 md:grid-cols-2">
            {packages.map((p) => (
              <div key={p.id} className="card flex flex-col p-5">
                <div className="flex justify-between gap-2"><h3 className="font-medium">{p.title}</h3><span className="font-display text-xl text-gold-300">{money(p.price_cents, p.currency)}</span></div>
                <p className="text-xs text-ink-400">{label(p.category)} · {p.delivery_days}-day delivery · {p.revisions_included} revisions · {RIGHTS_LABEL[p.rights_type]}</p>
                <p className="mt-2 flex-1 whitespace-pre-line text-sm text-ink-300">{p.description}</p>
                {!own && (user
                  ? <button className="btn-gold mt-4" onClick={() => { setBooking(p); setAgree(false); }}>Book</button>
                  : <a className="btn-gold mt-4" href={`/login?next=/creators/${handle}`}>Sign in to book</a>)}
              </div>
            ))}
          </div>
        </section>
      )}

      <section>
        <h2 className="font-display mb-2 text-2xl">Reviews</h2>
        <p className="text-sm text-ink-300">
          {reputation.count ? <><span className="text-gold-300">{"★".repeat(Math.round(reputation.average))}</span> {reputation.average.toFixed(1)} from {reputation.count} verified reviews · </> : "No reviews yet · "}
          {reputation.completed_projects} completed projects
        </p>
        <ul className="mt-3 space-y-3">
          {reputation.reviews.map((r) => (
            <li key={r.id} className="card p-4 text-sm">
              <p><span className="text-gold-300">{"★".repeat(r.rating)}</span> <span className="text-ink-400">{r.reviewer_name} · {r.project_title} · {new Date(r.created_at).toLocaleDateString()} · Verified booking</span></p>
              {r.body && <p className="mt-1 text-ink-200">{r.body}</p>}
            </li>
          ))}
        </ul>
      </section>

      {!own && (
        <section>
          {!contact ? <button className="btn-ghost" onClick={() => setContact(true)}>Contact {name}</button> : user ? (
            <div className="card max-w-xl space-y-2 p-4">
              <label htmlFor="contact" className="label">Message to {name}</label>
              <textarea id="contact" className="input" value={message} onChange={(e) => setMessage(e.target.value)} />
              <button className="btn-gold text-sm" disabled={!message.trim()} onClick={() => api<{ id: string }>("/conversations", { method: "POST", json: { creator_handle: handle, body: message } })
                .then((c) => router.push(`/messages?c=${c.id}`)).catch((e) => setMsg({ ok: false, text: e.message }))}>Send</button>
            </div>
          ) : <a className="btn-gold" href={`/login?next=/creators/${handle}`}>Sign in to message</a>}
        </section>
      )}

      {booking && (
        <div role="dialog" aria-modal="true" aria-labelledby="book-title" className="fixed inset-0 z-50 grid place-items-center bg-black/70 p-4">
          <div className="card max-h-[90vh] w-full max-w-lg space-y-4 overflow-y-auto p-6">
            <h2 id="book-title" className="font-display text-2xl">Book: {booking.title}</h2>
            <p className="text-sm">{money(booking.price_cents, booking.currency)} · {booking.delivery_days}-day delivery · {booking.revisions_included} revisions</p>
            {booking.deliverables && <p className="whitespace-pre-line text-sm text-ink-300">{booking.deliverables}</p>}
            <div className="rounded-lg bg-ink-950 p-3 text-sm"><strong>Rights: {RIGHTS_LABEL[booking.rights_type]}.</strong> <span className="text-ink-300">{booking.rights_terms}</span></div>
            <div><label htmlFor="brief" className="label">Your brief (location, dates, details)</label><textarea id="brief" className="input min-h-24" value={brief} onChange={(e) => setBrief(e.target.value)} /></div>
            <label className="flex items-start gap-2 text-sm"><input type="checkbox" className="mt-1" checked={agree} onChange={(e) => setAgree(e.target.checked)} /> I accept the package terms and rights above. I&apos;ll fund the booking before work starts; funds are released when I approve the delivery.</label>
            <div className="flex justify-end gap-2"><button className="btn-ghost" onClick={() => setBooking(null)}>Cancel</button><button className="btn-gold" disabled={!agree} onClick={book}>Book now</button></div>
          </div>
        </div>
      )}
    </div>
  );
}
