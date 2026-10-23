"""Idempotent seed of reference data: roles, license catalog, the initial
revenue-share rule versions and DRAFT contributor agreement templates.

Agreement texts seeded here are placeholders marked as drafts. They are not
legal documents and must be replaced with counsel-reviewed text, then marked
approved through the admin API, before production use.
"""

import hashlib

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    AgreementTemplate,
    LegalReviewStatus,
    LicenseType,
    RevenueModel,
    RevenueShareRule,
    Role,
    RoleCode,
)

ROLES = {
    RoleCode.buyer: ("Buyer", "Browse, download and license media"),
    RoleCode.creator: ("Creator", "Operate a storefront and upload media"),
    RoleCode.rights_owner: ("Rights owner", "Holds copyright in listed media"),
    RoleCode.affiliate: ("Affiliate", "Refers creators and customers"),
    RoleCode.org_admin: ("Organization admin", "Manages an organization account"),
    RoleCode.moderator: ("Moderator", "Reviews media, complaints and appeals"),
    RoleCode.finance_admin: ("Financial administrator", "Manages commission rules, payouts, reconciliation"),
    RoleCode.admin: ("Administrator", "Full platform administration"),
}

TERMS_VERSION = "2026.1-draft"

LICENSE_TYPES = [
    # code, name, free, exclusive, commercial, editorial, attribution, uses, summary
    ("free_personal", "Free · Personal use", True, False, False, True, False,
     ["personal"], "Personal, non-commercial projects. No resale or redistribution of the file."),
    ("free_attribution", "Free · Attribution required", True, False, True, True, True,
     ["personal", "editorial", "commercial_digital"],
     "Personal and commercial digital use with visible credit to the creator."),
    ("free_commercial", "Free · Commercial use", True, False, True, True, False,
     ["personal", "editorial", "commercial_digital", "commercial_print"],
     "Personal and commercial use without attribution. Creator has expressly authorized free distribution."),
    ("personal", "Personal", False, False, False, True, False, ["personal"],
     "Personal, non-commercial use."),
    ("editorial", "Editorial", False, False, False, True, False, ["editorial"],
     "News, education and commentary. Not for advertising or promotion."),
    ("standard_commercial", "Standard commercial", False, False, True, True, False,
     ["personal", "editorial", "commercial_digital", "commercial_print"],
     "Marketing, web, social and print up to standard reproduction limits."),
    ("extended_commercial", "Extended commercial", False, False, True, True, False,
     ["personal", "editorial", "commercial_digital", "commercial_print", "broadcast", "merchandise"],
     "Broadcast, merchandise and unlimited reproduction."),
    ("exclusive", "Exclusive", False, True, True, True, False, ["ALL"],
     "Exclusive rights for a defined territory, use and term under a signed agreement."),
    ("negotiated", "Negotiated", False, False, True, True, False, [],
     "Custom terms agreed directly between buyer and rights owner."),
]

# Proposed commercial arrangements from the business plan. Subject to legal review.
RULES = [
    ("model_a_nonexclusive", RevenueModel.nonexclusive, 5000, None, 1000,
     "Model A: perpetual nonexclusive; 50/50 split of net licensing revenue."),
    ("model_b_exclusive", RevenueModel.exclusive, 5000, 6500, 1000,
     "Model B: 65/35 on the initial exclusive transaction; proposed 50/50 on subsequent "
     "qualifying transactions where the signed contract provides for it."),
    ("model_c_free", RevenueModel.free, 0, None, 0, "Model C: free media; no royalty on zero-revenue downloads."),
]

# Custom production commission. 85% to the creator is a placeholder business
# decision; finance admins change it by creating a new rule version.
SERVICES_RULE = ("services_commission", RevenueModel.service, 8500, 1000,
                 "Custom production and gallery sales: creator receives 85%; the platform pays payment "
                 "processing fees from its 15% commission, and pays 10% of that commission to the "
                 "client's referrer during the attribution window.")
SERVICES_RULE_V1_NOTES = ("Custom production: creator receives 85% of each released milestone; the platform pays "
                          "payment processing fees from its 15% commission.")

DRAFT_BANNER = (
    "> **DRAFT — NOT LEGALLY REVIEWED.** Placeholder text for development only. "
    "Replace with counsel-approved terms before activation.\n\n"
)

