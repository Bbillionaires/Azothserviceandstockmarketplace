"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { Alert } from "@/components/Alert";
import { api, money } from "@/lib/api";
import type { Order } from "@/lib/orders";

/** Development-only stand-in for the hosted payment page (fake provider). */
function DevPay() {
  const id = useSearchParams().get("order") ?? "";
  const router = useRouter();
  const [order, setOrder] = useState<Order | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api<Order>(`/orders/${id}`).then(setOrder).catch((e) => setError(e.message));
  }, [id]);

  const finish = async (outcome: "paid" | "expired") => {
    try {
      await api(`/payments/dev/complete/${id}?outcome=${outcome}`, { method: "POST" });
      if (order?.project_id) router.push(`/projects/${order.project_id}`);
      else router.push(outcome === "paid" ? `/checkout/success?order=${id}` : `/cart?canceled=${id}`);
    } catch (e) {
      setError((e as Error).message);
    }
  };

  return (
    <div className="mx-auto max-w-md px-4 py-16">
      <Alert kind="info">Test payment page. No money moves. In production this step is Stripe Checkout.</Alert>
      {error && <div className="mt-4"><Alert>{error}</Alert></div>}
      {order && (
        <div className="card mt-6 space-y-4 p-6">
          <h1 className="font-display text-2xl">Pay {money(order.total_cents, order.currency)}</h1>
          <ul className="text-sm text-ink-300">{order.lines.map((l) => <li key={l.id}>{l.asset_title} · {l.license_name}</li>)}</ul>
          <button className="btn-gold w-full" onClick={() => finish("paid")}>Simulate successful payment</button>
          <button className="btn-ghost w-full" onClick={() => finish("expired")}>Simulate abandoned checkout</button>
        </div>
      )}
    </div>
  );
}

export default function DevPayPage() {
  return <Suspense><DevPay /></Suspense>;
}
