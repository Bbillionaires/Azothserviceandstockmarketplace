"""Payment provider adapters (Stripe Connect, and a fake for dev/tests)."""

from functools import lru_cache

from app.core.config import get_settings
from app.services.payments.base import (
    AccountState,
    CheckoutItem,
    CheckoutSession,
    PaymentDetails,
    PaymentProvider,
    PaymentProviderError,
    ProviderEvent,
)


@lru_cache
def get_provider() -> PaymentProvider:
    settings = get_settings()
    if settings.payment_provider == "stripe":
        from app.services.payments.stripe_provider import StripeProvider

        return StripeProvider(settings.stripe_secret_key or "", settings.stripe_webhook_secret or "",
                              settings.stripe_tax_enabled)
    from app.services.payments.fake import FakeProvider

    return FakeProvider()


__all__ = [
    "AccountState", "CheckoutItem", "CheckoutSession", "PaymentDetails", "PaymentProvider",
    "PaymentProviderError", "ProviderEvent", "get_provider",
]
