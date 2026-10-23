# Database Architecture

PostgreSQL in every deployed environment; SQLite only for fast local tests.
Schema changes go through Alembic (`backend/alembic/versions`). Conventions:

* UUID primary keys (`id`), `created_at` / `updated_at` in UTC (`timestamptz`).
* Money: integer minor units (`*_cents`) plus ISO-4217 `currency`.
* Percentages: integer basis points (`*_bps`, 10 000 = 100%).
* Enumerations: `VARCHAR` + `CHECK` constraint (portable, easy to extend).
* Deterministic constraint and index names (see `app/models/base.py`).
* Every foreign key states its `ON DELETE` behavior. Financial and legal
  records use `RESTRICT`, so they cannot be cascaded away.
* Append-only tables (`audit_logs`, planned `ledger_entries`,
  `financial_events`) are never updated or deleted by application code.

## 1. Implemented in Phase 1 (migration `0001`)

### Identity and organizations

| Table | Purpose | Key columns and constraints |
|---|---|---|
| `users` | Accounts | `email` UNIQUE; `password_hash`; `status` (active/suspended/banned/deactivated); `email_verified_at`; `mfa_secret`, `mfa_enabled`; `token_version` (session revocation); `referred_by_code` |
| `roles` | Permission roles | `code` UNIQUE: buyer, creator, rights_owner, affiliate, org_admin, moderator, finance_admin, admin |
| `user_roles` | Multi-role assignment | UNIQUE(`user_id`, `role_id`); `granted_by`, `granted_at` |
| `email_tokens` | Verification and reset tokens | Only the SHA-256 `token_hash` is stored (UNIQUE); `purpose`; `expires_at`; `used_at` (single use) |
| `organizations` | Studios, agencies, universities, clubs, vendors | `slug` UNIQUE; `org_type`; `verified_at` |
| `organization_members` | Membership | UNIQUE(`organization_id`, `user_id`); `member_role` (owner/admin/member/student). Membership never transfers content ownership. |

### Storefronts

| Table | Purpose | Key columns |
|---|---|---|
| `creator_profiles` | Public storefront (individual or organization-fronted) | `user_id` UNIQUE; `handle` UNIQUE; `categories` and `specialties` (JSON); coarse location only (`city`, `region`, `country_code`, `service_radius_km`); `remote_available`, `travel_available`; `verification_status`; `is_emerging_talent`, `is_featured` (indexed) |
| `follows` | Followers | UNIQUE(`user_id`, `creator_id`) |

### Media

| Table | Purpose | Key columns and indexes |
|---|---|---|
| `media_assets` | Photo or video listing | `creator_id`, `uploaded_by`, `contributor_agreement_id` (the agreement the upload was made under); `media_type`; `status` (processing, pending_review, approved, changes_requested, rejected, disabled, withdrawn, failed); technical metadata (dimensions, duration, fps, `resolution_label`, format, size); `checksum_sha256` and `perceptual_hash` (indexed, for duplicate detection); `scan_status`; location; disclosure flags (editorial-only, AI-generated, materially altered); release flags; `is_free`; counters. Indexes: (status, media_type), (creator_id, status), category, resolution, country, published_at; PostgreSQL GIN full-text index on `to_tsvector('english', search_text)` |
| `media_files` | Stored binaries per asset | UNIQUE(`asset_id`, `kind`); `kind` (original, preview, thumbnail, poster); `is_public`; `storage_key` |
| `media_releases` | Model and property releases | `release_type`; `subject_name`; private `document_storage_key`; verification fields |
| `copyright_declarations` | Uploader's sworn ownership statement | UNIQUE(`asset_id`); rights owner; original author; prior-license disclosure; `declaration_version` + full text; IP and user agent |
| `collections`, `collection_items` | Buyer collections | UNIQUE(`collection_id`, `asset_id`) |
| `favorites` | Buyer favorites | UNIQUE(`user_id`, `asset_id`) |

### Licensing

| Table | Purpose | Key columns |
|---|---|---|
| `license_types` | Buyer-facing license catalog | `code` UNIQUE (free_personal, free_attribution, free_commercial, personal, editorial, standard_commercial, extended_commercial, exclusive, negotiated); flags; `permitted_uses` (JSON); `terms_version`; `terms_markdown` |
| `revenue_share_rules` | **Versioned** commission configuration | UNIQUE(`code`, `version`); `revenue_model` (nonexclusive/exclusive/free); `creator_bps`; `initial_exclusive_creator_bps`; `affiliate_bps_of_platform`; `net_revenue_deductions` (JSON); CHECK bps ranges. Never updated in place. |
| `agreement_templates` | **Versioned** contributor agreements (Models A/B/C) | UNIQUE(`code`, `version`); `revenue_share_rule_id`; `body_markdown` + `body_sha256`; default territory, uses, sublicensing, duration, withdrawal terms; `legal_review_status` (draft/under_review/approved/retired) and reviewer |
| `contributor_agreements` | A creator's executed acceptance | `template_id` (exact version); signer and rights-owner names; terms frozen at signing; `signature_method` (clickwrap/esign_provider); `signature_evidence` (IP, user agent, document hash, environment, e-sign envelope id); `status` (active/superseded/terminated) |
| `price_listings` | Creator-set prices | UNIQUE(`asset_id`, `license_type_id`, `size_tier`); `price_cents` CHECK ≥ 0; `currency`; `subscription_credit_eligible` |
| `rights_grants` | Issued licenses (= license certificates) | `certificate_number` UNIQUE; asset, license type, licensee (user/org/name); `source` (free_download, purchase, subscription, exclusive_agreement, negotiated); `is_exclusive`; `territory`, `permitted_uses`; `starts_at`, `ends_at` (NULL = perpetual); price; `terms_version`; immutable `terms_snapshot`; `status`. Index (asset_id, status) for availability checks |
| `download_entitlements` | Permission to download an original | `rights_grant_id`; `max_downloads`, `download_count`; `expires_at` |

