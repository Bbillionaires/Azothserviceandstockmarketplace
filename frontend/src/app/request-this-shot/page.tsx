import Link from "next/link";
import { brand } from "@/config/brand";

export const metadata = { title: "Request This Shot" };

export default function RequestThisShot() {
  return (
    <div className="mx-auto max-w-4xl px-4 py-16">
      <p className="text-xs uppercase tracking-[0.25em] text-gold-400">Coming in Phase 3</p>
      <h1 className="font-display mt-2 text-5xl">Request This Shot</h1>
      <p className="mt-4 text-lg text-ink-200">
        Need drone footage of a specific building, interviews for a documentary, or a restaurant promo that doesn&apos;t
        exist yet? Post a brief with your location, budget and deadline. Local creators bid, you pick, and you decide up
        front whether the result is exclusive to you, nonexclusive, or on custom terms.
      </p>
      <ol className="mt-10 grid gap-4 sm:grid-cols-3">
        {[
          ["1. Describe the shot", "Location, deliverables, deadline, budget and reference files."],
          ["2. Compare offers", "Bids, fixed quotes or direct assignment to a creator you trust."],
          ["3. Approve & license", "Milestone payments through our payment partner and a license certificate."],
        ].map(([t, b]) => (
          <li key={t} className="card p-5"><p className="font-display text-lg text-gold-300">{t}</p><p className="mt-2 text-sm text-ink-300">{b}</p></li>
        ))}
      </ol>
      <div className="mt-10 flex flex-wrap gap-3">
        <Link href="/search" className="btn-gold">Search existing media first</Link>
        <a href={`mailto:${brand.supportEmail}?subject=Request%20This%20Shot%20early%20access`} className="btn-ghost">Ask for early access</a>
      </div>
    </div>
  );
}
