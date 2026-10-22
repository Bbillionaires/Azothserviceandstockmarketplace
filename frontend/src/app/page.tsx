import Link from "next/link";
import { CreatorCard } from "@/components/CreatorCard";
import { MediaGrid } from "@/components/MediaGrid";
import { SearchBar } from "@/components/SearchBar";
import { Section } from "@/components/Section";
import { brand } from "@/config/brand";
import { tryApi } from "@/lib/api";
import type { Creator, MediaCard, Page } from "@/lib/types";

export const revalidate = 60;

const CATEGORIES = [
  ["Aerial & drone", "aerial_drone"],
  ["Business", "business_finance"],
  ["Technology", "technology"],
  ["Travel", "travel"],
  ["Food", "food"],
  ["Real estate", "real_estate"],
  ["Nature", "nature_wildlife"],
  ["Sports", "sports"],
];

export default async function Home() {
  const [trending, photos, videos, free, featuredCreators, emerging] = await Promise.all([
    tryApi<MediaCard[]>("/media/featured?limit=8", []),
    tryApi<MediaCard[]>("/media/featured?media_type=photo&limit=6", []),
    tryApi<MediaCard[]>("/media/featured?media_type=video&limit=6", []),
    tryApi<MediaCard[]>("/media/featured?free=true&limit=4", []),
    tryApi<Page<Creator>>("/creators?featured=true&page_size=3", { items: [], total: 0, page: 1, page_size: 3 }),
    tryApi<Page<Creator>>("/creators?emerging=true&page_size=3", { items: [], total: 0, page: 1, page_size: 3 }),
  ]);
  const heroImages = trending.slice(0, 3);

  return (
    <>
      {/* 1-2. Cinematic hero + search */}
      <section aria-labelledby="hero-title" className="relative isolate overflow-hidden">
        <div className="absolute inset-0 -z-10">
          {brand.heroVideoUrl ? (
            <video
              className="h-full w-full object-cover opacity-50 motion-reduce:hidden"
              src={brand.heroVideoUrl}
              autoPlay muted loop playsInline aria-hidden
            />
          ) : (
            <div className="hero-drift grid h-full w-full grid-cols-3 opacity-40">
              {heroImages.map((m) => (
                // eslint-disable-next-line @next/next/no-img-element
                <img key={m.id} src={m.preview_url ?? m.thumbnail_url ?? ""} alt="" className="h-full w-full object-cover" />
              ))}
            </div>
          )}
          <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_top,rgba(200,161,90,0.18),transparent_60%)]" />
          <div className="absolute inset-0 bg-gradient-to-b from-ink-950/40 via-ink-950/70 to-ink-950" />
        </div>
        <div className="mx-auto flex min-h-[78vh] max-w-5xl flex-col items-center justify-center px-4 py-24 text-center">
          <p className="fade-up text-xs font-semibold uppercase tracking-[0.3em] text-gold-400">
            Photography · Footage · Production talent
          </p>
          <h1 id="hero-title" className="fade-up font-display mt-5 text-4xl leading-tight sm:text-6xl">
            License the shot. <span className="text-gold-400">Hire the crew.</span>
            <br className="hidden sm:block" /> Own the story.
          </h1>
          <p className="fade-up mt-6 max-w-2xl text-lg text-ink-200">{brand.tagline}</p>
          <div className="fade-up mt-10 w-full max-w-3xl"><SearchBar large /></div>
          <ul className="mt-6 flex flex-wrap justify-center gap-2 text-sm" aria-label="Popular categories">
            {CATEGORIES.map(([name, slug]) => (
              <li key={slug}>
                <Link href={`/search?category=${slug}`} className="rounded-full border border-ink-600 bg-ink-900/60 px-3 py-1 text-ink-200 hover:border-gold-500 hover:text-gold-300">
                  {name}
                </Link>
              </li>
            ))}
          </ul>
        </div>
      </section>

      {/* 3-6. Entry points */}
      <section aria-label="Ways to use the marketplace" className="mx-auto grid max-w-7xl gap-4 px-4 sm:grid-cols-2 lg:grid-cols-4">
        {[
          ["Stock photography", "Commercial, editorial and product imagery with clear licenses.", "/search?type=photo", "Browse photos"],
          ["Stock video", "HD, 4K and 8K footage, aerials and B-roll with watermarked previews.", "/search?type=video", "Browse footage"],
          ["Hire creators", "Photographers, videographers, drone operators and studios near you or remote.", "/creators", "Find a creator"],
          ["Request This Shot", "Need footage that doesn't exist yet? Post a brief and let creators bid.", "/request-this-shot", "Learn more"],
        ].map(([title, body, href, cta]) => (
          <Link key={href} href={href} className="card group p-6 transition hover:border-gold-600">
            <h2 className="font-display text-xl group-hover:text-gold-300">{title}</h2>
            <p className="mt-2 text-sm text-ink-300">{body}</p>
            <p className="mt-5 text-sm font-medium text-gold-400">{cta} →</p>
          </Link>
        ))}
      </section>

      {/* 8. Trending */}
      <Section id="trending" eyebrow="Trending now" title="Most-licensed this week" action={{ href: "/search?sort=popular", label: "See all" }}>
        <MediaGrid items={trending} empty="New media is being reviewed. Check back soon." />
      </Section>

      {/* 3-4. Photo / video rails */}
      <Section id="photos" eyebrow="Stock photography" title="Images that carry the brief" action={{ href: "/search?type=photo", label: "All photos" }}>
        <MediaGrid items={photos} />
      </Section>
      <Section id="video" eyebrow="Stock video" title="Footage from HD to 8K" action={{ href: "/search?type=video", label: "All footage" }}>
        <MediaGrid items={videos} empty="Video catalog opening soon. Creators can upload MP4 and MOV today." />
      </Section>

      {/* 7. Featured creators */}
      <Section id="creators" eyebrow="Featured creators" title="Storefronts worth following" action={{ href: "/creators", label: "Discover creators" }}>
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {featuredCreators.items.map((c) => <CreatorCard key={c.id} c={c} />)}
        </div>
      </Section>

      {/* 9. Free media */}
      <Section id="free" eyebrow="Free media" title="Free to use, clearly licensed" intro="Creators choose to share these for free. Free is not public domain: each download comes with a license certificate stating exactly what you may do." action={{ href: "/search?free=true", label: "Browse free media" }}>
        <MediaGrid items={free} />
      </Section>

      {/* 10. Exclusive licensing */}
      <Section id="exclusive" eyebrow="Exclusive licensing" title="When the shot has to be yours alone">
        <div className="card grid gap-6 p-8 md:grid-cols-3">
          {[
            ["Defined rights", "Territory, use, duration and sublicensing are written into every exclusive agreement."],
            ["Conflict checks", "Our rights-availability engine blocks a grant that overlaps an existing exclusive license."],
            ["Signed records", "Exclusive deals are executed by electronic signature, with a verifiable license certificate."],
          ].map(([t, b]) => (
            <div key={t}>
              <h3 className="font-display text-lg text-gold-300">{t}</h3>
              <p className="mt-2 text-sm text-ink-300">{b}</p>
            </div>
          ))}
          <p className="text-xs text-ink-400 md:col-span-3">Exclusive licensing opens after agreements complete legal review.</p>
        </div>
      </Section>

      {/* 11. Emerging talent */}
      <Section id="emerging" eyebrow="Hire emerging talent" title="Affordable, ambitious, ready to shoot" intro="Students, recent graduates and new creators building their portfolios." action={{ href: "/creators?emerging=true", label: "Meet emerging talent" }}>
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {emerging.items.map((c) => <CreatorCard key={c.id} c={c} />)}
        </div>
      </Section>

      {/* 12. Universities */}
      <Section id="universities" eyebrow="University & production clubs" title="Built with film schools and creative clubs">
        <div className="card grid gap-8 p-8 md:grid-cols-2">
          <p className="text-ink-200">
            Film departments, photography programs and production clubs will be able to run group storefronts, showcase
            student portfolios and route paid production opportunities to members. Members always keep ownership of
            their own work; any organization commission requires the member&apos;s separate authorization.
          </p>
          <div className="flex flex-col justify-center gap-3">
            <a className="btn-gold" href={`mailto:${brand.supportEmail}?subject=University%20partnership`}>Become a launch partner</a>
            <p className="text-xs text-ink-400">Partnership tools arrive in Phase 4 of the roadmap.</p>
          </div>
        </div>
      </Section>

      {/* 13. Earnings */}
      <Section id="earnings" eyebrow="Creator earnings" title="Transparent, auditable royalties" intro="Every sale is split by a versioned rule you can see in your contract, and every cent is traceable in your statement.">
        <div className="grid gap-4 lg:grid-cols-3">
          <div className="card p-6">
            <p className="text-sm text-ink-300">Nonexclusive license (example)</p>
            <p className="font-display mt-1 text-3xl">$100.00</p>
            <dl className="mt-5 space-y-2 text-sm">
              <div className="flex justify-between"><dt className="text-ink-300">You (creator)</dt><dd className="text-gold-300">$50.00</dd></div>
              <div className="flex justify-between"><dt className="text-ink-300">Platform</dt><dd>$50.00</dd></div>
              <div className="flex justify-between text-xs"><dt className="text-ink-400">↳ referral partner (from platform share)</dt><dd className="text-ink-400">$5.00</dd></div>
            </dl>
          </div>
          <div className="card p-6">
            <p className="text-sm text-ink-300">Exclusive license, first sale (example)</p>
            <p className="font-display mt-1 text-3xl">$1,000.00</p>
            <dl className="mt-5 space-y-2 text-sm">
              <div className="flex justify-between"><dt className="text-ink-300">You (creator)</dt><dd className="text-gold-300">$650.00</dd></div>
              <div className="flex justify-between"><dt className="text-ink-300">Platform</dt><dd>$350.00</dd></div>
            </dl>
          </div>
          <div className="card p-6">
            <p className="text-sm text-ink-300">Collaboration split (example)</p>
            <p className="font-display mt-1 text-3xl">$50.00 pool</p>
            <dl className="mt-5 space-y-2 text-sm">
              <div className="flex justify-between"><dt className="text-ink-300">Videographer · 50%</dt><dd>$25.00</dd></div>
              <div className="flex justify-between"><dt className="text-ink-300">Editor · 30%</dt><dd>$15.00</dd></div>
              <div className="flex justify-between"><dt className="text-ink-300">Drone operator · 20%</dt><dd>$10.00</dd></div>
            </dl>
          </div>
        </div>
        <p className="mt-4 text-xs text-ink-400">
          Examples use net licensing revenue after taxes and payment-processing fees. Proposed terms, subject to the final
          signed agreement. Creators keep copyright. No guaranteed sales, rankings or income.
        </p>
      </Section>

      {/* 14. Testimonials */}
      <Section id="stories" eyebrow="Customer & creator stories" title="Stories from our first customers">
        <div className="card p-8 text-ink-300">
          We publish only real, attributed testimonials. Our first customer and creator stories will appear here after launch.
        </div>
      </Section>

      {/* 15. Registration */}
      <section aria-labelledby="join-title" className="mx-auto max-w-7xl px-4 py-16">
        <div className="relative overflow-hidden rounded-3xl border border-gold-600/40 bg-gradient-to-br from-ink-800 via-ink-900 to-ink-950 p-10 text-center sm:p-16">
          <h2 id="join-title" className="font-display text-3xl sm:text-5xl">Your work, licensed on your terms.</h2>
          <p className="mx-auto mt-4 max-w-2xl text-ink-200">
            Open a free storefront, set your own prices and keep your copyright. Premium tools will be optional; basic
            selling never requires a subscription.
          </p>
          <div className="mt-8 flex flex-wrap justify-center gap-3">
            <Link href="/register?sell=1" className="btn-gold">Become a creator</Link>
            <Link href="/register" className="btn-ghost">Create a buyer account</Link>
          </div>
        </div>
      </section>
    </>
  );
}
