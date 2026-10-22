# Licensing, Royalties, Payments and Payouts

> The commercial arrangements below (Models A, B and C, the percentages, and
> affiliate terms) are **proposals** from the business plan. They are
> configurable data, not hard-coded promises, and must be reviewed by qualified
> counsel before activation. Generated agreements are not presumed enforceable
> because software produced them.

## 1. Three layers of rights

| Layer | Between | Record | Answers |
|---|---|---|---|
| **Contributor agreement** | Creator/rights owner ↔ platform | `contributor_agreements` → `agreement_templates` (version) → `revenue_share_rules` (version) | What the platform may do with the media, and how revenue is shared |
| **License grant** | Platform ↔ buyer | `rights_grants` (certificate) + `download_entitlements` | What this buyer may do with this asset |
| **Collaboration allocation** | Among co-creators | `collaborations` / `collaboration_members` (Phase 4) | How the creator pool is divided |

Copyright stays with the creator or rights owner in every model, including
exclusive deals. The platform's catalog value comes from **licensed rights**
(perpetual nonexclusive licenses under Model A, and defined exclusive rights
under Model B), never from assumed ownership of uploads.

### What every agreement records

Contract version and text hash; creator identity; rights-owner identity;
copyright declaration (per asset); license model; rights granted; territory;
permitted uses; effective date; duration; exclusivity; sublicensing authority;
revenue formula (rule code and version); royalty conditions; acceptance or
signature evidence (IP, user agent, timestamp, document SHA-256, e-sign envelope
id); prior-rights disclosure; withdrawal and termination terms; status history;
and dispute history (via moderation decisions and complaints linked to the
assets). Phase 1 implements all of these except e-sign envelopes and per-deal
exclusive terms, which arrive with Phase 4.

### Withdrawal and termination

* A creator can **withdraw** an asset at any time. It leaves the catalog, but
  licenses already granted remain valid (enforced: withdrawal changes only the
  asset status, never `rights_grants`).
* Terminating a contributor agreement stops new licensing under it. Customer
  licenses issued before termination survive, as the agreement text will state.
* Statutory termination rights (for example 17 U.S.C. §203, which lets authors
  terminate grants after 35 years) cannot be contracted away. Agreements must
  acknowledge them, and the data model keeps the grant date and parties needed
  to process a notice.

## 2. Revenue models

| | Model A: Perpetual nonexclusive | Model B: Perpetual exclusive | Model C: Free |
|---|---|---|---|
| Rule code | `model_a_nonexclusive` | `model_b_exclusive` | `model_c_free` |
| Platform right | Perpetual, nonexclusive license for defined uses; sublicensable to buyers | Defined exclusive rights under a separately signed agreement | Distribution under the free license the creator selects |
| Creator may license elsewhere | Yes | No, within the exclusive scope | Yes |
| Split of net revenue | 50% creator / 50% platform | **Initial** exclusive transaction 65 / 35; subsequent qualifying transactions 50 / 50 *where the contract provides* | No royalty on zero-revenue downloads |
| Activation | Click-accept allowed once counsel approves the version | Never click-accept; e-signature per deal and feature flag | Click-accept allowed once counsel approves the version |

The initial-transaction treatment, continuing royalties and minimum guarantees
for Model B are still open business points. They are therefore modeled as rule
parameters (`initial_exclusive_creator_bps`, `creator_bps`) plus per-deal fields
on `exclusive_deals` (Phase 4), not as fixed code.

## 3. Net licensing revenue (definition)

For one order line:

```
gross                    = price the buyer paid for the license line (after discounts, before tax)
− taxes_collected        = sales tax / VAT / GST collected for remittance           (always excluded)
− payment_processing_fees= the processor fee attributable to the line, pro rata   (configurable)
− partner_distribution_fees = fee retained by a syndication partner, if any       (configurable)
− chargeback_fees        = dispute fees, when the rule version includes them       (configurable)
= net licensing revenue
```

Which deductions apply is stored on each `revenue_share_rules` version
(`net_revenue_deductions`). Seeded versions deduct taxes, processing fees and
partner distribution fees. **Refunds and chargebacks are not deductions.** They
are recorded later as reversal journal entries that claw back the exact original
allocation, so the original calculation is never edited.

## 4. Royalty engine

`backend/app/services/royalty_engine.py`: pure functions with no database or
network access. 13 unit tests, including a 2 000-case randomized reconciliation
test.

```
net            = gross − Σ(deductions listed in the rule version)
creator_bps    = rule.initial_exclusive_creator_bps   if initial exclusive transaction
                 rule.creator_bps                     otherwise
creator_pool   = round_half_up(net × creator_bps / 10 000)
platform_share = net − creator_pool                  (absorbs rounding; always reconciles)
affiliate      = floor(platform_share × affiliate_bps / 10 000)   if an affiliate is attributed
platform_net   = platform_share − affiliate
collaborators  = split creator_pool by signed bps (largest-remainder; sums exactly)
assert Σ allocations == net
```

