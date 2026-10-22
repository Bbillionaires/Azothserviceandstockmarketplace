"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { api, label, money } from "@/lib/api";
import type { Order } from "@/lib/orders";

export function OrdersPanel() {
  const [orders, setOrders] = useState<Order[] | null>(null);
  useEffect(() => { api<Order[]>("/orders/mine").then(setOrders).catch(() => setOrders([])); }, []);
  if (!orders) return <p className="text-ink-300">Loading orders…</p>;
  if (!orders.length) return <div className="card p-10 text-center text-ink-300">No purchases yet.</div>;
  return (
    <ul className="space-y-3">
      {orders.map((o) => (
        <li key={o.id} className="card p-4">
          <div className="flex flex-wrap justify-between gap-2">
            <p className="font-medium">{new Date(o.created_at).toLocaleDateString()} · {label(o.status)}</p>
            <p className="font-semibold">{money(o.total_cents, o.currency)}</p>
          </div>
          <ul className="mt-2 space-y-1 text-sm text-ink-300">
            {o.lines.map((l) => (
              <li key={l.id}>
                {l.asset_title} · {l.license_name}
                {l.certificate_number && <> · <Link className="text-gold-300 underline" href={`/licenses/verify/${l.certificate_number}`}>{l.certificate_number}</Link></>}
                {l.status !== "fulfilled" && l.status !== "pending" && <span className="text-ink-400"> ({label(l.status)})</span>}
              </li>
            ))}
          </ul>
          {o.status === "pending" && o.checkout_url && <a className="mt-2 inline-block text-sm text-gold-300 underline" href={o.checkout_url}>Complete payment</a>}
          {o.status === "paid" && <Link className="mt-2 inline-block text-sm text-gold-300 underline" href={`/checkout/success?order=${o.id}`}>Downloads</Link>}
        </li>
      ))}
    </ul>
  );
}
