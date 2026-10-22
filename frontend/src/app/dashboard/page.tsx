"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { Alert } from "@/components/Alert";
import { api, label, money } from "@/lib/api";
import { useSession } from "@/lib/session";
import type { AgreementTemplate, Creator, MediaDetail, Page, RightsGrant } from "@/lib/types";
import { AgreementsPanel } from "./AgreementsPanel";
import { EarningsPanel } from "./EarningsPanel";
import { OrdersPanel } from "./OrdersPanel";
import { ReferralsPanel } from "./ReferralsPanel";
import { SecurityPanel } from "./SecurityPanel";
import { StorefrontForm } from "./StorefrontForm";

type Tab = "media" | "earnings" | "storefront" | "agreements" | "orders" | "licenses" | "referrals" | "security";

const STATUS_STYLE: Record<string, string> = {
  approved: "text-emerald-300",
  pending_review: "text-gold-300",
  processing: "text-sky-300",
  changes_requested: "text-amber-300",
  rejected: "text-red-300",
  failed: "text-red-300",
  disabled: "text-red-300",
  withdrawn: "text-ink-400",
};

export default function Dashboard() {
  const { user, loading, refresh } = useSession();
  const router = useRouter();
  const [tab, setTab] = useState<Tab>("media");
  const [creator, setCreator] = useState<Creator | null>(null);
  const [media, setMedia] = useState<MediaDetail[]>([]);
  const [templates, setTemplates] = useState<AgreementTemplate[]>([]);
  const [signed, setSigned] = useState<{ template_code: string; status: string }[]>([]);
  const [licenses, setLicenses] = useState<RightsGrant[]>([]);
  const [notice, setNotice] = useState("");

  const load = useCallback(async () => {
    const c = await api<Creator>("/creators/me").catch(() => null);
    setCreator(c);
    setLicenses(await api<RightsGrant[]>("/licenses/mine").catch(() => []));
    if (c) {
      const [m, t, s] = await Promise.all([
        api<Page<MediaDetail>>("/media/mine?page_size=100"),
        api<AgreementTemplate[]>("/agreements/templates"),
        api<{ template_code: string; status: string }[]>("/agreements/mine"),
      ]);
      setMedia(m.items);
      setTemplates(t);
      setSigned(s);
    }
  }, []);

  useEffect(() => {
    const t = new URLSearchParams(window.location.search).get("tab");
    if (t) setTab(t as Tab);
  }, []);

  useEffect(() => {
    if (!loading && !user) router.push("/login?next=/dashboard");
    if (user) load();
  }, [user, loading, router, load]);

  // Poll while uploads are processing.
  useEffect(() => {
    if (!media.some((m) => m.status === "processing")) return;
    const t = setTimeout(load, 3000);
    return () => clearTimeout(t);
  }, [media, load]);

  if (loading || !user) return <p className="p-10 text-center text-ink-300">Loading…</p>;

  const active = new Set(signed.filter((s) => s.status === "active").map((s) => s.template_code));
  const counts = media.reduce<Record<string, number>>((acc, m) => ({ ...acc, [m.status]: (acc[m.status] ?? 0) + 1 }), {});
  const tabs: [Tab, string][] = creator
    ? [["media", "My media"], ["earnings", "Earnings"], ["storefront", "Storefront"], ["agreements", "Agreements"],
       ["orders", "Purchases"], ["licenses", "My licenses"], ["referrals", "Referrals"], ["security", "Security"]]
    : [["storefront", "Open a storefront"], ["orders", "Purchases"], ["licenses", "My licenses"],
       ...(user.roles.includes("affiliate") ? [["earnings", "Earnings"] as [Tab, string]] : []),
       ["referrals", "Referrals"], ["security", "Security"]];
  const current = tabs.some(([t]) => t === tab) ? tab : tabs[0][0];

  return (
    <div className="mx-auto max-w-7xl px-4 py-10">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 className="font-display text-4xl">Dashboard</h1>
          <p className="text-ink-300">{user.display_name} · {user.roles.map(label).join(", ")}</p>
        </div>
        {creator && <Link href="/dashboard/upload" className="btn-gold">Upload media</Link>}
      </div>

      {!user.email_verified && (
        <div className="mt-6">
          <Alert kind="info">
            Verify your email to open a storefront and upload. Check your inbox.{" "}
            <button className="underline" onClick={async () => setNotice((await api<{ detail: string }>("/auth/resend-verification", { method: "POST" }).catch((e) => ({ detail: e.message }))).detail)}>
              Resend email
            </button>
          </Alert>
        </div>
      )}
      {notice && <div className="mt-3"><Alert kind="info">{notice}</Alert></div>}

      {creator && (
        <dl className="mt-8 grid grid-cols-2 gap-4 sm:grid-cols-4">
          {[
            ["Published", counts.approved ?? 0],
            ["In review", (counts.pending_review ?? 0) + (counts.processing ?? 0)],
            ["Needs attention", (counts.changes_requested ?? 0) + (counts.rejected ?? 0) + (counts.failed ?? 0)],
            ["Downloads", media.reduce((a, m) => a + m.download_count, 0)],
          ].map(([k, v]) => (
            <div key={k} className="card p-5"><dt className="text-sm text-ink-400">{k}</dt><dd className="font-display mt-1 text-3xl">{v}</dd></div>
          ))}
        </dl>
      )}
      {creator && (
        <p className="mt-3 text-xs text-ink-400">Earnings balances are calculated by the server ledger; see the Earnings tab for statements and payouts.</p>
      )}

      <div role="tablist" aria-label="Dashboard sections" className="mt-10 flex flex-wrap gap-2 border-b border-ink-800">
        {tabs.map(([t, l]) => (
          <button key={t} role="tab" aria-selected={current === t} onClick={() => setTab(t)}
            className={`-mb-px border-b-2 px-4 py-2 text-sm ${current === t ? "border-gold-500 text-gold-300" : "border-transparent text-ink-300 hover:text-white"}`}>
            {l}
          </button>
        ))}
      </div>

      <div className="mt-8" role="tabpanel">
        {current === "media" && creator && (
          media.length === 0 ? (
            <div className="card p-10 text-center text-ink-300">
              {active.size === 0 ? "Accept a contributor agreement in the Agreements tab, then upload your first file." : "No uploads yet."}
              <div className="mt-4"><Link href="/dashboard/upload" className="btn-gold">Upload media</Link></div>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-left text-sm">
                <thead className="text-ink-400"><tr><th className="p-2">Media</th><th className="p-2">Status</th><th className="p-2">Pricing</th><th className="p-2">Views</th><th className="p-2">Downloads</th><th className="p-2"><span className="sr-only">Actions</span></th></tr></thead>
                <tbody>
                  {media.map((m) => (
                    <tr key={m.id} className="border-t border-ink-800">
                      <td className="flex items-center gap-3 p-2">
                        {m.thumbnail_url
                          // eslint-disable-next-line @next/next/no-img-element
                          ? <img src={m.thumbnail_url} alt="" className="h-12 w-16 rounded object-cover" />
                          : <span className="h-12 w-16 rounded bg-ink-800" />}
                        <span>{m.title}<span className="block text-xs text-ink-400">{label(m.media_type)} · {m.resolution_label ?? "—"}</span></span>
                      </td>
                      <td className={`p-2 ${STATUS_STYLE[m.status] ?? ""}`}>
                        {label(m.status)}
                        {(m.rejection_reason || m.processing_error) && <span className="block max-w-xs text-xs text-ink-300">{m.rejection_reason || m.processing_error}</span>}
                      </td>
                      <td className="p-2 text-ink-200">
                        {m.free_license_codes.length ? "Free" : ""}{m.free_license_codes.length && m.prices.length ? " + " : ""}
                        {m.prices.length ? `from ${money(Math.min(...m.prices.map((p) => p.price_cents)), m.prices[0].currency)}` : m.free_license_codes.length ? "" : <span className="text-amber-300">Not priced</span>}
                      </td>
                      <td className="p-2">{m.view_count}</td>
                      <td className="p-2">{m.download_count}</td>
                      <td className="p-2"><Link href={`/dashboard/media/${m.id}`} className="text-gold-300 hover:underline">Manage</Link></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )
        )}
        {current === "storefront" && (
          <StorefrontForm creator={creator} defaultName={user.display_name} disabled={!user.email_verified} onSaved={async (c) => { setCreator(c); await refresh(); await load(); }} />
        )}
        {current === "agreements" && creator && <AgreementsPanel templates={templates} active={active} onSigned={load} />}
        {current === "licenses" && (
          licenses.length === 0 ? <div className="card p-10 text-center text-ink-300">Licenses you obtain appear here with their certificates.</div> : (
            <ul className="space-y-3">
              {licenses.map((l) => (
                <li key={l.certificate_number} className="card flex flex-col gap-2 p-4 sm:flex-row sm:items-center sm:justify-between">
                  <div>
                    <p className="font-medium">{l.asset_title}</p>
                    <p className="text-xs text-ink-400">{l.license_name} · {l.certificate_number} · {new Date(l.issued_at).toLocaleDateString()} · {label(l.status)}</p>
                  </div>
                  <div className="flex gap-2">
                    <Link className="btn-ghost text-sm" href={`/licenses/verify/${l.certificate_number}`}>Certificate</Link>
                    <button className="btn-gold text-sm" onClick={async () => {
                      const d = await api<{ download_url: string }>(`/licenses/${l.certificate_number}/download`, { method: "POST" });
                      window.location.href = d.download_url;
                    }}>Download</button>
                  </div>
                </li>
              ))}
            </ul>
          )
        )}
        {current === "security" && <SecurityPanel />}
        {current === "earnings" && <EarningsPanel />}
        {current === "orders" && <OrdersPanel />}
        {current === "referrals" && <ReferralsPanel verified={user.email_verified} />}
      </div>
    </div>
  );
}
