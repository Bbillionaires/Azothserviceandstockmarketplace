import Link from "next/link";
import { Fragment } from "react";
import { redirect } from "next/navigation";
import { brand } from "@/config/brand";
import { label, money, tryApi } from "@/lib/api";
import type { RightsGrant } from "@/lib/types";

export const dynamic = "force-dynamic";
export const metadata = { title: "License certificate" };

export default async function Certificate({ params, searchParams }: {
  params: Promise<{ cert: string }>;
  searchParams: Promise<{ cert?: string }>;
}) {
  const { cert } = await params;
  const sp = await searchParams;
  if (cert === "lookup" && sp.cert) redirect(`/licenses/verify/${encodeURIComponent(sp.cert.trim().toUpperCase())}`);
  const g = await tryApi<RightsGrant | null>(`/licenses/verify/${encodeURIComponent(cert)}`, null);

  if (!g) {
    return (
      <div className="mx-auto max-w-xl px-4 py-16 text-center">
        <h1 className="font-display text-3xl">Certificate not found</h1>
        <p className="mt-2 text-ink-300">No license matches “{cert}”. Check the number and try again.</p>
        <Link href="/licenses/verify" className="btn-ghost mt-6">Try another</Link>
      </div>
    );
  }

  const rows: [string, string][] = [
    ["Certificate", g.certificate_number],
    ["Status", label(g.status)],
    ["Media", g.asset_title],
    ["Creator", g.creator_display_name],
    ["Licensee", g.licensee_name],
    ["License", `${g.license_name} (terms ${g.terms_version})`],
    ["Exclusive", g.is_exclusive ? "Yes" : "No"],
    ["Territory", g.territory.join(", ")],
    ["Permitted uses", g.permitted_uses.map(label).join(", ")],
    ["Effective", new Date(g.starts_at).toLocaleDateString()],
    ["Expires", g.ends_at ? new Date(g.ends_at).toLocaleDateString() : "Perpetual"],
    ["Fee", g.price_cents ? money(g.price_cents, g.currency) : "Free"],
    ["Attribution required", g.requires_attribution ? `Yes — credit “${g.creator_display_name}”` : "No"],
  ];

  return (
    <div className="mx-auto max-w-2xl px-4 py-16">
      <div className="card p-8 print:border-black print:bg-white print:text-black">
        <p className="text-xs uppercase tracking-[0.25em] text-gold-400">{brand.name} · License certificate</p>
        <h1 className="font-display mt-2 text-3xl">{g.asset_title}</h1>
        <dl className="mt-6 grid grid-cols-[160px_1fr] gap-y-2 text-sm">
          {rows.map(([k, v]) => (<Fragment key={k}><dt className="text-ink-400">{k}</dt><dd>{v}</dd></Fragment>))}
        </dl>
        <p className="mt-6 text-xs text-ink-400">
          This certificate records the license issued through the marketplace. The governing terms are the license version
          named above. Issued {new Date(g.issued_at).toLocaleString()}.
        </p>
      </div>
      <p className="mt-4 text-center text-xs text-ink-400">Use your browser&apos;s print function to save a PDF copy.</p>
    </div>
  );
}
