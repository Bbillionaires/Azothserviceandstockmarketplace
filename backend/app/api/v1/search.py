from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.media import SearchOut
from app.services import media_service as ms
from app.services.search import SearchParams, interpret_query, search_media

router = APIRouter(prefix="/search", tags=["search"])


@router.get("/media", response_model=SearchOut)
def search(
    q: str = Query("", max_length=200),
    media_type: str | None = Query(None, alias="type", pattern="^(photo|video)$"),
    category: str | None = Query(None, max_length=40),
    orientation: str | None = Query(None, pattern="^(horizontal|vertical|square)$"),
    resolution: str | None = Query(None, pattern="^(SD|HD|4K|8K)$"),
    min_duration: float | None = Query(None, ge=0),
    max_duration: float | None = Query(None, ge=0),
    free: bool = False,
    license: str | None = Query(None, max_length=40),
    country: str | None = Query(None, min_length=2, max_length=2),
    creator: str | None = Query(None, max_length=40),
    model_release: bool | None = None,
    min_price: int | None = Query(None, ge=0, description="cents"),
    max_price: int | None = Query(None, ge=0, description="cents"),
    sort: str = Query("relevance", pattern="^(relevance|newest|popular|price_low)$"),
    page: int = Query(1, ge=1, le=500),
    page_size: int = Query(24, ge=1, le=60),
    db: Session = Depends(get_db),
):
    params = interpret_query(SearchParams(
        q=q, media_type=media_type, category=category, orientation=orientation, resolution=resolution,
        min_duration=min_duration, max_duration=max_duration, free_only=free, license_code=license,
        country=country, creator_handle=creator, has_model_release=model_release, min_price_cents=min_price,
        max_price_cents=max_price, sort=sort, page=page, page_size=page_size,
    ))
    rows, total, facets = search_media(db, params)
    prices = ms.prices_for(db, [a.id for a, _ in rows])
    return {
        "items": [ms.to_card(a, c, prices.get(a.id, [])) for a, c in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
        "facets": facets,
        "interpreted": {k: (str(v) if v is not None else None) for k, v in params.interpreted.items()},
    }
