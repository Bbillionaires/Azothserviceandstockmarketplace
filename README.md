# Global Media Marketplace

Stock photography and video licensing, creator storefronts, and (in later
phases) custom production services and a film production exchange.
An independent marketplace of **One United Enterprise LLC**, *Powered by
Azoth Digital*. The marketplace name and domain are not final; "Lumen & Reel"
is a configurable placeholder.

| Folder | Stack |
|---|---|
| [`backend/`](backend) | Python 3.12+, FastAPI, SQLAlchemy 2, Alembic, PostgreSQL, Pillow, FFmpeg |
| [`frontend/`](frontend) | Next.js 15, TypeScript, Tailwind CSS 4 |
| [`docs/`](docs) | Architecture, database, licensing and royalties, legal dependencies, costs, roadmap, deployment |

**Start with [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).**

## What works today (Phase 1)

* Accounts with email verification, password reset, optional authenticator-app
  MFA, and multiple roles per account.
* Creator storefronts with location and specialty discovery and an "emerging
  talent" category.
* Versioned contributor agreements (Models A/B/C) with signature evidence.
  Exclusive deals cannot be click-accepted.
* Photo and video upload with magic-byte validation, a malware-scan hook,
  watermarked previews (FFmpeg for video), private originals and duplicate
  signals.
* Search with filters, facets, PostgreSQL full-text search and
  natural-language filter extraction.
* Creator-controlled pricing; free licenses with certificate numbers, public
  certificate verification and signed, expiring download links.
* Moderation queue, appeals, a DMCA notice and counter-notice workflow,
  versioned commission rules, and an audit log.
* Tested royalty engine (50/50, 65/35 initial exclusive, affiliate commission
  from the platform share, collaborator splits) and rights-availability checks
  that block conflicting exclusive grants.

**Phase 2 (monetization):**

* Cart and checkout through Stripe Checkout. A fake provider lets you test the
  whole flow locally without Stripe.
* Server-side re-pricing, signed and idempotent webhooks, and licenses issued
  on payment.
* An append-only double-entry ledger. Royalties are calculated for every order
  line using the creator's signed rule version.
* Creator and affiliate earnings with a 14-day hold, Stripe Express payout
  onboarding, automatic payouts and monthly CSV statements.
* Refunds, chargebacks (including won disputes) and clawbacks.
* Referral links with commission paid from the platform share.
* Finance console with reconciliation.

**Phase 3 (custom production):**

* Production briefs and **Request This Shot**, where clients must choose the
  rights they want.
* A creator board, rules-based creator matching, invitations, and confidential
  proposals with milestone plans.
* Fixed-price packages on storefronts.
* Bookings that record the agreed rights and acceptance evidence.
* Milestone payments held until the client approves, with private deliverable
  files, revision limits, auto-approval and cancellation rules.
* Disputes resolved by staff (release, refund or split).
* Messaging and notifications, and verified two-way reviews.
* Private client proofing galleries.

**Gap closure (hardening and money edge cases):**

* A Redis-backed RQ worker for media, gallery and deliverable processing, and
  Redis rate limits shared across API replicas.
* Direct-to-storage uploads (presigned PUT) with upload sessions and progress.
* Resend email, and Cloudflare Turnstile CAPTCHA on public forms.
* Partial refunds, refunds issued in the Stripe dashboard, per-line Stripe
  tax, and reconciliation against Stripe balance activity.
* Bookings: referral commissions, refunds after release, chargebacks restored
  when won, and automatic refunds of duplicate payments.
* Creator-recruitment referral bonus, a multi-currency cart and earnings, and
  payout tax-information status.
* Gallery add-on sales: paid downloads and creator-fulfilled prints with guest
  checkout and shipping tracking.

See [docs/ROADMAP.md](docs/ROADMAP.md) for status and remaining limitations.
Nothing here is production-ready until the legal texts are reviewed and
Stripe is verified in test mode.

## Quick start on Windows (PowerShell)

Install once: [Python 3.12+](https://www.python.org/downloads/) (tick "Add to
PATH"), [Node.js 22 LTS](https://nodejs.org), [Git](https://git-scm.com), and
FFmpeg (needed for video previews):

```powershell
winget install Gyan.FFmpeg
```

### 1. Backend API

```powershell
cd backend
python -m venv .venv
# If activation is blocked: Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
.\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
Copy-Item .env.example .env
```

Edit `.env`. The quickest option is SQLite: set
`DATABASE_URL=sqlite:///./dev.db`. For PostgreSQL (recommended), install it
with `winget install PostgreSQL.PostgreSQL.16` or Docker, create a
`marketplace` database and use
`DATABASE_URL=postgresql://postgres:<password>@localhost:5432/marketplace`.

```powershell
alembic upgrade head                       # create tables
python -m app.cli seed                     # roles, license types, draft agreements
python -m app.cli create-admin you@example.com "Your Name"
python -m app.cli demo                     # optional: 3 demo creators + 12 images
# To try paid checkout locally, set FEATURE_PAID_LICENSING=true in .env (fake provider, no money moves)
uvicorn app.main:app --reload --port 8000  # API docs: http://localhost:8000/docs
```

Without `REDIS_URL`, uploads are processed inside the API process, which is
fine for development. To run the production setup locally, start Redis
(`docker run -p 6379:6379 redis:7`), set `REDIS_URL=redis://localhost:6379/0`
and run a worker in another window. On Windows, RQ needs WSL or Docker because
it relies on `fork`:

```powershell
rq worker default --url redis://localhost:6379/0 --with-scheduler
```

Verification and reset emails are printed in this terminal in development.
Copy the link from there.

### 2. Frontend

In a second PowerShell window:

```powershell
cd frontend
npm install
Copy-Item .env.example .env.local
npm run dev                                # http://localhost:3000
```

### 3. Tests

```powershell
cd backend
.\.venv\Scripts\Activate.ps1
pytest                 # royalties, rights, auth, media, admin, video, migrations, commerce, production, gaps
ruff check .

cd ..\frontend
npm run typecheck
npm run build
```

macOS and Linux use the same commands with `source .venv/bin/activate` and
`cp` instead of `Copy-Item`.

## Deploying

Vercel (frontend) + Railway (API, worker, PostgreSQL, Redis, ClamAV, daily finance cron) +
Cloudflare R2 (storage) + Stripe Connect (payments). Step by step in [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md).

## Development rules

* Backend and frontend stay separate; branding stays configurable.
* Money is integer cents; commission terms are versioned and never edited in
  place.
* Exclusive licensing and paid licensing stay behind feature flags until
  agreements are counsel-approved and payments are tested.
* Every new module ships with a migration and tests.
