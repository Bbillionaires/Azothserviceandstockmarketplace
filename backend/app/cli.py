"""Management commands.

    python -m app.cli seed                         # reference data (idempotent)
    python -m app.cli create-admin EMAIL NAME      # prompts for a password
    python -m app.cli demo                         # demo creators + media (dev only)
    python -m app.cli run-finance                  # daily: auto-approvals, earnings, payouts, reconciliation
"""

import argparse
import getpass
import io
import random
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from PIL import Image, ImageDraw
from sqlalchemy import select

from app.api.v1.auth import grant_role
from app.core.config import get_settings
from app.core.database import SessionLocal
from app.core.security import hash_password
from app.models import (
    AgreementTemplate,
    ContributorAgreement,
    CreatorProfile,
    LicenseType,
    MediaAsset,
    MediaStatus,
    MediaType,
    PriceListing,
    RoleCode,
    SignatureMethod,
    User,
)
from app.services import media_service as ms
from app.services.reference_data import seed_reference_data


def cmd_seed(_args) -> None:
    with SessionLocal() as db:
        seed_reference_data(db)
    print("Reference data seeded.")


def cmd_create_admin(args) -> None:
    password = getpass.getpass("Password (min 12 chars): ")
    if len(password) < 12:
        sys.exit("Password too short")
    with SessionLocal() as db:
        seed_reference_data(db)
        user = db.scalar(select(User).where(User.email == args.email.lower()))
        if not user:
            user = User(email=args.email.lower(), password_hash=hash_password(password), display_name=args.name,
                        email_verified_at=datetime.now(UTC))
            db.add(user)
            db.flush()
        grant_role(db, user, RoleCode.admin)
        grant_role(db, user, RoleCode.buyer)
        db.commit()
    print(f"Administrator {args.email} ready.")


DEMO_CREATORS = [
    ("aerial-atlas", "Aerial Atlas", "Drone cinematography", "Jacksonville", "FL", "US",
     ["drone_operator", "videographer"]),
    ("northlight-studio", "Northlight Studio", "Commercial & product photography", "Atlanta", "GA", "US",
     ["photographer", "production_studio"]),
    ("maya-reels", "Maya Okafor", "Documentary filmmaker · emerging talent", "Savannah", "GA", "US",
     ["filmmaker", "editor"]),
]

DEMO_MEDIA = [
    ("Downtown skyline at sunset", "aerial_drone", ["skyline", "sunset", "downtown", "aerial", "city"],
     (255, 140, 60), (40, 20, 70)),
    ("Riverfront bridge at blue hour", "architecture", ["bridge", "river", "night", "city lights"], (30, 60, 140), (10, 10, 30)),
    ("Coastal marsh from above", "nature_wildlife", ["marsh", "coast", "aerial", "green"], (60, 140, 90), (10, 50, 60)),
    ("Espresso pour close-up", "food", ["coffee", "espresso", "cafe", "macro"], (120, 70, 40), (20, 10, 5)),
    ("Founder portrait in studio", "business_finance", ["portrait", "business", "entrepreneur", "studio"],
     (90, 90, 100), (20, 20, 25)),
    ("Minimal product on marble", "product", ["product", "minimal", "marble", "ecommerce"], (220, 215, 205), (150, 140, 130)),
    ("Night market street scene", "travel", ["street", "market", "night", "people", "travel"], (200, 50, 80), (20, 10, 40)),
    ("Server room corridor", "technology", ["data center", "servers", "technology", "blue"], (20, 120, 200), (5, 10, 30)),
    ("Stadium lights before kickoff", "sports", ["stadium", "football", "sports", "lights"], (40, 160, 70), (10, 20, 10)),
    ("Modern kitchen interior", "real_estate", ["interior", "kitchen", "real estate", "home"], (230, 220, 200), (120, 100, 80)),
    ("Freight train through pines", "transportation", ["train", "freight", "forest", "transportation"],
     (90, 110, 70), (30, 30, 30)),
    ("Morning yoga on the beach", "lifestyle", ["yoga", "beach", "wellness", "morning"], (250, 200, 150), (80, 140, 200)),
]


def _gradient(size: tuple[int, int], top: tuple, bottom: tuple, seed: int) -> bytes:
    w, h = size
    img = Image.new("RGB", size)
    draw = ImageDraw.Draw(img)
    for y in range(h):
        t = y / h
        draw.line([(0, y), (w, y)], fill=tuple(int(top[i] * (1 - t) + bottom[i] * t) for i in range(3)))
    rnd = random.Random(seed)
    for _ in range(14):
        x, y, r = rnd.randint(0, w), rnd.randint(0, h), rnd.randint(w // 30, w // 8)
        shade = tuple(min(255, c + rnd.randint(10, 60)) for c in bottom)
        draw.ellipse([x - r, y - r, x + r, y + r], fill=shade)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=90)
    return buf.getvalue()


