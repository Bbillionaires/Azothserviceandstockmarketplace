# Infrastructure Cost Estimates

Monthly USD estimates based on public list prices as of late 2026. **Re-check
current pricing before budgeting.** Excludes payment processing (a pass-through
percentage of revenue: Stripe ≈ 2.9% + $0.30 per card charge, plus Connect fees
of about $2 per monthly active connected account and 0.25% + $0.25 per payout),
payroll, legal and marketing.

## Assumptions

| | Launch | 1,000 users | 10,000 users | 100,000 users |
|---|---|---|---|---|
| Active creators | 50 | 300 | 2,000 | 15,000 |
| Photos in catalog | 1,500 | 15,000 | 150,000 | 1,500,000 |
| Video clips in catalog | 500 | 5,000 | 50,000 | 500,000 |
| Monthly site visitors | 2,000 | 20,000 | 150,000 | 1,500,000 |
| Licensed downloads / month | 200 | 2,000 | 20,000 | 200,000 |

Per-asset storage:

* Photo original ≈ 15 MB, previews ≈ 1 MB.
* Video original (mostly 4K, 20–60 s) ≈ 400 MB; watermarked 30 s, 960 px
  preview ≈ 4 MB; poster and thumbnail ≈ 0.5 MB.

Per-visit bandwidth: about 30 preview views, 70% photo (≈ 0.3 MB) and 30% video
(≈ 4 MB), so ≈ 40 MB per visit. Licensed downloads average ≈ 100 MB.

| | Launch | 1,000 | 10,000 | 100,000 |
|---|---|---|---|---|
| **Stored data** | ≈ 0.23 TB | ≈ 2.3 TB | ≈ 23 TB | ≈ 230 TB |
| **Preview egress / month** | ≈ 0.08 TB | ≈ 0.8 TB | ≈ 6 TB | ≈ 60 TB |
| **Original downloads / month** | ≈ 0.02 TB | ≈ 0.2 TB | ≈ 2 TB | ≈ 20 TB |

## Recommended stack and monthly cost

Storage: Cloudflare R2 (≈ $0.015/GB-month standard, ≈ $0.01 infrequent access,
**$0 egress**), fronted by Cloudflare's CDN. Hosting: Vercel (frontend) and
Railway (API, worker, PostgreSQL, ClamAV).

| Item | Launch | 1,000 users | 10,000 users | 100,000 users |
|---|---|---|---|---|
| Vercel (Pro plan; Hobby does not allow commercial use) | $20 | $20–40 | $50–150 | $300–1,000 |
| Railway API service(s) | $10–20 | $30–60 | $150–300 | $600–1,200 |
| Media worker (FFmpeg transcoding) | in API | $20–40 | $150–400 | $1,000–2,500 |
| PostgreSQL (Railway, later managed HA) | $5–15 | $20–40 | $100–250 | $500–1,200 |
| ClamAV scanner container | $0 (off in dev) | $15–25 | $25–50 | $100–200 |
| Redis (queue, rate limits) | — | $5–10 | $20–40 | $100–200 |
| Object storage (R2) | $4 | $35 | $350 | $2,500–3,500 (IA tier for originals) |
| R2 operations | <$1 | $2–5 | $20–50 | $200–400 |
| CDN / WAF (Cloudflare) | $0 | $0–25 | $25–250 | $250–2,000 |
| Search engine (Meilisearch/Typesense) | — (Postgres FTS) | — | $50–150 | $300–800 |
| Transactional email | $0 (free tier) | $0–20 | $20–90 | $200–500 |
| Error tracking and logs | $0 (free tiers) | $0–30 | $30–100 | $200–600 |
| Backups (PITR, off-site copies) | $0–5 | $5–15 | $30–80 | $150–400 |
| E-signature (Phase 4) | — | $0–40 | $50–150 | $300–1,000 |
| AI tagging and embeddings (Phase 5) | — | — | $50–200 | $500–2,000 |
| **Estimated total** | **≈ $45–90** | **≈ $150–350** | **≈ $1,100–2,500** | **≈ $7,500–17,000** |

### Why R2 instead of S3 + CloudFront

Bandwidth dominates video marketplaces. At the 10,000-user tier, ≈ 8 TB of
monthly egress would cost about $700 at ≈ $0.085/GB on AWS; at 100,000 users,
≈ 80 TB costs roughly $5,000–6,500 a month. R2 charges nothing for egress.
The code uses the S3 API, so switching providers is an environment-variable
change.

### When to change approach

* **Video previews at scale.** If streaming quality matters more than cost
  (adaptive bitrate, analytics), move previews to Cloudflare Stream
  (≈ $5 per 1,000 minutes stored, ≈ $1 per 1,000 minutes delivered) or Mux.
  With 500k clips, 30-second previews ≈ 250k minutes ≈ $1,250 stored, plus
  delivery.
* **Large uploads.** Above about 1 GB, uploads should go straight from the
  browser to R2 through presigned multipart URLs instead of through the API.
  This is planned for Phase 2 and removes most API bandwidth and timeouts.
* **Transcoding spikes.** Run the worker as an autoscaled queue consumer.
  Beyond about 10k new clips a month, compare cost with a managed transcoder.
* **Cold originals.** Move originals not downloaded in 90 days to the
  infrequent-access tier (about 33% cheaper).

## Avoiding unnecessary subscriptions

Launch needs only Vercel Pro, Railway (usage-based), Cloudflare (R2 plus free
CDN), a domain, and free tiers of an email provider and error tracker. Stripe
has no monthly fee. E-signature, search, AI and streaming services are added
only when their phase ships.
