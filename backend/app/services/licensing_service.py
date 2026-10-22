"""Issuing licenses (rights grants) and download entitlements."""

from __future__ import annotations

import secrets
from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import sign_download
from app.models import (
    CreatorProfile,
    DownloadEntitlement,
    GrantSource,
    GrantStatus,
    LicenseType,
    MediaAsset,
    MediaStatus,
    PriceListing,
    RightsGrant,
    User,
)
from app.services import audit
from app.services.rights_availability import RightsScope, check_availability

CERT_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def new_certificate_number() -> str:
    return f"LC-{datetime.now(UTC):%Y%m}-" + "".join(secrets.choice(CERT_ALPHABET) for _ in range(10))


def active_scopes(db: Session, asset_id) -> list[RightsScope]:
    grants = db.scalars(
        select(RightsGrant).where(RightsGrant.asset_id == asset_id, RightsGrant.status == GrantStatus.active)
    )
    return [
        RightsScope.build(g.territory, g.permitted_uses, g.starts_at, g.ends_at, g.is_exclusive, str(g.id))
        for g in grants
    ]


def issue_free_license(
    db: Session, user: User, asset: MediaAsset, license_code: str, licensee_name: str | None, ip: str | None
) -> tuple[RightsGrant, DownloadEntitlement]:
    if asset.status is not MediaStatus.approved:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Media not found")
    listing = db.scalar(
        select(PriceListing)
        .join(LicenseType, LicenseType.id == PriceListing.license_type_id)
        .where(
            PriceListing.asset_id == asset.id,
            PriceListing.is_active,
            LicenseType.code == license_code,
            LicenseType.is_free,
            PriceListing.price_cents == 0,
        )
    )
    if not listing:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This media is not offered free under that license")
    lt = listing.license_type

    # Reuse an existing active free grant so repeat downloads don't mint new certificates.
    existing = db.scalar(
        select(RightsGrant).where(
            RightsGrant.asset_id == asset.id,
            RightsGrant.licensee_user_id == user.id,
            RightsGrant.license_type_id == lt.id,
            RightsGrant.status == GrantStatus.active,
        )
    )
    if existing:
        ent = db.scalar(select(DownloadEntitlement).where(DownloadEntitlement.rights_grant_id == existing.id))
        if ent:
            return existing, ent

    now = datetime.now(UTC)
    requested = RightsScope.build(["WORLDWIDE"], lt.permitted_uses, now, None, exclusive=False)
    availability = check_availability(active_scopes(db, asset.id), requested)
    if not availability.available:
        raise HTTPException(status.HTTP_409_CONFLICT, "These rights are no longer available for this media")

    creator = db.get(CreatorProfile, asset.creator_id)
    grant = RightsGrant(
        certificate_number=new_certificate_number(),
        asset_id=asset.id,
        license_type_id=lt.id,
        licensee_user_id=user.id,
        licensee_name=licensee_name or user.display_name,
        source=GrantSource.free_download,
        is_exclusive=False,
        territory=["WORLDWIDE"],
        permitted_uses=lt.permitted_uses,
        size_tier=listing.size_tier,
        starts_at=now,
        ends_at=None,
        price_cents=0,
        currency=listing.currency,
        terms_version=lt.terms_version,
        terms_snapshot={
            "license_code": lt.code,
            "license_name": lt.name,
            "summary": lt.summary,
            "terms_markdown": lt.terms_markdown,
            "requires_attribution": lt.requires_attribution,
            "asset_title": asset.title,
            "creator_display_name": creator.display_name if creator else "",
            "creator_handle": creator.handle if creator else "",
            "contributor_agreement_id": str(asset.contributor_agreement_id) if asset.contributor_agreement_id else None,
        },
    )
    db.add(grant)
    db.flush()
    ent = DownloadEntitlement(rights_grant_id=grant.id, user_id=user.id, asset_id=asset.id, max_downloads=10)
    db.add(ent)
    asset.download_count += 1
    audit.record(db, "license.free_issued", user.id, "rights_grant", grant.id, ip,
                 certificate=grant.certificate_number, asset_id=asset.id, license=lt.code)
    db.flush()
    return grant, ent


def download_link(ent: DownloadEntitlement) -> tuple[str, int]:
    seconds = get_settings().download_link_seconds
    return f"{get_settings().api_prefix}/downloads/{sign_download(ent.id, 'original')}", seconds


def grant_view(grant: RightsGrant) -> dict:
    snap = grant.terms_snapshot or {}
    return {
        "certificate_number": grant.certificate_number,
        "asset_id": grant.asset_id,
        "asset_title": snap.get("asset_title", ""),
        "license_code": grant.license_type.code,
        "license_name": grant.license_type.name,
        "licensee_name": grant.licensee_name,
        "is_exclusive": grant.is_exclusive,
        "territory": grant.territory,
        "permitted_uses": grant.permitted_uses,
        "starts_at": grant.starts_at,
        "ends_at": grant.ends_at,
        "price_cents": grant.price_cents,
        "currency": grant.currency,
        "terms_version": grant.terms_version,
        "status": grant.status.value,
        "issued_at": grant.issued_at,
        "creator_display_name": snap.get("creator_display_name", ""),
        "requires_attribution": bool(snap.get("requires_attribution")),
    }