### Trust, safety and audit

| Table | Purpose |
|---|---|
| `moderation_decisions` | Every approve/reject/request-changes/disable/restore with reason, moderator and advisory `automated_signals` |
| `content_appeals` | Creator appeals; must be resolved by a different moderator |
| `copyright_complaints` | DMCA-style notices with required statements, status workflow (received → under_review → content_disabled → counter_notice_received → restored/closed) and counter-notice |
| `audit_logs` | Append-only actions log: actor, action, subject, details, IP |

## 2. Planned tables by phase

Each phase ships as its own Alembic migration.

### Phase 2: Monetization (implemented, migration `0002`)

| Table | Purpose |
|---|---|
| `orders` | Buyer checkout: status (pending, paid, partially_refunded, refunded, disputed, canceled), subtotal, tax, total, provider fee; UNIQUE(`buyer_user_id`, `idempotency_key`); UNIQUE `provider_session_id`, `provider_payment_id`; attributed `affiliate_user_id` |
| `order_lines` | Asset × license × size tier with price, tax and fee shares; the contributor agreement and **revenue-share rule version** used; the resulting `rights_grant_id` |
| `financial_events` | Raw provider events, UNIQUE(`provider`, `provider_event_id`) so webhooks process once; `processing_error` for retries |
| `ledger_accounts` | Chart of accounts per currency, UNIQUE(`code`, `currency`) |
| `ledger_journals` | One posting per business event, UNIQUE `idempotency_key` |
| `ledger_entries` | Journal lines; CHECK exactly one positive side; append-only |
| `royalty_allocations` | Engine output per order line (rule version, deductions, pools, explanation), UNIQUE per line |
| `earnings` | Payee sub-ledger with hold status (pending/available/paid/reversed); negative rows for clawbacks (`reverses_earning_id`) |
| `payout_accounts` | Stripe Express account per user: status, payouts enabled, outstanding requirements |
| `payouts` | Transfers to payees: UNIQUE `idempotency_key`, `provider_transfer_id`, journal, failure reason |
| `refunds` | One per refunded line: amount, reason, provider refund id, journal |
| `referral_codes`, `referrals` | One code per user; direct referrals with attribution window and fraud flags |
| `reconciliation_runs` | Results of each reconciliation (checks and findings) |

Still planned for monetization: `tax_profiles` (W-9/W-8 status via Stripe)
and creator-recruitment bonus tables.

### Phase 3: Custom production (implemented, migration `0003`)

| Table | Purpose |
|---|---|
| `project_requests` | Client briefs, including **Request This Shot** (`kind = shot_request`): category, deliverables, coarse location, remote OK, budget range, deadline, required `rights_preference` (exclusive/nonexclusive/custom), visibility (public/invite-only), status |
| `request_invitations` | Direct invitations / assignments to specific creators, UNIQUE(request, creator) |
| `service_packages` | Fixed-price storefront offers with delivery days, revisions and rights terms |
| `proposals` | Bids, UNIQUE(request, creator); milestone plan (JSON, sums to total), rights type and terms; visible only to the client and the bidder |
| `projects` | Bookings: client, creator, source (proposal or package), agreed rights snapshot, **acceptance evidence** (who/when/IP/terms), commission rule version, status |
| `milestones` | Amount, due date, status (unfunded → funded → submitted ⇄ revision_requested → approved / refunded / canceled / disputed), auto-approve time, released and refunded amounts |
| `deliverables` | Private files per milestone (checksum, size); never added to the stock catalog |
| `revision_requests` | Client change requests (counted against included revisions) |
| `conversations`, `conversation_participants`, `messages` | One conversation per pair and subject (request, project or direct); read markers |
| `notifications` | In-app notifications (key events also emailed) |
| `reviews` | Verified reviews: only on completed projects, once per direction, 1–5 rating, moderator can hide |
| `project_disputes` | Milestone disputes with previous state, resolution (release/refund/split with creator share) |
| `client_galleries`, `gallery_items`, `gallery_comments` | Private proofing galleries: secret link token, optional password, expiry, selection limit, download permission; items with private originals and watermarked proofs; favorites, selections, comments and revision requests |

