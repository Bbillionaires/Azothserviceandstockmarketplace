"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { Alert } from "@/components/Alert";
import { api, label, money } from "@/lib/api";
import { useCart } from "@/lib/cart";
import type { Order } from "@/lib/orders";

function Success() {
  const id = useSearchParams().get("order") ?? "";
  const { clear } = useCart();
  const [order, setOrder] = useState<Order | null>(null);
  const [error, setError] = useState("");
  const [tries, setTries] = useState(0);

  // The payment confirmation arrives by webhook, usually within seconds; poll until it lands.
  useEffect(() => {
    let stop = false;
    api<Order>(`/orders/${id}`).then((o) => {
      if (stop) return;
      setOrder(o);
      if (o.status === "paid") clear();
      else if (o.status === "pending" && tries < 20) setTimeout(() => setTries((t) => t + 1), 1500);
    }).catch((e) => setError(e.message));
    return () => { stop = true; };
  }, [id, tries, clear]);

  const download = async (cert: string) => {
    const d = await api<{ download_url: string }>(`/licenses/${cert}/download`, { method: "POST" });
    window.location.href = d.download_url;
  };

  return (
    <div className="mx-auto max-w-3xl px-4 py-16">
      {error && <Alert>{error}</Alert>}
      {!order ? <p className="text-ink-300">Loading your order…</p> : order.status === "pending" ? (
        <div className="space-y-3">
          <h1 className="font-display text-3xl">Confirming your payment…</h1>
          <p className="text-ink-300">{tries < 20 ? "This usually takes a few seconds." : "Still waiting for confirmation from the payment provider. Your licenses will appear in your dashboard as soon as it arrives."}</p>
        </div>
      ) : (
        <div className="space-y-6">
          <p className="text-xs uppercase tracking-[0.25em] text-gold-400">Order {label(order.status)}</p>
          <h1 className="font-display text-4xl">{order.status === "paid" ? "Thank you. Your licenses are ready." : "Order details"}</h1>
          <ul className="space-y-3">
            {order.lines.map((l) => (
              <li key={l.id} className="card flex flex-col gap-3 p-4 sm:flex-row sm:items-center sm:justify-between">
                <div>
                  <p className="font-medium">{l.asset_title}</p>
                  <p className="text-xs text-ink-400">{l.license_name} · licensed to {l.licensee_name} · {money(l.unit_price_cents, order.currency)}</p>
                </div>
                {l.certificate_number && l.status === "fulfilled" && (
                  <div className="flex gap-2">
                    <Link className="btn-ghost text-sm" href={`/licenses/verify/${l.certificate_number}`}>Certificate</Link>
                    <button className="btn-gold text-sm" onClick={() => download(l.certificate_number!)}>Download original</button>
                  </div>
                )}
              </li>
            ))}
          </ul>
          <dl className="card grid grid-cols-2 gap-2 p-5 text-sm">
            <dt className="text-ink-400">Subtotal</dt><dd className="text-right">{money(order.subtotal_cents, order.currency)}</dd>
            <dt className="text-ink-400">Tax</dt><dd className="text-right">{money(order.tax_cents, order.currency)}</dd>
            <dt className="font-semibold">Total paid</dt><dd className="text-right font-semibold">{money(order.total_cents, order.currency)}</dd>
          </dl>
          <Link href="/dashboard?tab=orders" className="text-sm text-gold-300 underline">All orders and licenses</Link>
        </div>
      )}
    </div>
  );
}

export default function SuccessPage() {
  return <Suspense><Success /></Suspense>;
}
