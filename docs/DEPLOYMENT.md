# Deployment: Vercel (frontend) + Railway (API and database)

```
Browser ──► Vercel (Next.js) ──rewrites /api/v1/*──► Railway (FastAPI) ──► Railway PostgreSQL
   │                                                     │
   └────────────► Cloudflare R2 public bucket (CDN) ◄────┘ (private bucket for originals)
```

## 0. Prerequisites

* GitHub repository (this one).
* Accounts: [Railway](https://railway.com), [Vercel](https://vercel.com),
  [Cloudflare](https://cloudflare.com) (R2 storage).
* Optional CLIs (PowerShell):

```powershell
npm install -g @railway/cli vercel
railway login
vercel login
```

## 1. Object storage (Cloudflare R2)

1. Cloudflare dashboard → **R2** → create two buckets: `media-originals`
   (private, never public) and `media-previews`.
2. On `media-previews`, connect a custom domain (for example
   `media.yourdomain.com`) or enable the r2.dev URL for testing.
3. **R2 → Manage API tokens** → create a token with *Object Read & Write* on
   both buckets. Note the Access Key ID, Secret Access Key and the S3 endpoint
   `https://<account-id>.r2.cloudflarestorage.com`.

## 2. API on Railway

1. Railway → **New Project → Deploy from GitHub repo** → choose this repo.
2. In the service **Settings**: set **Root Directory** to `backend`. Railway
   picks up `backend/railway.json` and builds `backend/Dockerfile` (Python 3.13
   + FFmpeg). The container runs `alembic upgrade head`, seeds reference data,
   then starts Uvicorn on `$PORT`. Health check: `/health`.
3. **New → Database → PostgreSQL** in the same project.
4. API service **Variables** (Raw editor):

```
ENVIRONMENT=production
DATABASE_URL=${{Postgres.DATABASE_URL}}
SECRET_KEY=<paste output of: python -c "import secrets; print(secrets.token_urlsafe(64))">
COOKIE_SECURE=true
PUBLIC_WEB_URL=https://<your-vercel-domain>
CORS_ORIGINS=["https://<your-vercel-domain>"]
STORAGE_BACKEND=s3
S3_ENDPOINT_URL=https://<account-id>.r2.cloudflarestorage.com
S3_REGION=auto
S3_ACCESS_KEY_ID=<r2 key id>
S3_SECRET_ACCESS_KEY=<r2 secret>
S3_PRIVATE_BUCKET=media-originals
S3_PUBLIC_BUCKET=media-previews
PUBLIC_MEDIA_BASE_URL=https://media.yourdomain.com
EMAIL_BACKEND=smtp
SMTP_HOST=<provider host>
SMTP_PORT=587
SMTP_USERNAME=<user>
SMTP_PASSWORD=<password>
BRAND_NAME=<final brand>
BRAND_SUPPORT_EMAIL=support@yourdomain.com
MALWARE_SCANNER=clamav
CLAMD_HOST=<clamav service private domain>
CLAMD_PORT=3310
FEATURE_PAID_LICENSING=false
FEATURE_EXCLUSIVE_LICENSING=false
```

   Startup fails on purpose if `SECRET_KEY` is the dev default,
   `COOKIE_SECURE` is false, or storage is not S3.

5. ClamAV (recommended before public uploads): **New → Docker Image →
   `clamav/clamav:stable`**. Give it at least 2 GB of RAM and use its private
   domain as `CLAMD_HOST`.
6. **Settings → Networking → Generate Domain**, which gives
   `https://<api>.up.railway.app`. Check it with
   `Invoke-RestMethod https://<api>.up.railway.app/health`.
7. Create the first administrator from a shell inside the service:

```powershell
railway link            # choose the project and API service
railway ssh             # opens a shell in the running container
python -m app.cli create-admin you@yourdomain.com "Your Name"
```

## 3. Frontend on Vercel

1. Vercel → **Add New → Project** → import this repo.
2. **Root Directory:** `frontend`. Framework preset: Next.js (auto-detected).
3. **Environment Variables:**

```
BACKEND_URL=https://<api>.up.railway.app
NEXT_PUBLIC_BRAND_NAME=<final brand>
NEXT_PUBLIC_BRAND_TAGLINE=Licensed photography, footage and production talent worldwide.
NEXT_PUBLIC_SUPPORT_EMAIL=support@yourdomain.com
NEXT_PUBLIC_BRAND_LOGO_URL=
NEXT_PUBLIC_HERO_VIDEO_URL=https://media.yourdomain.com/brand/hero.mp4
```

4. Deploy. Add your custom domain under **Settings → Domains**, then update
   `PUBLIC_WEB_URL` and `CORS_ORIGINS` on Railway to match.

Browser requests go to the Vercel domain; `next.config.ts` rewrites `/api/v1/*`
to Railway, so the session cookie is first-party. The API never needs to be
called cross-origin by the browser.

## 4. After every deploy

* Railway runs migrations automatically on start.
* Smoke test: register, verify email, open storefront, accept agreement,
  upload a photo, approve it as admin, search for it, download it free.
* Watch Railway logs and the error tracker for 15 minutes.

## 5. Backups and monitoring

* Enable Railway PostgreSQL backups (or move to a managed provider with
  point-in-time recovery) and run a weekly off-site `pg_dump` to a private R2
  bucket.
* Turn on R2 object versioning or lifecycle rules for the originals bucket.
* Add Sentry DSNs (frontend and backend) and an uptime check on `/health`.

## 6. Payments: Stripe Connect (Phase 2)

Paid licensing stays off (`FEATURE_PAID_LICENSING=false`) until the steps below
are complete **and** the licensing agreements are counsel-approved. Production
refuses to start with paid licensing on unless `PAYMENT_PROVIDER=stripe` and
both Stripe secrets are set.

1. **Stripe account.** Activate the platform account for the legal entity.
   Under **Connect → Settings**, choose *Express* accounts and complete the
   platform profile (marketplace, separate charges and transfers). Set the
   Express branding to the marketplace brand.
2. **Tax (optional).** To have Stripe calculate sales tax and VAT, enable
   Stripe Tax, add your registrations, and set `STRIPE_TAX_ENABLED=true`.
   License lines use product tax code `txcd_10000000` (general electronically
   supplied services). Confirm the right code with your tax adviser.
3. **Webhook endpoints.** Both use the same URL:
   `https://<your-web-domain>/api/v1/payments/webhooks/stripe` (Vercel proxies
   it to Railway).
   * **Developers → Webhooks → Add endpoint** ("Your account"), with events:
     `checkout.session.completed`, `checkout.session.async_payment_succeeded`,
     `checkout.session.async_payment_failed`, `checkout.session.expired`,
     `charge.refunded`, `charge.dispute.created`, `charge.dispute.closed`,
     `transfer.reversed`.
   * A second endpoint for **"Connected accounts"** with `account.updated`.

   Each endpoint has its own signing secret. Put both in
   `STRIPE_WEBHOOK_SECRET`, separated by a comma.
4. **Railway variables:**

```
PAYMENT_PROVIDER=stripe
STRIPE_SECRET_KEY=sk_live_...        # use sk_test_... in staging
STRIPE_WEBHOOK_SECRET=whsec_platform...,whsec_connect...
STRIPE_TAX_ENABLED=false
EARNINGS_HOLD_DAYS=14
MIN_PAYOUT_CENTS=1000
REFERRAL_ATTRIBUTION_DAYS=365
FEATURE_PAID_LICENSING=true
```

5. **Test mode first.** In staging with `sk_test_` keys, forward events
   locally with the Stripe CLI:

```powershell
stripe listen --forward-to localhost:8000/api/v1/payments/webhooks/stripe
```

   Then buy a license with card `4242 4242 4242 4242`. Check the
   certificate, the creator's pending earnings, and a clean reconciliation.
   Refund the order from Admin → Finance, and test a dispute with card
   `4000 0000 0000 0259`.

## 7. Daily finance job

Create a second Railway service from the same repo and root directory with:

* **Custom start command:** `python -m app.cli run-finance`
* **Cron schedule:** `17 6 * * *` (daily, 06:17 UTC)
* The same variables as the API (use Railway shared variables).

The job cancels abandoned checkouts, auto-approves delivered milestones the
client hasn't answered within `MILESTONE_AUTO_APPROVE_DAYS`, releases earnings
past their hold period, pays out available balances, and runs reconciliation. It exits
non-zero when reconciliation finds issues, so Railway marks the run failed and
alerts you. Finance admins can also run payouts and reconciliation from
Admin → Finance.

Cross-border note: Stripe Express transfers to creators outside the platform's
country need cross-border payouts enabled and are not available in every
country. Check Stripe's supported-country list before recruiting creators
abroad.
