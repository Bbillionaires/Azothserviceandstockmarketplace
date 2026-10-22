"""Import every model so Alembic autogenerate and ``Base.metadata`` see them."""

from app.models.base import Base
from app.models.commerce import (
    AccountType,
    Earning,
    EarningKind,
    EarningStatus,
    FinancialEvent,
    JournalKind,
    LedgerAccount,
    LedgerEntry,
    LedgerJournal,
    Order,
    OrderLine,
    OrderLineStatus,
    OrderStatus,
    Payout,
    PayoutAccount,
    PayoutAccountStatus,
    PayoutStatus,
    ReconciliationRun,
    Referral,
    ReferralCode,
    ReferralStatus,
    Refund,
    RefundReason,
    RoyaltyAllocation,
)
from app.models.creator import CreatorProfile, Follow, VerificationStatus
from app.models.licensing import (
    AgreementStatus,
    AgreementTemplate,
    ContributorAgreement,
    DownloadEntitlement,
    GrantSource,
    GrantStatus,
    LegalReviewStatus,
    LicenseType,
    PriceListing,
    RevenueModel,
    RevenueShareRule,
    RightsGrant,
    SignatureMethod,
)
from app.models.media import (
    Collection,
    CollectionItem,
    CopyrightDeclaration,
    Favorite,
    FileKind,
    MediaAsset,
    MediaFile,
    MediaRelease,
    MediaStatus,
    MediaType,
    Orientation,
    ReleaseType,
    ScanStatus,
)
from app.models.moderation import (
    AppealStatus,
    AuditLog,
    ComplaintStatus,
    ContentAppeal,
    CopyrightComplaint,
    ModerationAction,
    ModerationDecision,
)
from app.models.user import (
    EmailToken,
    EmailTokenPurpose,
    Organization,
    OrganizationMember,
    OrganizationType,
    OrgMemberRole,
    Role,
    RoleCode,
    User,
    UserRole,
    UserStatus,
)


