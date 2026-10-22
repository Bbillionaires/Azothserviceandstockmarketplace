# MVP, Roadmap and Schedule

## 1. Smallest commercially useful MVP

**A curated, regional stock-media marketplace that can take money.** That is
Phase 1 (built) plus the core of Phase 2:

1. Creator storefronts, upload, moderation, search, free media with
   certificates (**done**).
2. Paid licenses for standard and extended commercial and editorial use via
   Stripe Checkout and Connect, with protected downloads and certificates.
3. Model A royalties written to the ledger, creator earnings dashboard,
   monthly statement, Stripe Express payouts.
4. Basic referral links (creator recruitment only).

This is enough to sign up local creators (university film programs, drone
operators, real-estate photographers), sell licenses to local businesses and
agencies, and prove the core metrics: paying customers, GMV and creator
earnings. Custom production, exclusives, subscriptions and the Production
Exchange come after there is real demand data.

## 2. Phase 1 status (this delivery)

| Feature | Status | Notes |
|---|---|---|
| Homepage (all 16 sections) | ✅ | Hero video via env var; still collage fallback. The testimonials section shows no invented quotes |
| Authentication | ✅ | Email verification, reset, TOTP MFA, multi-role, logout-all |
| Customer accounts | ✅ | Favorites, collections, license history, re-download |
| Creator accounts and storefronts | ✅ | Public storefront, discovery filters, follow, emerging talent |
| Media uploads | ✅ | JPEG/PNG/TIFF/WebP and MP4/MOV; watermarked previews; FFmpeg video previews |
| Free media listings | ✅ | Creator-authorized free licenses with certificates and signed downloads |
| Search | ✅ | Filters, facets, Postgres FTS, natural-language filter extraction |
| Media detail pages | ✅ | Specs, disclosures, license options |
| Basic licensing records | ✅ | Versioned agreements, rights grants, public certificate verification |
| Administrator moderation | ✅ | Queue with advisory signals, appeals, DMCA workflow, roles, commission versions, audit |
| Responsive design | ✅ | Tested at 390 px and 1440 px; reduced-motion respected |
| Organizations | ◐ | Schema only; UI in Phase 4 |
| Paid checkout | ✗ | Phase 2 (prices can already be set and displayed) |

**Known limitations before production:**

* Media processing runs in-process (FastAPI background task). Move it to a
  Redis-backed worker before heavy video volume.
* Uploads pass through the API. Add presigned multipart direct-to-R2 uploads
  for large video.
* The rate limiter is per-instance memory. Use Redis when running more than
  one API replica.
* Email uses a console backend in development. Configure SMTP or a provider
  adapter.
* No CAPTCHA on registration or complaint forms yet.
* Agreement and legal texts are placeholders and must be replaced after legal
  review.

## 3. Phased schedule

Estimates assume one senior full-stack developer with AI assistance and part-time
design and QA. Calendar weeks, not effort.

| Phase | Scope | Duration | Cumulative |
|---|---|---|---|
| **1. Foundation** | Built in this delivery | (done) | — |
| 1.5 Hardening | Worker queue, direct uploads, Redis rate limits, email provider, Sentry, backups, WCAG audit, staging environment, legal texts | 2–3 weeks | 3 weeks |
| **2. Monetization** | Orders, Stripe Checkout and Connect Express, webhooks, ledger, royalty allocation, payouts, refunds, statements, earnings dashboard, reconciliation job, basic referrals | 5–7 weeks | ~10 weeks |
| **3. Custom production** | Project briefs, Request This Shot, proposals, booking, messaging, milestones, deliverables, reviews, disputes, client galleries, creator matching (rules-based) | 8–10 weeks | ~20 weeks |
| Addendum: immediate | Talent availability, Urgent Crew, vendor profiles, production bid requests | 4–6 weeks | ~26 weeks |
| **4. Partnerships and advanced licensing** | University and club programs, collaborations, exclusive deals and e-signature, rights carve-outs, syndication | 6–8 weeks | ~34 weeks |
| Addendum: second release | Production packages, rebooking, staffing dashboards, vendor shortlists | 4–5 weeks | ~39 weeks |
| **5. Global scale** | Buyer and creator subscriptions and credits, enterprise accounts, public API, AI tagging, search and matching, analytics, multi-currency | 10–14 weeks | ~53 weeks |
| Addendum: advanced | Resource rentals (after legal), contract workflows, expense management, enterprise BI | 6–8 weeks | ~60 weeks |