Guarantees, all enforced by tests:

* **Affiliate commission comes from the platform share**, never the creator's
  royalty. Example: $100 → creator $50, platform $50, affiliate $5 (10% of the
  platform share), platform keeps $45.
* **Collaborations divide only the creator pool.** Example: $100 → $50 pool →
  videographer 50% ($25), editor 30% ($15), drone operator 20% ($10); the
  platform still receives $50.
* Exclusive initial transaction: $1,000 → $650 creator / $350 platform.
* Free rule cannot be applied to a paid transaction; negative amounts,
  unknown deductions and shares that do not total 100% are rejected.
* Every result carries the rule code and version and a human-readable
  explanation for statements (`RoyaltyResult.explain()`).

Administrators can dry-run any stored rule version through
`POST /api/v1/admin/royalty-preview`.

### Commission changes

`POST /api/v1/admin/revenue-rules` (finance_admin or admin) creates a **new
version**. No endpoint edits or deletes a version. New terms reach creators only
when an agreement template is re-issued against the new rule version and the
creator accepts it. Signed agreements keep their original version.

### Subscription royalties (Phase 5)

Credits carry an **effective value** = plan net price for the period ÷ credits
included. A download that consumes *n* credits generates royalty revenue of
*n* × effective value, which then runs through the same engine and the creator's
rule. Unused credits ("breakage") are retained by the platform, which must be
disclosed in creator terms. An optional per-download minimum royalty can be
added as a rule parameter. Unlimited-download plans stay off until abuse and
financial risks are modeled.

## 5. Rights availability

`backend/app/services/rights_availability.py` (6 tests) runs before any grant.

* A scope is territory × permitted uses × time window (`WORLDWIDE` and `ALL`
  are wildcards; `ends_at = NULL` is perpetual).
* A request **conflicts** with an active grant when the scopes overlap and
  either side is exclusive.
* An exclusive request over existing **nonexclusive** licenses is blocked by
  default. Those licenses are returned as *prior obligations*; the deal may
  proceed only if they are explicitly accepted as disclosed carve-outs.
* Free downloads already run this check. Paid checkout and exclusive deals
  will run it inside the same database transaction that inserts the grant,
  with a row lock on the asset, to prevent races.

## 6. Payment and payout workflow (implemented in Phase 2)

Provider: **Stripe Connect** with **Express** connected accounts, using
**separate charges and transfers**. That model is required because one sale can
pay several parties (creator, collaborators, affiliate). Stripe performs
identity verification (KYC), holds the money-transmission licenses, and issues
1099-K forms where applicable. The platform never holds funds outside Stripe.

```mermaid
sequenceDiagram
  participant Buyer
  participant Web as Next.js
  participant API as FastAPI
  participant Stripe
  participant Ledger as Ledger (Postgres)

  Buyer->>Web: Choose license(s)
  Web->>API: POST /orders (idempotency key)
  API->>API: Re-price from price_listings, check rights availability
  API->>Stripe: Create PaymentIntent (metadata: order id, transfer_group)
  API-->>Web: client_secret
  Buyer->>Stripe: Pay (Stripe Elements; card data never touches us)
  Stripe-->>API: webhook payment_intent.succeeded (signed)
  API->>API: Verify signature; insert financial_events (event id UNIQUE → idempotent)
  API->>Ledger: Journal: Dr clearing / Cr creator_payable, affiliate_payable, platform_revenue, tax_payable, fees
  API->>API: Create rights_grants + certificates + download entitlements
  API-->>Buyer: Email certificate + download links
  Note over API,Ledger: Hold period (e.g. 14 days) for refunds and chargebacks
  API->>Stripe: Transfer to each connected account (transfer_group, idempotency key)
  API->>Ledger: Journal: Dr creator_payable / Cr clearing (payout)
  Stripe-->>API: transfer.* / payout.* webhooks → reconcile
```

Rules:

1. **Prices are re-computed server-side** from `price_listings`. Client-sent
   amounts are ignored.
2. **Idempotency everywhere.** Orders take a client idempotency key. Every
   Stripe call passes an idempotency key derived from our row id. Webhook
   processing is keyed by Stripe's event id (UNIQUE), so a retried event is a
   no-op.
3. **Immutable financial events.** Raw webhook payloads go to
   `financial_events`, and journal entries are append-only and balanced.
   Corrections are new reversing entries.
4. **Balances come from the ledger.** "Available", "pending" and "paid" amounts
   in creator dashboards are ledger queries. The frontend never computes them.
