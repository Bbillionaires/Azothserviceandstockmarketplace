"use client";

import { useCallback, useEffect, useState } from "react";

/** Cart lives in localStorage (a per-browser convenience). Prices shown here
 * are informational; the server re-prices every item at checkout. */
export type CartItem = {
  price_listing_id: string;
  asset_id: string;
  title: string;
  thumbnail_url: string | null;
  license_name: string;
  size_tier: string;
  price_cents: number;
  currency: string;
  licensee_name?: string;
};

const KEY = "cart.v1";
const EVENT = "cart-changed";

function read(): CartItem[] {
  try {
    return JSON.parse(localStorage.getItem(KEY) ?? "[]");
  } catch {
    return [];
  }
}

function write(items: CartItem[]) {
  try {
    localStorage.setItem(KEY, JSON.stringify(items));
  } catch {}
  window.dispatchEvent(new Event(EVENT));
}

export function useCart() {
  const [items, setItems] = useState<CartItem[]>([]);
  useEffect(() => {
    const sync = () => setItems(read());
    sync();
    window.addEventListener(EVENT, sync);
    window.addEventListener("storage", sync);
    return () => {
      window.removeEventListener(EVENT, sync);
      window.removeEventListener("storage", sync);
    };
  }, []);
  const add = useCallback((item: CartItem) => {
    const current = read().filter((i) => i.price_listing_id !== item.price_listing_id && i.asset_id !== item.asset_id);
    write([...current, item]);
  }, []);
  const remove = useCallback((id: string) => write(read().filter((i) => i.price_listing_id !== id)), []);
  const update = useCallback((id: string, patch: Partial<CartItem>) =>
    write(read().map((i) => (i.price_listing_id === id ? { ...i, ...patch } : i))), []);
  const clear = useCallback(() => write([]), []);
  /** Remove the items a paid order covered (one order per currency). */
  const removeListings = useCallback((ids: string[]) => write(read().filter((i) => !ids.includes(i.price_listing_id))), []);
  return { items, add, remove, update, clear, removeListings };
}

/** Remember a ?ref= referral code seen on any page until registration. */
export function rememberReferral() {
  try {
    const ref = new URLSearchParams(window.location.search).get("ref");
    if (ref) localStorage.setItem("referral.code", ref);
  } catch {}
}

export function storedReferral(): string | null {
  try {
    return localStorage.getItem("referral.code");
  } catch {
    return null;
  }
}