Each phase ships behind feature flags, with migrations, tests and a staging
soak before production.

## 4. Features that can wait without harming launch

Buyer and creator subscriptions; enterprise contracts and API; exclusive
licensing (legal gate); syndication; AI tagging, search and pricing
(manual keywords and Postgres FTS are enough at launch); university program
tooling (run partnerships manually with referral codes first); client
galleries; collaborations; print-order integrations; multi-currency and
localization; advanced analytics; resource rentals; contract workflows; expense
management; recurring affiliate commissions.

## 5. Production Exchange addendum: module estimates

Complexity S/M/L/XL. Incremental infrastructure cost is at the 10,000-user
tier. Revenue potential is directional, not a forecast.

| Module | Release | Complexity | Builds on | Incremental infra / ops | Revenue mechanism | Revenue potential |
|---|---|---|---|---|---|---|
| Talent availability | Immediate | M | Profiles, search | ~$0–20/mo (rows + indexes) | Drives bookings; premium visibility later | Indirect; high engagement |
| Urgent Crew | Immediate | M | Availability, notifications | $20–60/mo (email/SMS/push) | Featured urgent posts; booking commission once legal clears | Medium; high demand |
| Vendor directory | Immediate | S–M | Organizations, search | ~$0–20/mo | Paid vendor listings ($19–99/mo), clearly labeled sponsored placement | Medium; recurring |
| Production bid exchange | Immediate | M–L | Phase 3 proposals, private storage | ~$10–30/mo | Commission on awarded production contracts | High per deal |
| Production packages | Second | M | Booking, `split_by_bps`, ledger | ~$0–20/mo | Commission on package bookings | Medium–high |
| Crew rebooking | Second | S | Bookings history | negligible | Higher repeat GMV | Indirect; strong retention |
| Project staffing dashboards | Second | M | Projects, bookings | negligible | Premium production workspace ($49–199/mo) | Medium |
| Vendor shortlists | Second | S | Vendors | negligible | Workspace feature | Low; retention |
| Resource rentals | Advanced (after legal, insurance, deposits) | L | Payments, disputes | $20–100/mo + insurance partner | Rental commission | Medium; higher risk |
| Contract workflows | Advanced | L | E-signature, private storage | E-sign API $50–300/mo | Contract administration add-on | Medium |
| Production expense management | Advanced | L | Ledger, Stripe | ~$20–50/mo | Enterprise workspace | Medium (enterprise) |
| Business lead exchange | Advanced | M | Orgs, moderation | negligible | Lead tools subscription; never sale of contact data | Low–medium |
| Marketplace BI | Advanced | M | Read replica, aggregation | $50–150/mo | Enterprise reporting; internal decisions | Indirect |

**Build order (lowest cost, highest demand first):** vendor directory →
talent availability → Urgent Crew → bid exchange → rebooking → packages →
staffing dashboards → contracts → expenses → rentals.

## 6. Growth plan and KPIs

**Focused geographic launch.** One metro area first (the demo data assumes
Jacksonville / North Florida and Georgia). Seed supply through university film
and photography programs, student production clubs, drone operators and
real-estate photographers. Seed demand through small businesses, marketing
agencies, real-estate brokerages and local media.

**Acquisition tactics.**

* Partnership kit for universities: one-pager, ambassador referral codes,
  student showcase competitions, credit toward portfolios.
* Creator onboarding campaigns: "first 100 approved assets" review fast-lane,
  pricing guidance, release templates.
* Referral program: creator recruitment bonuses and customer acquisition
  commissions paid from the platform share. Fraud checks: self-referral,
  device and payment fingerprint, clawback on refunds. No multi-level
  commissions.
* Buyer-side: local SEO landing pages ("drone footage Jacksonville"), free
  media as top-of-funnel, Request This Shot for unmet demand.
* National expansion city by city once a metro reaches liquidity (for example,
  over 30% of searches returning a licensable result and repeat buyers above 25%).

**Track:** active creators, approved assets, paying customers, GMV, net
platform revenue, creator earnings, repeat-purchase rate, search-to-license
conversion, creator retention (90-day), customer acquisition cost, dispute and
refund rates, subscription retention (Phase 5). Prioritize paying customers and
commercially useful media over raw sign-up counts.
