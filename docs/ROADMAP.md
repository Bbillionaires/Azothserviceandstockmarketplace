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

**Hardening gaps closed** (were listed as known limitations):

* Media, gallery and deliverable processing runs on an RQ worker backed by
  Redis (`rq worker default`), with retries. Without `REDIS_URL` (local
  development) jobs fall back to in-process background tasks.
* Uploads go straight to object storage through presigned PUT URLs (upload
  sessions with size and ownership checks). The API never buffers large video.
  Local storage uses an equivalent same-origin endpoint.
* The rate limiter uses Redis when `REDIS_URL` is set (required in production),
  so limits hold across API replicas.
* Email: console (development), SMTP, or Resend (`EMAIL_BACKEND=resend`).
* Cloudflare Turnstile CAPTCHA on registration, password reset, copyright
  complaints and gallery passwords (enabled when the keys are set).

**Still open:** agreement and legal texts are placeholders and must be
replaced after legal review.

## 2b. Phase 2 status (monetization)

| Feature | Status | Notes |
|---|---|---|
| Paid stock media sales | ✅ | Cart, server-side re-pricing, Stripe Checkout (fake provider for local dev), certificates and protected downloads |
| Marketplace payment integration | ✅ | Stripe Checkout + Connect Express adapter, signed webhooks, idempotent event processing, retry of failed events |
| Creator payout onboarding | ✅ | Hosted Express onboarding, account status sync |
| Royalty calculations | ✅ | Engine output stored per line with rule version; double-entry ledger |
| Licensing certificates | ✅ | Issued on payment; revoked on refund or chargeback, restored if the dispute is won |
| Protected downloads | ✅ | Same signed-link system as free media; blocked after refund |
| Earnings dashboards | ✅ | Pending, available, paid, lifetime; per-sale calculation; payouts; monthly CSV statement |
| Basic affiliate referrals | ✅ | Referral links, attribution window, commission from the platform share, IP-velocity fraud flag, clawback on refund |
| Refunds and chargebacks | ✅ | Full and partial refunds (several per line); refunds issued in the Stripe dashboard (full or partial) booked automatically; disputes created and won |
| Per-line tax | ✅ | Stripe Tax amounts read per line item; proration only as a fallback |
| Provider reconciliation | ✅ | Charges, fees, refunds and transfers compared with Stripe balance activity |
| Creator recruitment bonus | ✅ | One-time platform-funded bonus to the referrer when a referred creator's first earning clears its hold |
| Multi-currency cart and earnings | ✅ | One checkout per currency; earnings dashboard per currency |
| Tax information status | ✅ | Shown from the Connect account's requirements (forms collected by Stripe) |
| Payouts and reconciliation | ✅ | Daily job with hold period, minimum payout, failure handling, advisory lock; reconciliation checks |
| Finance admin console | ✅ | Overview KPIs, orders and refunds, payout run, reconciliation, failed-event retry |

**Not yet verified against live Stripe.** The Stripe adapter is covered by
offline tests (signature verification, request parameters, error handling),
but nobody has run a real test-mode payment end to end yet. Do that in Stripe
test mode before enabling `FEATURE_PAID_LICENSING` in production (see
DEPLOYMENT.md §6).

## 2c. Phase 3 status (custom production)

| Feature | Status | Notes |
|---|---|---|
| Custom project posting | ✅ | Briefs with category, deliverables, location, budget, deadline, rights preference, public or invite-only |
| Request This Shot | ✅ | Shot requests with required rights choice (exclusive / nonexclusive / custom); creator board with location, category, budget and deadline filters |
| Creator matching | ✅ | Rules-based: skills vs. service category, city/country, remote and travel, verification, verified rating and completed projects, emerging talent within budget |
| Proposals | ✅ | Milestone plans, delivery time, revisions, rights terms; confidential per bidder; accept / decline / withdraw; invitations |
| Booking | ✅ | From accepted proposals or fixed-price packages; acceptance evidence and rights snapshot recorded |
| Messaging | ✅ | Per project, per bid and direct-from-storefront conversations; unread counts; notifications |
| Project milestones | ✅ | Fund (Stripe Checkout), deliver private files, submit, revision requests (limited), approve and release, auto-approve, add paid milestones |
| Cancellation handling | ✅ | Unfunded projects cancel freely; funded milestones need a creator refund or a dispute |
| Disputes | ✅ | Either party opens; funds frozen; staff resolve by release, refund or split |
| Refunds after release | ✅ | Finance refunds (full or partial) and Stripe-dashboard refunds; creator, referrer and platform each return their share; paid earnings become clawbacks |
| Card chargebacks on bookings | ✅ | Held and released funds pulled back; restored exactly if the dispute is won |
| Duplicate milestone payments | ✅ | Refunded automatically in full |
| Booking referral commission | ✅ | Client's referrer earns `affiliate_bps_of_platform` of the commission (services_commission v2) |
| Reviews | ✅ | Verified (completed projects only), both directions, shown on storefronts; moderators can hide |
| Client galleries | ✅ | Secret link, optional password, expiry, watermarked proofs, favorites, selections with limit, comments, revision requests, approval, optional original downloads |
| Gallery add-on sales | ✅ | Per-image digital downloads and creator-fulfilled print options; guest checkout; tracking emails; refunds and chargebacks. Print-lab integrations are not included |

Commissioned deliverables are stored privately and there is no code path that
publishes them to the stock catalog.

## 3. Phased schedule

Estimates assume one senior full-stack developer with AI assistance and part-time
design and QA. Calendar weeks, not effort.

| Phase | Scope | Duration | Cumulative |
|---|---|---|---|
| **1. Foundation** | Built in this delivery | (done) | — |
| 1.5 Hardening | Done: worker queue, direct uploads, Redis rate limits, email provider, CAPTCHA. Remaining: Sentry, backups, WCAG audit, staging environment, legal texts | 1–2 weeks | 2 weeks |
| **2. Monetization** | Built (pending live Stripe test-mode verification) | (done) | — |
| **3. Custom production** | Built | (done) | — |
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
tooling (run partnerships manually with referral codes first);
collaborations; print-lab integrations; localization; advanced analytics; resource rentals; contract workflows; expense
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
