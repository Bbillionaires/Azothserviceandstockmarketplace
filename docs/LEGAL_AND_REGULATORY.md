# Legal and Regulatory Dependencies

This is an engineering checklist of the legal work the platform depends on. It
is not legal advice. Items marked **Blocker** must be resolved before the
related feature is switched on in production. The code enforces several of
these gates: unapproved agreement versions cannot be signed in production,
exclusive licensing and paid licensing are behind feature flags, and demo data
refuses to load in production.

## Entity and brand

| Item | Why | Gate |
|---|---|---|
| Final legal structure of the marketplace under One United Enterprise LLC (DBA vs. subsidiary) | Contracting party on every agreement, Stripe account holder, tax filings | **Blocker** for launch |
| Trademark clearance and registration for the final marketplace name | The placeholder "Lumen & Reel" is not cleared | **Blocker** for public launch |
| Business licenses and sales-tax registrations in launch states | Selling digital licenses is taxable in many US states and abroad | **Blocker** for paid licensing |

## Platform terms and policies

| Document | Notes | Gate |
|---|---|---|
| Terms of Service (buyers and creators) | Marketplace role, limitations of liability, dispute resolution, governing law | **Blocker** for launch |
| Privacy Policy plus data-processing terms | GDPR/UK GDPR, CCPA/CPRA, other US state laws; cookie disclosures; data subject rights; retention schedule | **Blocker** for launch |
| Acceptable Use and Content Policy | Prohibited content, AI-content disclosure, minors, sensitive and editorial content | **Blocker** for launch |
| Copyright / DMCA policy | Designated agent registered with the US Copyright Office, notice and counter-notice procedures (implemented), repeat-infringer policy | **Blocker**: register the agent before accepting uploads |
| Contributor agreements: Model A, Model C | Replace the seeded DRAFT texts; mark versions `approved` via the admin API with the reviewer's name | **Blocker** for production uploads |
| Exclusive licensing agreement: Model B | Territory, uses, duration, sublicensing, carve-outs, minimum guarantees, continuing royalties, statutory termination acknowledgement; e-signature provider | **Blocker** for exclusive licensing |
| Buyer license agreements (personal, editorial, standard and extended commercial, free variants) | Precise permitted uses, reproduction limits, prohibited uses, indemnities, attribution wording | **Blocker** for paid licensing (free variants before launch) |
| Model and property release templates | Jurisdiction-specific; minors | Before commercial licensing of identifiable people or property |
| Collaboration and organization commission authorizations | Co-creator splits; university/club commissions need each member's separate consent | Phase 4 |
| Custom production terms | Commissioned-work ownership, work-for-hire where lawful, cancellations, revisions, rights negotiated per project | Phase 3 |
| Affiliate program terms | Commission terms, FTC endorsement disclosures, anti-fraud; no multi-level commissions | Phase 2 affiliates |
| Creator and buyer subscription terms | Auto-renewal laws (e.g. California), cancellation flows, credit expiry and breakage disclosure | Phase 5 |

## Payments and finance

| Item | Notes |
|---|---|
| Stripe Connect platform agreement and approved business model | Confirm the marketplace model, separate charges and transfers, and the maximum hold periods for refund windows and milestone payments |
| Money transmission and escrow | Use only the provider's licensed flows; never describe milestone holds as "escrow" unless a licensed escrow partner is engaged |
| Sales tax, VAT and digital-services taxes | Stripe Tax or equivalent; marketplace facilitator rules by state; EU VAT OSS for EU buyers |
| Information reporting | 1099-K via Stripe; possible 1099-NEC for affiliates; EU DAC7 if EU sellers; backup withholding via W-9/W-8 |
| Unclaimed property | Unpaid creator balances may escheat; define a dormancy policy |
| Financial record retention | Ledger and audit records kept for at least 7 years |

## Content and data protection

* Copyright Office DMCA agent designation (renew every 3 years).
* Statutory termination rights (17 U.S.C. §203 and foreign equivalents),
  moral rights in some jurisdictions, and droit de suite do not apply to
  digital licenses but should be checked for print offers.
* Right-of-publicity, privacy and minors' image rules for releases.
* Drone footage: the operator's FAA Part 107 status and airspace authorizations
  are the creator's responsibility. Consider a declaration checkbox for aerial
  uploads.
* AI-generated or altered media: disclosure obligations (implemented as
  creator-declared flags) and evolving state and EU AI Act transparency rules.
* Accessibility: target WCAG 2.2 AA (ADA and the European Accessibility Act).
* Export controls and sanctions screening for payouts (handled through Stripe
  onboarding).

## Production Exchange addendum

| Feature | Legal question to resolve first |
|---|---|
| Urgent Crew and talent availability | Is any fee a "talent agency" or employment-agency fee requiring licensing (e.g. California Talent Agencies Act, New York employment agency law)? Start with free listings and commission only on services contracted through the platform after review |
| Worker classification | Contractor vs. employee for crews (California AB 5 and others); the platform should not set hours or direct work |
| Union productions | SAG-AFTRA, IATSE and Teamsters rules; let productions flag union status |
| Resource rentals | Rental agreements, insurance, deposits, damage policy, dispute procedure before enabling paid rentals |
| Contract templates | Counsel-reviewed templates only, with a visible "not legal advice" notice; uploads of custom contracts allowed |
| Lead exchange | No sale of personal contact data; consent-based contact reveal; CAN-SPAM, TCPA for SMS alerts |
| Production expense management | No holding or moving third-party funds outside approved payment flows |
