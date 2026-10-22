import { notFound } from "next/navigation";
import { Suspense } from "react";
import { brand } from "@/config/brand";
import { tryApi } from "@/lib/api";
import type { LicenseType } from "@/lib/types";
import { ComplaintForm } from "./ComplaintForm";

const DRAFT = "Draft for legal review. This page is a placeholder and is not yet the binding agreement.";

const PAGES: Record<string, { title: string; body: string[] }> = {
  terms: {
    title: "Terms of Service",
    body: [
      `${brand.name} is an independent marketplace operated by ${brand.parentCompany}.`,
      "Creators keep copyright in their work. Uploading media does not transfer ownership to the platform.",
      "Buyers receive only the rights stated in the license certificate issued for each download or purchase.",
      "Custom production rights are negotiated per project; commissioned content is never resold without the commissioning customer's agreement.",
      "Payments are processed by an authorized payment provider. The platform does not provide escrow services.",
    ],
  },
  privacy: {
    title: "Privacy Policy",
    body: [
      "We collect account details, storefront information you choose to publish, uploads, and records needed for licensing, tax and fraud prevention.",
      "Public creator locations are limited to city, region and country. We never publish home addresses.",
      "We do not sell personal contact data.",
    ],
  },
  licenses: { title: "License agreements", body: ["Each license type below summarizes the rights granted. The full terms version is recorded on every certificate."] },
  copyright: {
    title: "Copyright & DMCA policy",
    body: [
      "If you believe media on this marketplace infringes your copyright, submit a notice below. A moderator reviews every notice for completeness before any action; content is not removed automatically.",
      "Creators whose content is disabled may submit a counter-notice from their dashboard. Repeat infringers lose upload privileges.",
    ],
  },
};

export function generateStaticParams() {
  return Object.keys(PAGES).map((slug) => ({ slug }));
}

export default async function LegalPage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  const page = PAGES[slug];
  if (!page) notFound();
  const types = slug === "licenses" ? await tryApi<LicenseType[]>("/license-types", []) : [];

  return (
    <div className="mx-auto max-w-3xl px-4 py-16">
      <h1 className="font-display text-4xl">{page.title}</h1>
      <p className="mt-4 rounded-lg border border-amber-500/30 bg-amber-500/5 p-3 text-sm text-amber-200">{DRAFT}</p>
      <div className="mt-6 space-y-4 text-ink-200">{page.body.map((p) => <p key={p}>{p}</p>)}</div>
      {types.length > 0 && (
        <ul className="mt-8 space-y-3">
          {types.map((t) => (
            <li key={t.code} className="card p-5">
              <p className="font-display text-lg">{t.name}</p>
              <p className="mt-1 text-sm text-ink-300">{t.summary}</p>
              <p className="mt-2 text-xs text-ink-400">Terms version {t.terms_version}{t.requires_attribution ? " · attribution required" : ""}</p>
            </li>
          ))}
        </ul>
      )}
      {slug === "copyright" && <Suspense><ComplaintForm /></Suspense>}
    </div>
  );
}