TEMPLATES = {
    "model_a_nonexclusive": (
        "Perpetual Nonexclusive Contributor Agreement",
        ["personal", "editorial", "commercial_digital", "commercial_print", "broadcast", "merchandise"],
        "Creator may withdraw media prospectively; licenses already granted to customers survive withdrawal.",
        "1. You keep copyright ownership.\n2. You grant the platform a perpetual, nonexclusive, worldwide "
        "license to market and sublicense the media for the permitted uses.\n3. You may license the media "
        "elsewhere.\n4. Net licensing revenue is shared 50% to you and 50% to the platform.\n",
    ),
    "model_b_exclusive": (
        "Exclusive Licensing Agreement",
        ["ALL"],
        "Withdrawal and termination as stated in the separately executed agreement, subject to statutory "
        "termination rights.",
        "1. Exclusive licensing rights for the defined territory, uses and term. Copyright ownership does "
        "not transfer.\n2. 65% to you on the initial exclusive transaction; continuing royalties as the "
        "signed contract provides.\n3. Requires separate electronic signature.\n",
    ),
    "model_c_free": (
        "Free Distribution Authorization",
        ["personal", "editorial", "commercial_digital", "commercial_print"],
        "Creator may stop offering media for free at any time; downloads already made keep their license.",
        "1. You expressly authorize free distribution under the license type you choose.\n2. Free does not "
        "mean public domain.\n3. No royalty is paid on zero-revenue downloads.\n",
    ),
}


def seed_reference_data(db: Session) -> None:
    existing_roles = {r.code for r in db.scalars(select(Role))}
    for code, (name, desc) in ROLES.items():
        if code.value not in existing_roles:
            db.add(Role(code=code.value, name=name, description=desc))

    existing_lt = {lt.code for lt in db.scalars(select(LicenseType))}
    for i, (code, name, free, excl, comm, edit, attr, uses, summary) in enumerate(LICENSE_TYPES):
        if code not in existing_lt:
            db.add(LicenseType(
                code=code, name=name, summary=summary, is_free=free, is_exclusive=excl,
                allows_commercial_use=comm, allows_editorial_use=edit, requires_attribution=attr,
                permitted_uses=uses, terms_version=TERMS_VERSION, sort_order=i,
                terms_markdown=DRAFT_BANNER + summary,
            ))
    db.flush()

    for code, model, creator_bps, initial_bps, aff_bps, notes in RULES:
        rule = db.scalar(select(RevenueShareRule).where(RevenueShareRule.code == code))
        if not rule:
            rule = RevenueShareRule(
                code=code, version=1, revenue_model=model, creator_bps=creator_bps,
                initial_exclusive_creator_bps=initial_bps, affiliate_bps_of_platform=aff_bps,
                net_revenue_deductions=["taxes_collected", "payment_processing_fees", "partner_distribution_fees"],
                notes=notes,
            )
            db.add(rule)
            db.flush()
        if not db.scalar(select(AgreementTemplate).where(AgreementTemplate.code == code)):
            title, uses, withdrawal, body = TEMPLATES[code]
            text = DRAFT_BANNER + body
            db.add(AgreementTemplate(
                code=code, version=1, title=title, revenue_model=model, revenue_share_rule_id=rule.id,
                body_markdown=text, body_sha256=hashlib.sha256(text.encode()).hexdigest(),
                territory=["WORLDWIDE"], permitted_uses=uses, sublicensing_allowed=True,
                duration="perpetual", withdrawal_terms=withdrawal,
                legal_review_status=LegalReviewStatus.draft,
            ))
    db.commit()
    code, model, creator_bps, aff_bps, notes = SERVICES_RULE
    latest = db.scalar(select(RevenueShareRule).where(RevenueShareRule.code == code)
                       .order_by(RevenueShareRule.version.desc()))
    # New installs get the current rule. An install still on the untouched
    # Phase 3 seed (no referral commission) gets it as version 2; a version a
    # finance admin created is left alone. Projects keep their snapshotted rule.
    untouched_v1 = (latest is not None and latest.version == 1 and latest.affiliate_bps_of_platform == 0
                    and latest.created_by is None and latest.notes == SERVICES_RULE_V1_NOTES)
    if latest is None or untouched_v1:
        db.add(RevenueShareRule(code=code, version=2 if latest else 1, revenue_model=model, creator_bps=creator_bps,
                                initial_exclusive_creator_bps=None, affiliate_bps_of_platform=aff_bps,
                                net_revenue_deductions=[], notes=notes))
        db.commit()
