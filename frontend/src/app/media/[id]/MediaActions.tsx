"use client";

import Link from "next/link";
import { useState } from "react";
import { Alert } from "@/components/Alert";
import { api, label, money } from "@/lib/api";
import { useSession } from "@/lib/session";
import type { MediaDetail } from "@/lib/types";

type Download = { certificate_number: string; download_url: string };

export function MediaActions({ media }: { media: MediaDetail }) {
  const { user } = useSession();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [download, setDownload] = useState<Download | null>(null);
  const [saved, setSaved] = useState(false);

  const getFree = async (code: string) => {
    setBusy(true);
    setError("");
    try {
      const d = await api<Download>(`/media/${media.id}/free-license`, { method: "POST", json: { license_code: code } });
      setDownload(d);
      window.location.href = d.download_url;
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const save = async () => {
    try {
      await api(`/favorites/${media.id}`, { method: "PUT" });
      setSaved(true);
    } catch (e) {
      setError((e as Error).message);
    }
  };

  return (
    <aside className="space-y-4" aria-label="License options">
      {media.free_license_codes.length > 0 && (
        <div className="card p-6">
          <h2 className="font-display text-xl">Free download</h2>
          <p className="mt-1 text-sm text-ink-300">The creator offers this media free. You still receive a license certificate.</p>
          {user ? (
            media.free_license_codes.map((code) => (
              <button key={code} disabled={busy} onClick={() => getFree(code)} className="btn-gold mt-4 w-full">
                {busy ? "Preparing…" : `Download · ${label(code.replace("free_", ""))}`}
              </button>
            ))
          ) : (
            <Link href={`/login?next=/media/${media.id}`} className="btn-gold mt-4 w-full">Sign in to download</Link>
          )}
          <Link href="/legal/licenses" className="mt-3 block text-xs text-ink-400 underline">Read the license terms</Link>
        </div>
      )}

      {media.prices.length > 0 && (
        <div className="card p-6">
          <h2 className="font-display text-xl">License options</h2>
          <ul className="mt-4 divide-y divide-ink-700 text-sm">
            {media.prices.map((p) => (
              <li key={p.id} className="flex items-center justify-between py-3">
                <span>{p.license_name}<span className="block text-xs text-ink-400">{label(p.size_tier)}</span></span>
                <span className="font-semibold text-gold-300">{money(p.price_cents, p.currency)}</span>
              </li>
            ))}
          </ul>
          <button disabled className="btn-gold mt-4 w-full" aria-describedby="checkout-note">License &amp; download</button>
          <p id="checkout-note" className="mt-2 text-xs text-ink-400">
            Paid checkout opens in the next release. Prices are set by the creator.
          </p>
        </div>
      )}

      {error && <Alert>{error}</Alert>}
      {download && (
        <Alert kind="success">
          Download started. License certificate <Link className="underline" href={`/licenses/verify/${download.certificate_number}`}>{download.certificate_number}</Link>.
        </Alert>
      )}

      <div className="flex gap-2">
        {user && <button className="btn-ghost flex-1 text-sm" onClick={save} disabled={saved}>{saved ? "Saved ✓" : "Save to favorites"}</button>}
        <Link className="btn-ghost flex-1 text-sm" href={`/legal/copyright?asset=${media.id}`}>Report</Link>
      </div>
      <p className="text-xs text-ink-400">{media.view_count} views · {media.download_count} downloads</p>
    </aside>
  );
}
