"""Public configuration consumed by the frontend: branding, flags, catalogs."""

from fastapi import APIRouter

from app.core.config import get_settings
from app.models.creator import PROFESSIONAL_CATEGORIES
from app.models.media import MEDIA_CATEGORIES

router = APIRouter(tags=["config"])


@router.get("/config/public")
def public_config():
    s = get_settings()
    return {
        "brand": {
            "name": s.brand_name,
            "tagline": s.brand_tagline,
            "domain": s.brand_domain,
            "logo_url": s.brand_logo_url,
            "primary_color": s.brand_primary_color,
            "support_email": s.brand_support_email,
            "parent_company": s.parent_company,
            "technology_partner": s.technology_partner,
        },
        "features": {
            "paid_licensing": s.feature_paid_licensing,
            "exclusive_licensing": s.feature_exclusive_licensing,
        },
        "media_categories": MEDIA_CATEGORIES,
        "professional_categories": PROFESSIONAL_CATEGORIES,
    }