Columns added to Phase 2 tables: `orders.purpose` (license/milestone) and
`orders.milestone_id`; `earnings.milestone_id` (and `order_line_id` now
nullable); `refunds.milestone_id` (and `order_line_id` now nullable). New enum
values: `service` revenue model, `service_milestone` earnings,
`service_funding`/`service_release`/`service_refund` journals,
`project_canceled`/`dispute_resolution` refund reasons.

### Gap closure (implemented, migration `0004`)

| Table | Purpose |
|---|---|
| `upload_sessions` | Direct-to-storage uploads: owner, purpose (media / deliverable / gallery_item), target, declared and maximum size, staged `incoming/` key, status, expiry |
| `gallery_print_options` | Print products a creator offers in a gallery (name, price); deactivated rather than deleted |
| `gallery_orders` | Guest gallery orders: link to `orders`, client name and email, shipping address, status, commission rule snapshot, outstanding allocation by account, chargeback snapshot, carrier and tracking |
| `gallery_order_items` | Digital downloads and prints per order (quantity, unit price) |

New columns: `orders.buyer_email` (and `buyer_user_id` now nullable for guest
gallery orders); `order_lines.refunded_cents`; `refunds.allocation` (accounts
reversed) and several refunds per line (unique constraint dropped);
`earnings.order_id` (gallery sales); `referrals.creator_bonus_paid_at`;
`milestones.affiliate_user_id`, released amounts outstanding per party
(`release_creator_cents`, `release_affiliate_cents`, `release_platform_cents`),
`reversed_release_cents`, `tax_refunded_cents`, `chargeback_snapshot`;
`deliverables.scan_status` (and `checksum_sha256` nullable until scanned);
`client_galleries.download_price_cents` and `currency`;
`gallery_items.download_unlocked`. New enum values: `gallery` order purpose,
`gallery_sale` and `referral_bonus` earnings and journals,
`price_adjustment` refund reason.

### Phase 4: Partnerships and advanced licensing

`university_partnerships` (organization extension: program type, ambassador,
referral code), `organization_commission_authorizations` (member-signed),
`collaborations`, `collaboration_members` (bps shares that must total 10 000,
signature evidence), `exclusive_deals` (negotiated territory, uses, term,
minimum guarantee, carve-outs of prior licenses), `esign_envelopes` (provider
envelope id, status, signed PDF key), `syndication_partners`,
`syndication_authorizations` (creator opt-in per channel),
`syndication_transactions`.

### Phase 5: Global scale

`subscription_plans` (versioned), `subscriptions`, `credit_ledger` (grants,
consumption, expiry), `enterprise_accounts`, `enterprise_contracts`,
`api_clients` and `api_keys` (hashed), `media_embeddings` (pgvector, for AI
search), `ai_tags` (source, confidence), `creator_subscriptions`.

### Film Production Exchange (addendum)

| Table | Purpose |
|---|---|
| `availability_profiles` | Per-professional settings: categories, project types, service area, travel and remote, rate (or negotiable), minimum booking, `share_calendar` privacy level |
| `availability_windows` | Public available date ranges. Private calendar events are never stored or exposed; only "available" blocks the professional publishes |
| `urgent_crew_requests` | Position, location, start time, duration, compensation, requirements, application deadline, contact method, `employer_verified` snapshot |
| `urgent_crew_applications` | Applicant, note, status |
| `notification_preferences` | Opt-in per category, radius and channel |
| `vendor_profiles` | Organization extension for production vendors: categories (catering, transport, security...), service areas, listing tier (free/paid) |
| `vendor_inquiries` | Inquiries from productions |
| `rfp_requests` | Bid exchange: specs, budget range, deadline, visibility (public/private) |
| `rfp_invitations` | Private invitations |
| `rfp_bids` | Proposal documents (private bucket), price; visible only to the requester and the bidder (row-level checks in the service layer) |
| `production_packages`, `package_members` | Bundled services; member role and allocation bps; member authorization evidence |
| `resource_listings`, `resource_inquiries` | Equipment, studio space, props, vehicles (listings and inquiries only until rental terms exist) |
| `contract_templates`, `contracts`, `contract_parties` | Versioned, counsel-reviewed templates or uploaded custom contracts; signature status; private document storage |
| `budget_lines`, `expenses`, `vendor_invoices`, `payment_commitments` | Production expense tracking linked to the ledger when paid through approved payment flows |
| `team_rosters`, `preferred_vendors`, `rebooking_invitations` | Rebooking and saved teams |
| `business_leads`, `lead_responses`, `saved_leads` | Lead exchange. Contact data is revealed only by the lead owner's action |

## 3. Indexing and scaling notes

* Catalog search: GIN full-text index now; add `pg_trgm` for fuzzy matching,
  then a dedicated engine (Meilisearch or Typesense) once the catalog passes
  about 500k assets or relevance tuning needs it. Embeddings (pgvector) back
  AI search.
* Duplicate detection compares perceptual hashes in the application today. At
  scale, move to BK-tree or LSH buckets, or a vector index.
* Counters (`view_count`, `download_count`) move to an event table plus
  periodic aggregation when write contention appears.
* Partition `audit_logs`, `financial_events` and `ledger_entries` by month
  once they pass tens of millions of rows.
* Read replica for analytics and admin reporting at the 10k+ user tier.
