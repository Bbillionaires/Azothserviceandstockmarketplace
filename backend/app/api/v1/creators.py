"""Creator storefronts and creator discovery."""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import String, cast, func, or_, select
from sqlalchemy.orm import Session

from app.api.v1.auth import grant_role
from app.core.database import get_db
from app.core.deps import current_user, verified_user
from app.models import CreatorProfile, Follow, MediaAsset, MediaStatus, RoleCode, User
from app.models.creator import PROFESSIONAL_CATEGORIES
from app.schemas.common import Message, Page
from app.schemas.creator import CreatorCreate, CreatorOut, CreatorStats, CreatorUpdate
from app.services import audit

router = APIRouter(prefix="/creators", tags=["creators"])


def my_profile(db: Session, user: User) -> CreatorProfile:
    profile = db.scalar(select(CreatorProfile).where(CreatorProfile.user_id == user.id))
    if not profile:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Create your storefront first")
    return profile


@router.post("", response_model=CreatorOut, status_code=201)
def create_storefront(body: CreatorCreate, user: User = Depends(verified_user), db: Session = Depends(get_db)):
    if db.scalar(select(CreatorProfile.id).where(CreatorProfile.user_id == user.id)):
        raise HTTPException(status.HTTP_409_CONFLICT, "You already have a storefront")
    if db.scalar(select(CreatorProfile.id).where(CreatorProfile.handle == body.handle)):
        raise HTTPException(status.HTTP_409_CONFLICT, "That handle is taken")
    profile = CreatorProfile(user_id=user.id, **body.model_dump())
    db.add(profile)
    grant_role(db, user, RoleCode.creator)
    db.flush()
    audit.record(db, "creator.storefront_created", user.id, "creator_profile", profile.id, handle=profile.handle)
    db.commit()
    return profile


@router.get("/me", response_model=CreatorOut)
def get_mine(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return my_profile(db, user)


@router.patch("/me", response_model=CreatorOut)
def update_mine(body: CreatorUpdate, user: User = Depends(current_user), db: Session = Depends(get_db)):
    profile = my_profile(db, user)
    for key, value in body.model_dump(exclude_unset=True).items():
        if key == "display_name" and value is None:
            continue
        setattr(profile, key, value)
    db.commit()
    return profile


@router.get("", response_model=Page[CreatorOut])
def discover(
    q: str | None = Query(None, max_length=100),
    category: str | None = None,
    city: str | None = None,
    country: str | None = Query(None, min_length=2, max_length=2),
    remote: bool | None = None,
    travel: bool | None = None,
    emerging: bool | None = None,
    featured: bool | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(24, ge=1, le=100),
    db: Session = Depends(get_db),
):
    stmt = select(CreatorProfile)
    if q:
        like = f"%{q.lower()}%"
        stmt = stmt.where(or_(func.lower(CreatorProfile.display_name).like(like),
                              func.lower(CreatorProfile.headline).like(like),
                              CreatorProfile.handle.like(like)))
    if category:
        if category not in PROFESSIONAL_CATEGORIES:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Unknown category")
        # JSON list membership; portable across PostgreSQL and SQLite.
        stmt = stmt.where(cast(CreatorProfile.categories, String).like(f'%"{category}"%'))
    if city:
        stmt = stmt.where(func.lower(CreatorProfile.city) == city.lower())
    if country:
        stmt = stmt.where(CreatorProfile.country_code == country.upper())
    if remote is not None:
        stmt = stmt.where(CreatorProfile.remote_available.is_(remote))
    if travel is not None:
        stmt = stmt.where(CreatorProfile.travel_available.is_(travel))
    if emerging is not None:
        stmt = stmt.where(CreatorProfile.is_emerging_talent.is_(emerging))
    if featured is not None:
        stmt = stmt.where(CreatorProfile.is_featured.is_(featured))
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    items = db.scalars(
        stmt.order_by(CreatorProfile.is_featured.desc(), CreatorProfile.follower_count.desc(), CreatorProfile.created_at)
        .offset((page - 1) * page_size).limit(page_size)
    ).all()
    return Page[CreatorOut](items=items, total=total, page=page, page_size=page_size)


@router.get("/{handle}", response_model=CreatorOut)
def get_storefront(handle: str, db: Session = Depends(get_db)):
    profile = db.scalar(select(CreatorProfile).where(CreatorProfile.handle == handle.lower()))
    if not profile:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Creator not found")
    return profile


@router.get("/{handle}/stats", response_model=CreatorStats)
def storefront_stats(handle: str, db: Session = Depends(get_db)):
    profile = get_storefront(handle, db)
    row = db.execute(
        select(func.count(), func.coalesce(func.sum(MediaAsset.download_count), 0),
               func.coalesce(func.sum(MediaAsset.view_count), 0))
        .where(MediaAsset.creator_id == profile.id, MediaAsset.status == MediaStatus.approved)
    ).one()
    return CreatorStats(approved_media=row[0], total_downloads=row[1], total_views=row[2])


@router.post("/{handle}/follow", response_model=Message)
def follow(handle: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    profile = get_storefront(handle, db)
    if profile.user_id == user.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "You cannot follow yourself")
    if not db.scalar(select(Follow.id).where(Follow.user_id == user.id, Follow.creator_id == profile.id)):
        db.add(Follow(user_id=user.id, creator_id=profile.id))
        profile.follower_count += 1
        db.commit()
    return Message(detail="Following")


@router.delete("/{handle}/follow", response_model=Message)
def unfollow(handle: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    profile = get_storefront(handle, db)
    row = db.scalar(select(Follow).where(Follow.user_id == user.id, Follow.creator_id == profile.id))
    if row:
        db.delete(row)
        profile.follower_count = max(0, profile.follower_count - 1)
        db.commit()
    return Message(detail="Unfollowed")
