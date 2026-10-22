"""Buyer favorites and saved collections."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import current_user
from app.models import Collection, CollectionItem, CreatorProfile, Favorite, MediaAsset, MediaStatus, User
from app.schemas.common import Message
from app.schemas.media import MediaCard
from app.services import media_service as ms

router = APIRouter(tags=["library"])


class CollectionIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    is_private: bool = True


class CollectionOut(BaseModel):
    id: uuid.UUID
    name: str
    is_private: bool
    item_count: int


def _cards(db: Session, asset_ids: list[uuid.UUID]) -> list[dict]:
    if not asset_ids:
        return []
    rows = db.execute(select(MediaAsset, CreatorProfile).join(CreatorProfile, CreatorProfile.id == MediaAsset.creator_id)
                      .where(MediaAsset.id.in_(asset_ids), MediaAsset.status == MediaStatus.approved)).all()
    prices = ms.prices_for(db, [a.id for a, _ in rows])
    by_id = {a.id: ms.to_card(a, c, prices.get(a.id, [])) for a, c in rows}
    return [by_id[i] for i in asset_ids if i in by_id]


def _approved(db: Session, asset_id: uuid.UUID) -> MediaAsset:
    asset = db.get(MediaAsset, asset_id)
    if not asset or asset.status is not MediaStatus.approved:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Media not found")
    return asset


@router.get("/favorites", response_model=list[MediaCard])
def list_favorites(user: User = Depends(current_user), db: Session = Depends(get_db)):
    ids = list(db.scalars(select(Favorite.asset_id).where(Favorite.user_id == user.id).order_by(Favorite.created_at.desc())))
    return _cards(db, ids)


@router.put("/favorites/{asset_id}", response_model=Message)
def add_favorite(asset_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)):
    _approved(db, asset_id)
    if not db.scalar(select(Favorite.id).where(Favorite.user_id == user.id, Favorite.asset_id == asset_id)):
        db.add(Favorite(user_id=user.id, asset_id=asset_id))
        db.commit()
    return Message(detail="Saved to favorites")


@router.delete("/favorites/{asset_id}", response_model=Message)
def remove_favorite(asset_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)):
    fav = db.scalar(select(Favorite).where(Favorite.user_id == user.id, Favorite.asset_id == asset_id))
    if fav:
        db.delete(fav)
        db.commit()
    return Message(detail="Removed from favorites")


@router.get("/collections", response_model=list[CollectionOut])
def list_collections(user: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = db.execute(
        select(Collection, func.count(CollectionItem.id))
        .outerjoin(CollectionItem, CollectionItem.collection_id == Collection.id)
        .where(Collection.owner_id == user.id).group_by(Collection.id).order_by(Collection.created_at.desc())
    ).all()
    return [CollectionOut(id=c.id, name=c.name, is_private=c.is_private, item_count=n) for c, n in rows]


@router.post("/collections", response_model=CollectionOut, status_code=201)
def create_collection(body: CollectionIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    c = Collection(owner_id=user.id, name=body.name.strip(), is_private=body.is_private)
    db.add(c)
    db.commit()
    return CollectionOut(id=c.id, name=c.name, is_private=c.is_private, item_count=0)


def _own_collection(db: Session, user: User, collection_id: uuid.UUID) -> Collection:
    c = db.get(Collection, collection_id)
    if not c or c.owner_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Collection not found")
    return c


@router.get("/collections/{collection_id}", response_model=list[MediaCard])
def collection_items(collection_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)):
    _own_collection(db, user, collection_id)
    ids = list(db.scalars(select(CollectionItem.asset_id).where(CollectionItem.collection_id == collection_id)
                          .order_by(CollectionItem.added_at.desc())))
    return _cards(db, ids)


@router.put("/collections/{collection_id}/items/{asset_id}", response_model=Message)
def add_item(collection_id: uuid.UUID, asset_id: uuid.UUID, user: User = Depends(current_user),
             db: Session = Depends(get_db)):
    _own_collection(db, user, collection_id)
    _approved(db, asset_id)
    if not db.scalar(select(CollectionItem.id).where(CollectionItem.collection_id == collection_id,
                                                     CollectionItem.asset_id == asset_id)):
        db.add(CollectionItem(collection_id=collection_id, asset_id=asset_id))
        db.commit()
    return Message(detail="Added to collection")


@router.delete("/collections/{collection_id}/items/{asset_id}", response_model=Message)
def remove_item(collection_id: uuid.UUID, asset_id: uuid.UUID, user: User = Depends(current_user),
                db: Session = Depends(get_db)):
    _own_collection(db, user, collection_id)
    item = db.scalar(select(CollectionItem).where(CollectionItem.collection_id == collection_id,
                                                  CollectionItem.asset_id == asset_id))
    if item:
        db.delete(item)
        db.commit()
    return Message(detail="Removed from collection")


@router.delete("/collections/{collection_id}", response_model=Message)
def delete_collection(collection_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)):
    c = _own_collection(db, user, collection_id)
    db.delete(c)
    db.commit()
    return Message(detail="Collection deleted")
