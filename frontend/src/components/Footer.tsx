import Link from "next/link";
import { brand } from "@/config/brand";

const COLUMNS = [
  {
    title: "Marketplace",
    links: [
      ["Stock photos", "/search?type=photo"],
      ["Stock video", "/search?type=video"],
      ["Free media", "/search?free=true"],
      ["Hire creators", "/creators"],
      ["Emerging talent", "/creators?emerging=true"],
    ],
  },
  {
    title: "Creators",
    links: [
      ["Start selling", "/register?sell=1"],
      ["How earnings work", "/#earnings"],
      ["University partners", "/#universities"],
      ["Creator dashboard", "/dashboard"],
    ],
  },
  {
    title: "Legal",
    links: [
      ["Terms of Service", "/legal/terms"],
      ["Privacy Policy", "/legal/privacy"],
      ["License agreements", "/legal/licenses"],
      ["Copyright & DMCA", "/legal/copyright"],
      ["Verify a license", "/licenses/verify"],
    ],
  },
];

export function Footer() {
  return (
    <footer className="mt-24 border-t border-ink-800 bg-ink-950">
      <div className="mx-auto grid max-w-7xl gap-10 px-4 py-14 md:grid-cols-4">
        <div>
          <p className="font-display text-2xl">{brand.name}</p>
          <p className="mt-3 text-sm text-ink-300">{brand.tagline}</p>
          <p className="mt-4 text-sm text-ink-300">
            Support: <a className="underline hover:text-gold-300" href={`mailto:${brand.supportEmail}`}>{brand.supportEmail}</a>
          </p>
        </div>
        {COLUMNS.map((col) => (
          <nav key={col.title} aria-label={col.title}>
            <h2 className="text-sm font-semibold uppercase tracking-wider text-gold-400">{col.title}</h2>
            <ul className="mt-4 space-y-2 text-sm text-ink-200">
              {col.links.map(([label, href]) => (
                <li key={href}><Link className="hover:text-gold-300" href={href}>{label}</Link></li>
              ))}
            </ul>
          </nav>
        ))}
      </div>
      <div className="border-t border-ink-800">
        <div className="mx-auto flex max-w-7xl flex-col gap-2 px-4 py-6 text-xs text-ink-400 sm:flex-row sm:justify-between">
          <p>© {new Date().getFullYear()} {brand.name}. An independent marketplace of {brand.parentCompany}.</p>
          <p>Powered by {brand.poweredBy}.</p>
        </div>
      </div>
    </footer>
  );
}
