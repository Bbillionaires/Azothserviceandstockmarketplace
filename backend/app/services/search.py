"""Media search.

PostgreSQL uses full-text search (``websearch_to_tsquery`` against a GIN
index created in the initial migration). Other databases (SQLite in tests and
local development) fall back to term-by-term ``LIKE`` matching. Both paths
share the same filters and facets.

``interpret_query`` is a small deterministic parser that pulls structured
filters out of natural-language queries such as
"4K aerial footage of downtown Jacksonville at sunset". It is a placeholder
for the AI search module planned for Phase 5 and is not presented as AI.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from sqlalchemy import Select, and_, func, select
from sqlalchemy.orm import Session

from app.models import CreatorProfile, LicenseType, MediaAsset, MediaStatus, PriceListing

VIDEO_WORDS = {"footage", "video", "videos", "clip", "clips", "b-roll", "broll"}
PHOTO_WORDS = {"photo", "photos", "photograph", "photographs", "image", "images", "picture", "pictures"}
STOP_WORDS = {"a", "an", "the", "of", "in", "at", "on", "for", "with", "and", "to", "from", "by"}


@dataclass
class SearchParams:
    q: str = ""
    media_type: str | None = None
    category: str | None = None
    orientation: str | None = None
    resolution: str | None = None
    min_duration: float | None = None
    max_duration: float | None = None
    free_only: bool = False
    license_code: str | None = None
    country: str | None = None
    creator_handle: str | None = None
    has_model_release: bool | None = None
    min_price_cents: int | None = None
    max_price_cents: int | None = None
    sort: str = "relevance"  # relevance | newest | popular | price_low
    page: int = 1
    page_size: int = 24
    interpreted: dict = field(default_factory=dict)


def interpret_query(params: SearchParams) -> SearchParams:
    tokens = re.findall(r"[\w-]+", params.q.lower())
    remaining: list[str] = []
    for tok in tokens:
        if tok in ("8k", "4k", "hd") and not params.resolution:
            params.resolution = tok.upper()
            params.interpreted["resolution"] = params.resolution
        elif tok in VIDEO_WORDS and not params.media_type:
            params.media_type = "video"
            params.interpreted["media_type"] = "video"
        elif tok in PHOTO_WORDS and not params.media_type:
            params.media_type = "photo"
            params.interpreted["media_type"] = "photo"
        elif tok in ("vertical", "portrait", "horizontal", "landscape") and not params.orientation:
            params.orientation = "vertical" if tok in ("vertical", "portrait") else "horizontal"
            params.interpreted["orientation"] = params.orientation
        elif tok == "free" and not params.free_only:
            params.free_only = True
            params.interpreted["free_only"] = "true"
        elif tok not in STOP_WORDS:
            remaining.append(tok)
    params.interpreted["terms"] = " ".join(remaining) or None
    params.q = " ".join(remaining)
    return params


def _base_query(db: Session, p: SearchParams) -> Select:
    stmt = (
        select(MediaAsset, CreatorProfile)
        .join(CreatorProfile, CreatorProfile.id == MediaAsset.creator_id)
        .where(MediaAsset.status == MediaStatus.approved)
    )
    if p.q:
        if db.bind.dialect.name == "postgresql":
            stmt = stmt.where(
                func.to_tsvector("english", MediaAsset.search_text).op("@@")(
                    func.websearch_to_tsquery("english", p.q)
                )
            )
        else:
            for term in p.q.split():
                stmt = stmt.where(MediaAsset.search_text.like(f"%{term}%"))
    if p.media_type:
        stmt = stmt.where(MediaAsset.media_type == p.media_type)
    if p.category:
        stmt = stmt.where(MediaAsset.category == p.category)
    if p.orientation:
        stmt = stmt.where(MediaAsset.orientation == p.orientation)
    if p.resolution:
        order = ["SD", "HD", "4K", "8K"]
        if p.resolution in order:
            stmt = stmt.where(MediaAsset.resolution_label.in_(order[order.index(p.resolution):]))
    if p.min_duration is not None:
        stmt = stmt.where(MediaAsset.duration_seconds >= p.min_duration)
    if p.max_duration is not None:
        stmt = stmt.where(MediaAsset.duration_seconds <= p.max_duration)
    if p.free_only:
        stmt = stmt.where(MediaAsset.is_free.is_(True))
    if p.country:
        stmt = stmt.where(MediaAsset.location_country == p.country.upper())
    if p.creator_handle:
        stmt = stmt.where(CreatorProfile.handle == p.creator_handle.lower())
    if p.has_model_release is not None:
        stmt = stmt.where(MediaAsset.has_model_release.is_(p.has_model_release))
    price_filters = []
    if p.license_code:
        price_filters.append(LicenseType.code == p.license_code)
    if p.min_price_cents is not None:
        price_filters.append(PriceListing.price_cents >= p.min_price_cents)
    if p.max_price_cents is not None:
        price_filters.append(PriceListing.price_cents <= p.max_price_cents)
    if price_filters:
        sub = (
            select(PriceListing.asset_id)
            .join(LicenseType, LicenseType.id == PriceListing.license_type_id)
            .where(PriceListing.is_active, and_(*price_filters))
        )
        stmt = stmt.where(MediaAsset.id.in_(sub))
    return stmt


def search_media(db: Session, p: SearchParams) -> tuple[list[tuple[MediaAsset, CreatorProfile]], int, dict]:
    stmt = _base_query(db, p)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0

    if p.sort == "newest":
        stmt = stmt.order_by(MediaAsset.published_at.desc())
    elif p.sort == "popular" or (p.sort == "relevance" and not p.q):
        stmt = stmt.order_by((MediaAsset.download_count * 5 + MediaAsset.view_count).desc(), MediaAsset.published_at.desc())
    elif p.sort == "price_low":
        min_price = (
            select(func.min(PriceListing.price_cents))
            .where(PriceListing.asset_id == MediaAsset.id, PriceListing.is_active)
            .scalar_subquery()
        )
        stmt = stmt.order_by(MediaAsset.is_free.desc(), min_price.asc())
    elif db.bind.dialect.name == "postgresql" and p.q:
        rank = func.ts_rank(func.to_tsvector("english", MediaAsset.search_text), func.websearch_to_tsquery("english", p.q))
        stmt = stmt.order_by(rank.desc(), MediaAsset.download_count.desc())
    else:
        stmt = stmt.order_by(MediaAsset.download_count.desc(), MediaAsset.published_at.desc())

    rows = db.execute(stmt.offset((p.page - 1) * p.page_size).limit(p.page_size)).all()
    return [(a, c) for a, c in rows], total, _facets(db, p)


def _facets(db: Session, p: SearchParams) -> dict:
    sub = _base_query(db, p).with_only_columns(MediaAsset.id).subquery()
    facets = {}
    for name, col in (
        ("media_type", MediaAsset.media_type),
        ("category", MediaAsset.category),
        ("orientation", MediaAsset.orientation),
        ("resolution", MediaAsset.resolution_label),
    ):
        rows = db.execute(
            select(col, func.count()).where(MediaAsset.id.in_(select(sub.c.id))).group_by(col).order_by(func.count().desc())
        ).all()
        facets[name] = [
            {"value": v.value if hasattr(v, "value") else v, "count": c} for v, c in rows if v is not None
        ]
    return facets