5. **Refunds and chargebacks** create reversal journals that mirror the
   original allocation. If a transfer was already sent, a transfer reversal is
   requested, or the amount is netted against future earnings according to the
   creator terms.
6. **Daily reconciliation job** compares Stripe balance transactions, transfers
   and payouts with ledger totals and flags any mismatch for finance admins.
   It also exports monthly reports.
7. **Payout onboarding.** Creators complete Stripe-hosted onboarding.
   Earnings accrue in the ledger before onboarding and are transferred once the
   account is enabled.
8. **Tax.** Use Stripe Tax (or an equivalent) for sales tax and VAT on license
   sales. Collect W-9/W-8 through Stripe Connect onboarding. Platform-issued
   information returns (for example 1099-NEC for affiliates, if applicable)
   need advice from an accountant.

### Custom production payments (Phase 3)

Milestone payments use the same Connect flow: the customer pays a milestone
upfront, funds stay in the platform's Stripe balance until the deliverable is
approved (or auto-approved after a review window), then transfer. This is
described as a *marketplace payment workflow*, **not escrow**. Stripe's limits
on how long funds can be held, and counsel's view on money transmission and
escrow terminology, set the maximum hold periods.

## 7. Phase 2 implementation notes

Code: `app/services/payment_service.py` (orders, fulfillment, refunds,
disputes, webhook events), `app/services/ledger.py` (double-entry ledger),
`app/services/payout_service.py` (hold release, payouts, reconciliation),
`app/services/referral_service.py`, and `app/services/payments/` (Stripe and
fake provider adapters). 21 tests in `tests/test_commerce.py` plus the engine
tests.

### Chart of accounts

| Code | Type | Meaning |
|---|---|---|
| `clearing:<provider>` | asset | Money in the provider balance (Stripe) |
| `tax_payable` | liability | Tax collected for remittance |
| `creator_payable:<user>` | liability | Owed to a creator, not yet transferred |
| `affiliate_payable:<user>` | liability | Owed to a referral partner |
| `platform_revenue` | revenue | Platform share after affiliate commission |
| `fee_recovery` | revenue | Processing fees deducted from net revenue before the split |
| `processing_fees` | expense | Fees charged by the provider |
| `refund_losses` | expense | Dispute fees and other absorbed losses |

### Journals

| Event | Entries |
|---|---|
| Sale | Dr clearing (total − fee), Dr processing_fees (fee); Cr tax_payable, Cr creator_payable, Cr affiliate_payable, Cr platform_revenue, Cr fee_recovery |
| Refund (per line, full) | Exact mirror of the line's credits; Cr clearing (price + tax). The provider keeps its original fee, so the platform absorbs it |
| Chargeback | Same reversal as a refund, plus Dr refund_losses / Cr clearing for the dispute fee; licenses are revoked |
| Dispute won | Re-posts the line credits against clearing; licenses and earnings are restored (new hold period) |
| Payout | Dr creator_payable / affiliate_payable; Cr clearing |
| Failed or reversed transfer | Mirror of the payout journal; the earnings become available again |

Every journal is checked for balance before insert and has a unique
idempotency key (`sale:<order>`, `refund:<line>`, `payout:<id>`, ...).

### Earnings sub-ledger and holds

Each sale creates `earnings` rows for the creator (and affiliate) with status
`pending` until `EARNINGS_HOLD_DAYS` (default 14) pass, then `available`. The
daily job pays available balances of at least `MIN_PAYOUT_CENTS` to payees
whose Stripe Express account has payouts enabled. A refund before payout
marks the earning `reversed`. A refund after payout adds a *negative* earning
that nets against the next payout, so a payee's available balance can be
negative. Reconciliation verifies that every payable ledger account equals the
unpaid earnings for that payee.

### Reconciliation (`python -m app.cli run-finance`, or Admin → Finance)

Checks: all journals balanced; payables match unpaid earnings; every
non-pending order has a sale journal and correct totals; every fulfilled line
has an active license and a royalty allocation; no payouts stuck in
`processing` for over an hour; no unprocessed provider events. It also
reports the clearing balance so finance can compare it with the Stripe
balance. A non-`ok` run exits non-zero for cron alerting.

### Known limitations

* Refunds are whole-line only. A partial refund issued in the Stripe dashboard
  is stored and flagged for manual review rather than guessed at.
* Tax is allocated to lines in proportion to their prices (Stripe Tax returns
  an order total).
* Checkout sessions are single-currency; multi-currency pricing is Phase 5.
* Provider-side reconciliation (matching Stripe balance transactions line by
  line) is manual for now: compare the reported clearing balance with the
  Stripe dashboard.
* Affiliate commissions cover customer acquisition only. Creator-recruitment
  bonuses are not built yet.