def cmd_demo(_args) -> None:
    if get_settings().is_production:
        sys.exit("Refusing to load demo data in production")
    with SessionLocal() as db:
        seed_reference_data(db)
        templates = {t.code: t for t in db.scalars(select(AgreementTemplate))}
        lts = {lt.code: lt for lt in db.scalars(select(LicenseType))}
        creators = []
        for handle, name, headline, city, region, country, cats in DEMO_CREATORS:
            profile = db.scalar(select(CreatorProfile).where(CreatorProfile.handle == handle))
            if not profile:
                user = User(email=f"{handle}@example.com", password_hash=hash_password("demo-password-123"),
                            display_name=name, email_verified_at=datetime.now(UTC))
                db.add(user)
                db.flush()
                grant_role(db, user, RoleCode.buyer)
                grant_role(db, user, RoleCode.creator)
                profile = CreatorProfile(user_id=user.id, handle=handle, display_name=name, headline=headline,
                                         bio=f"{name} is a demo storefront.", city=city, region=region,
                                         country_code=country, categories=cats, remote_available=True,
                                         is_emerging_talent=handle == "maya-reels", is_featured=handle != "maya-reels")
                db.add(profile)
                db.flush()
                for code in ("model_a_nonexclusive", "model_c_free"):
                    t = templates[code]
                    db.add(ContributorAgreement(
                        template_id=t.id, creator_id=profile.id, signer_user_id=user.id, signer_legal_name=name,
                        rights_owner_name=name, territory=t.territory, permitted_uses=t.permitted_uses,
                        sublicensing_allowed=t.sublicensing_allowed, duration=t.duration,
                        signature_method=SignatureMethod.clickwrap, signature_evidence={"demo": True},
                    ))
            creators.append(profile)
        db.commit()

        if db.scalar(select(MediaAsset.id).limit(1)):
            print("Demo media already present.")
            return
        for i, (title, category, keywords, top, bottom) in enumerate(DEMO_MEDIA):
            creator = creators[i % len(creators)]
            agreement = db.scalar(select(ContributorAgreement).where(
                ContributorAgreement.creator_id == creator.id,
                ContributorAgreement.template_id == templates["model_a_nonexclusive"].id))
            size = [(3840, 2160), (2400, 3600), (4000, 4000), (6000, 4000)][i % 4]
            asset = MediaAsset(creator_id=creator.id, uploaded_by=creator.user_id,
                               contributor_agreement_id=agreement.id, media_type=MediaType.photo,
                               status=MediaStatus.processing, title=title, description=f"Demo image: {title}.",
                               category=category, keywords=keywords, file_format="jpeg",
                               location_city=creator.city, location_region=creator.region,
                               location_country=creator.country_code, has_model_release=i % 3 == 0)
            db.add(asset)
            db.flush()
            tmp = Path(tempfile.mkdtemp()) / "demo.jpg"
            tmp.write_bytes(_gradient(size, top, bottom, i))
            asset.file_size_bytes = tmp.stat().st_size
            db.add(ms.new_declaration(asset, creator.user_id, creator.display_name, True, "", False, None, "demo"))
            db.commit()
            ms.process_asset(asset.id, tmp)
            db.refresh(asset)
            asset.status = MediaStatus.approved
            asset.published_at = datetime.now(UTC)
            if i % 3 == 0:
                asset.is_free = True
                db.add(PriceListing(asset_id=asset.id, license_type_id=lts["free_commercial"].id, price_cents=0))
            db.add(PriceListing(asset_id=asset.id, license_type_id=lts["standard_commercial"].id,
                                price_cents=2900 + 1000 * (i % 4)))
            db.add(PriceListing(asset_id=asset.id, license_type_id=lts["extended_commercial"].id,
                                price_cents=14900))
            db.commit()
            print(f"  + {title}")
    print("Demo data loaded. Demo creator password: demo-password-123")


def cmd_run_finance(_args) -> None:
    from app.services import payout_service
    from app.services.payments import get_provider
    from app.services.production_service import auto_approve_due

    with SessionLocal() as db:
        canceled = payout_service.cancel_stale_orders(db)
        db.commit()
        approved = auto_approve_due(db)
        db.commit()
        result = payout_service.run_payouts(db, get_provider())
        db.commit()
        run = payout_service.reconcile(db, provider=get_provider())
        db.commit()
    print(f"Canceled stale orders: {canceled}")
    print(f"Milestones auto-approved: {approved}")
    print(f"Payouts: {result}")
    print(f"Reconciliation: {run.status} ({len(run.findings)} findings)")
    if run.status != "ok":
        sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    sub = parser.add_subparsers(required=True)
    sub.add_parser("seed").set_defaults(func=cmd_seed)
    p = sub.add_parser("create-admin")
    p.add_argument("email")
    p.add_argument("name")
    p.set_defaults(func=cmd_create_admin)
    sub.add_parser("demo").set_defaults(func=cmd_demo)
    sub.add_parser("run-finance").set_defaults(func=cmd_run_finance)
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
