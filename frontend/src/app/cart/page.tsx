"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { Alert } from "@/components/Alert";
import { api, label, money } from "@/lib/api";
import { useCart } from "@/lib/cart";
import type { Order } from "@/lib/orders";
import { useSession } from "@/lib/session";

function Cart() {
  const { items, remove, update } = useCart();
  const { user } = useSession();
  const router = useRouter();
  const canceled = useSearchParams().get("canceled");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const currency = items[0]?.currency ?? "USD";
  const subtotal = items.reduce((a, i) => a + i.price_cents, 0);

  const checkout = async () => {
    setBusy(true);
    setError("");
    try {
      // One idempotency key per checkout attempt: a double click cannot create two orders.
      const key = sessionStorage.getItem("checkout.key") ?? crypto.randomUUID();
      sessionStorage.setItem("checkout.key", key);
      const order = await api<Order>("/orders", {
        method: "POST",
        json: { idempotency_key: key, items: items.map((i) => ({ price_listing_id: i.price_listing_id, licensee_name: i.licensee_name || undefined })) },
      });
      sessionStorage.removeItem("checkout.key");
      if (order.checkout_url) window.location.href = order.checkout_url;
      else router.push(`/checkout/success?order=${order.id}`);
    } catch (e) {
      sessionStorage.removeItem("checkout.key");
      setError((e as Error).message);
      setBusy(false);
    }
  };

  return (
    <div className="mx-auto max-w-4xl px-4 py-10">
      <h1 className="font-display text-4xl">Cart</h1>
      {canceled && <div className="mt-4"><Alert kind="info">Checkout was canceled. Your cart is unchanged.</Alert></div>}
      {items.length === 0 ? (
        <div className="card mt-8 p-10 text-center text-ink-300">
          Your cart is empty. <Link href="/search" className="text-gold-300 underline">Browse media</Link>
        </div>
      ) : (
        <div className="mt-8 grid gap-8 lg:grid-cols-[1fr_300px]">
          <ul className="space-y-3">
            {items.map((i) => (
              <li key={i.price_listing_id} className="card flex gap-4 p-4">
                {i.thumbnail_url
                  // eslint-disable-next-line @next/next/no-img-element
                  ? <img src={i.thumbnail_url} alt="" className="h-20 w-28 rounded object-cover" />
                  : <span className="h-20 w-28 rounded bg-ink-800" />}
                <div className="min-w-0 flex-1 space-y-2">
                  <div className="flex justify-between gap-2">
                    <Link href={`/media/${i.asset_id}`} className="truncate font-medium hover:text-gold-300">{i.title}</Link>
                    <span className="font-semibold text-gold-300">{money(i.price_cents, i.currency)}</span>
                  </div>
                  <p className="text-xs text-ink-400">{i.license_name} · {label(i.size_tier)}</p>
                  <div className="flex items-center gap-2">
                    <label htmlFor={`ln-${i.price_listing_id}`} className="shrink-0 text-xs text-ink-300">Licensed to</label>
                    <input id={`ln-${i.price_listing_id}`} className="input py-1 text-sm" placeholder={user?.display_name ?? "Your name or company"}
                      value={i.licensee_name ?? ""} onChange={(e) => update(i.price_listing_id, { licensee_name: e.target.value })} />
                    <button className="text-xs text-ink-400 hover:text-red-300" onClick={() => remove(i.price_listing_id)}>Remove</button>
                  </div>
                </div>
              </li>
            ))}
          </ul>
          <aside className="card h-fit space-y-4 p-6">
            <div className="flex justify-between"><span className="text-ink-300">Subtotal</span><span>{money(subtotal, currency)}</span></div>
            <p className="text-xs text-ink-400">Sales tax, if any, is calculated at checkout. Prices are confirmed by the server when you check out.</p>
            {error && <Alert>{error}</Alert>}
            {user ? (
              user.email_verified
                ? <button className="btn-gold w-full" disabled={busy} onClick={checkout}>{busy ? "Starting checkout…" : "Checkout"}</button>
                : <Alert kind="info">Verify your email address before purchasing.</Alert>
            ) : (
              <Link href="/login?next=/cart" className="btn-gold w-full">Sign in to check out</Link>
            )}
            <p className="text-xs text-ink-400">Payments are processed securely by our payment provider. We never see your card details.</p>
          </aside>
        </div>
      )}
    </div>
  );
}

export default function CartPage() {
  return <Suspense><Cart /></Suspense>;
}
