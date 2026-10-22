"""Phase 3 custom production: requests, invitations, packages, proposals,
projects, milestones, deliverables, revisions, messaging, notifications,
reviews, project disputes, client galleries; milestone links on orders,
earnings and refunds; new enum values.

Downgrade note: restoring the old CHECK constraints fails while Phase 3 rows exist
(e.g. the ``services_commission`` rule or service earnings). Remove that data first.

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-22 20:26:41.895943
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = '0003'
down_revision: str | None = '0002'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Enum columns are VARCHAR + CHECK constraints; new members need the CHECK rewritten.
# (old values, new values) per column.
_REVENUE = (["nonexclusive", "exclusive", "free"], ["nonexclusive", "exclusive", "free", "service"])
ENUM_CHANGES = [
    ("revenue_share_rules", "revenue_model", "revenue_model", _REVENUE),
    ("agreement_templates", "revenue_model", "agreement_revenue_model", _REVENUE),
    ("earnings", "kind", "earning_kind",
     (["stock_license", "affiliate_commission"], ["stock_license", "affiliate_commission", "service_milestone"])),
    ("ledger_journals", "kind", "journal_kind",
     (["sale", "refund", "dispute", "dispute_reinstated", "payout", "payout_reversal", "adjustment"],
      ["sale", "refund", "dispute", "dispute_reinstated", "payout", "payout_reversal", "adjustment",
       "service_funding", "service_release", "service_refund"])),
    ("refunds", "reason", "refund_reason",
     (["requested_by_customer", "duplicate", "fraudulent", "rights_issue", "chargeback", "other"],
      ["requested_by_customer", "duplicate", "fraudulent", "rights_issue", "chargeback", "project_canceled",
       "dispute_resolution", "other"])),
]


def _replace_enum_check(table: str, column: str, name: str, values: list[str]) -> None:
    constraint = f"ck_{table}_{name}"
    with op.batch_alter_table(table, recreate="always" if op.get_bind().dialect.name == "sqlite" else "auto") as b:
        b.drop_constraint(op.f(constraint), type_="check")
        b.create_check_constraint(op.f(constraint), sa.column(column).in_(values))


def upgrade() -> None:
    op.create_table('conversations',
    sa.Column('kind', sa.Enum('direct', 'request', 'project', name='conversation_kind', native_enum=False, create_constraint=True, length=40), nullable=False),
    sa.Column('subject_id', sa.Uuid(), nullable=True),
    sa.Column('pair_key', sa.String(length=80), nullable=False),
    sa.Column('title', sa.String(length=200), nullable=False),
    sa.Column('last_message_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_conversations')),
    sa.UniqueConstraint('kind', 'subject_id', 'pair_key', name=op.f('uq_conversations_kind_subject_id_pair_key'))
    )
    op.create_index(op.f('ix_conversations_last_message_at'), 'conversations', ['last_message_at'], unique=False)
    op.create_table('conversation_participants',
    sa.Column('conversation_id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('last_read_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['conversation_id'], ['conversations.id'], name=op.f('fk_conversation_participants_conversation_id_conversations'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_conversation_participants_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_conversation_participants')),
    sa.UniqueConstraint('conversation_id', 'user_id', name=op.f('uq_conversation_participants_conversation_id_user_id'))
    )
    op.create_index(op.f('ix_conversation_participants_conversation_id'), 'conversation_participants', ['conversation_id'], unique=False)
    op.create_index(op.f('ix_conversation_participants_user_id'), 'conversation_participants', ['user_id'], unique=False)
    op.create_table('messages',
    sa.Column('conversation_id', sa.Uuid(), nullable=False),
    sa.Column('sender_id', sa.Uuid(), nullable=True),
    sa.Column('body', sa.Text(), nullable=False),
    sa.Column('is_system', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['conversation_id'], ['conversations.id'], name=op.f('fk_messages_conversation_id_conversations'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['sender_id'], ['users.id'], name=op.f('fk_messages_sender_id_users'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_messages'))
    )
    op.create_index('ix_messages_conversation_created', 'messages', ['conversation_id', 'created_at'], unique=False)
    op.create_table('notifications',
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('kind', sa.String(length=60), nullable=False),
    sa.Column('title', sa.String(length=200), nullable=False),
    sa.Column('body', sa.Text(), nullable=False),
    sa.Column('link', sa.String(length=300), nullable=False),
    sa.Column('read_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_notifications_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_notifications'))
    )
    op.create_index(op.f('ix_notifications_created_at'), 'notifications', ['created_at'], unique=False)
    op.create_index('ix_notifications_user_read', 'notifications', ['user_id', 'read_at'], unique=False)
    op.create_table('project_requests',
    sa.Column('client_user_id', sa.Uuid(), nullable=False),
    sa.Column('kind', sa.Enum('custom_project', 'shot_request', name='request_kind', native_enum=False, create_constraint=True, length=40), nullable=False),
    sa.Column('title', sa.String(length=200), nullable=False),
    sa.Column('description', sa.Text(), nullable=False),
    sa.Column('category', sa.String(length=40), nullable=False),
    sa.Column('deliverables', sa.Text(), nullable=False),
    sa.Column('reference_urls', sa.JSON(), nullable=False),
    sa.Column('location_city', sa.String(length=120), nullable=True),
    sa.Column('location_region', sa.String(length=120), nullable=True),
    sa.Column('location_country', sa.String(length=2), nullable=True),
    sa.Column('remote_ok', sa.Boolean(), nullable=False),
    sa.Column('budget_min_cents', sa.Integer(), nullable=True),
    sa.Column('budget_max_cents', sa.Integer(), nullable=True),
    sa.Column('currency', sa.String(length=3), nullable=False),
    sa.Column('deadline', sa.Date(), nullable=True),
    sa.Column('rights_preference', sa.Enum('exclusive', 'nonexclusive', 'custom', name='rights_preference', native_enum=False, create_constraint=True, length=40), nullable=False),
    sa.Column('visibility', sa.Enum('public', 'invite_only', name='request_visibility', native_enum=False, create_constraint=True, length=40), nullable=False),
    sa.Column('status', sa.Enum('open', 'awarded', 'closed', 'canceled', name='request_status', native_enum=False, create_constraint=True, length=40), nullable=False),
    sa.Column('proposal_count', sa.Integer(), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint('budget_max_cents IS NULL OR budget_min_cents IS NULL OR budget_max_cents >= budget_min_cents', name=op.f('ck_project_requests_budget_range')),
    sa.CheckConstraint('budget_min_cents IS NULL OR budget_min_cents >= 0', name=op.f('ck_project_requests_budget_min_non_negative')),
    sa.ForeignKeyConstraint(['client_user_id'], ['users.id'], name=op.f('fk_project_requests_client_user_id_users'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_project_requests'))
    )
    op.create_index(op.f('ix_project_requests_client_user_id'), 'project_requests', ['client_user_id'], unique=False)
    op.create_index(op.f('ix_project_requests_deadline'), 'project_requests', ['deadline'], unique=False)
    op.create_index(op.f('ix_project_requests_location_city'), 'project_requests', ['location_city'], unique=False)
    op.create_index(op.f('ix_project_requests_location_country'), 'project_requests', ['location_country'], unique=False)
    op.create_index('ix_project_requests_status_category', 'project_requests', ['status', 'category'], unique=False)
    op.create_table('proposals',
    sa.Column('request_id', sa.Uuid(), nullable=False),
    sa.Column('creator_id', sa.Uuid(), nullable=False),
    sa.Column('cover_letter', sa.Text(), nullable=False),
    sa.Column('total_cents', sa.Integer(), nullable=False),
    sa.Column('currency', sa.String(length=3), nullable=False),
    sa.Column('milestones', sa.JSON(), nullable=False),
    sa.Column('delivery_days', sa.Integer(), nullable=False),
    sa.Column('revisions_included', sa.Integer(), nullable=False),
    sa.Column('rights_type', sa.Enum('exclusive', 'nonexclusive', 'custom', name='proposal_rights_type', native_enum=False, create_constraint=True, length=40), nullable=False),
    sa.Column('rights_terms', sa.Text(), nullable=False),
    sa.Column('status', sa.Enum('submitted', 'withdrawn', 'accepted', 'declined', name='proposal_status', native_enum=False, create_constraint=True, length=40), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint('total_cents >= 100', name=op.f('ck_proposals_total_minimum')),
    sa.ForeignKeyConstraint(['creator_id'], ['creator_profiles.id'], name=op.f('fk_proposals_creator_id_creator_profiles'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['request_id'], ['project_requests.id'], name=op.f('fk_proposals_request_id_project_requests'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_proposals')),
    sa.UniqueConstraint('request_id', 'creator_id', name=op.f('uq_proposals_request_id_creator_id'))
    )
    op.create_index(op.f('ix_proposals_creator_id'), 'proposals', ['creator_id'], unique=False)
    op.create_index(op.f('ix_proposals_request_id'), 'proposals', ['request_id'], unique=False)
    op.create_table('request_invitations',
    sa.Column('request_id', sa.Uuid(), nullable=False),
    sa.Column('creator_id', sa.Uuid(), nullable=False),
    sa.Column('message', sa.Text(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['creator_id'], ['creator_profiles.id'], name=op.f('fk_request_invitations_creator_id_creator_profiles'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['request_id'], ['project_requests.id'], name=op.f('fk_request_invitations_request_id_project_requests'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_request_invitations')),
    sa.UniqueConstraint('request_id', 'creator_id', name=op.f('uq_request_invitations_request_id_creator_id'))
    )
    op.create_index(op.f('ix_request_invitations_creator_id'), 'request_invitations', ['creator_id'], unique=False)
    op.create_index(op.f('ix_request_invitations_request_id'), 'request_invitations', ['request_id'], unique=False)
    op.create_table('service_packages',
    sa.Column('creator_id', sa.Uuid(), nullable=False),
    sa.Column('title', sa.String(length=200), nullable=False),
    sa.Column('description', sa.Text(), nullable=False),
    sa.Column('category', sa.String(length=40), nullable=False),
    sa.Column('deliverables', sa.Text(), nullable=False),
    sa.Column('price_cents', sa.Integer(), nullable=False),
    sa.Column('currency', sa.String(length=3), nullable=False),
    sa.Column('delivery_days', sa.Integer(), nullable=False),
    sa.Column('revisions_included', sa.Integer(), nullable=False),
    sa.Column('rights_type', sa.Enum('exclusive', 'nonexclusive', 'custom', name='package_rights_type', native_enum=False, create_constraint=True, length=40), nullable=False),
    sa.Column('rights_terms', sa.Text(), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint('price_cents >= 100', name=op.f('ck_service_packages_price_minimum')),
    sa.ForeignKeyConstraint(['creator_id'], ['creator_profiles.id'], name=op.f('fk_service_packages_creator_id_creator_profiles'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_service_packages'))
    )
    op.create_index(op.f('ix_service_packages_category'), 'service_packages', ['category'], unique=False)
    op.create_index(op.f('ix_service_packages_creator_id'), 'service_packages', ['creator_id'], unique=False)
    op.create_table('projects',
    sa.Column('client_user_id', sa.Uuid(), nullable=False),
    sa.Column('creator_id', sa.Uuid(), nullable=False),
    sa.Column('request_id', sa.Uuid(), nullable=True),
    sa.Column('proposal_id', sa.Uuid(), nullable=True),
    sa.Column('package_id', sa.Uuid(), nullable=True),
    sa.Column('title', sa.String(length=200), nullable=False),
    sa.Column('description', sa.Text(), nullable=False),
    sa.Column('currency', sa.String(length=3), nullable=False),
    sa.Column('total_cents', sa.Integer(), nullable=False),
    sa.Column('revisions_included', sa.Integer(), nullable=False),
    sa.Column('rights_type', sa.Enum('exclusive', 'nonexclusive', 'custom', name='project_rights_type', native_enum=False, create_constraint=True, length=40), nullable=False),
    sa.Column('rights_terms', sa.Text(), nullable=False),
    sa.Column('acceptance_evidence', sa.JSON(), nullable=False),
    sa.Column('commission_rule_id', sa.Uuid(), nullable=False),
    sa.Column('status', sa.Enum('active', 'completed', 'canceled', 'disputed', name='project_status', native_enum=False, create_constraint=True, length=40), nullable=False),
    sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('canceled_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['client_user_id'], ['users.id'], name=op.f('fk_projects_client_user_id_users'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['commission_rule_id'], ['revenue_share_rules.id'], name=op.f('fk_projects_commission_rule_id_revenue_share_rules'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['creator_id'], ['creator_profiles.id'], name=op.f('fk_projects_creator_id_creator_profiles'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['package_id'], ['service_packages.id'], name=op.f('fk_projects_package_id_service_packages'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['proposal_id'], ['proposals.id'], name=op.f('fk_projects_proposal_id_proposals'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['request_id'], ['project_requests.id'], name=op.f('fk_projects_request_id_project_requests'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_projects'))
    )
    op.create_index(op.f('ix_projects_client_user_id'), 'projects', ['client_user_id'], unique=False)
    op.create_index(op.f('ix_projects_creator_id'), 'projects', ['creator_id'], unique=False)
    op.create_table('client_galleries',
    sa.Column('creator_id', sa.Uuid(), nullable=False),
    sa.Column('project_id', sa.Uuid(), nullable=True),
    sa.Column('title', sa.String(length=200), nullable=False),
    sa.Column('message', sa.Text(), nullable=False),
    sa.Column('client_name', sa.String(length=200), nullable=False),
    sa.Column('client_email', sa.String(length=320), nullable=True),
    sa.Column('access_token', sa.String(length=64), nullable=False),
    sa.Column('password_hash', sa.String(length=255), nullable=True),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('allow_downloads', sa.Boolean(), nullable=False),
    sa.Column('selection_limit', sa.Integer(), nullable=True),
    sa.Column('status', sa.Enum('draft', 'shared', 'approved', 'archived', name='gallery_status', native_enum=False, create_constraint=True, length=40), nullable=False),
    sa.Column('client_approved_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_viewed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['creator_id'], ['creator_profiles.id'], name=op.f('fk_client_galleries_creator_id_creator_profiles'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], name=op.f('fk_client_galleries_project_id_projects'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_client_galleries')),
    sa.UniqueConstraint('access_token', name=op.f('uq_client_galleries_access_token'))
    )
    op.create_index(op.f('ix_client_galleries_creator_id'), 'client_galleries', ['creator_id'], unique=False)
    op.create_table('milestones',
    sa.Column('project_id', sa.Uuid(), nullable=False),
    sa.Column('position', sa.Integer(), nullable=False),
    sa.Column('title', sa.String(length=200), nullable=False),
    sa.Column('description', sa.Text(), nullable=False),
    sa.Column('amount_cents', sa.Integer(), nullable=False),
    sa.Column('due_date', sa.Date(), nullable=True),
    sa.Column('status', sa.Enum('unfunded', 'funded', 'submitted', 'revision_requested', 'approved', 'refunded', 'canceled', 'disputed', name='milestone_status', native_enum=False, create_constraint=True, length=40), nullable=False),
    sa.Column('tax_cents', sa.Integer(), nullable=False),
    sa.Column('funded_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('submitted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('auto_approve_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('approved_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('revisions_used', sa.Integer(), nullable=False),
    sa.Column('released_cents', sa.Integer(), nullable=False),
    sa.Column('refunded_cents', sa.Integer(), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint('amount_cents >= 100', name=op.f('ck_milestones_amount_minimum')),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], name=op.f('fk_milestones_project_id_projects'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_milestones'))
    )
    op.create_index(op.f('ix_milestones_auto_approve_at'), 'milestones', ['auto_approve_at'], unique=False)
    op.create_index(op.f('ix_milestones_project_id'), 'milestones', ['project_id'], unique=False)
    op.create_table('reviews',
    sa.Column('project_id', sa.Uuid(), nullable=False),
    sa.Column('direction', sa.Enum('client_to_creator', 'creator_to_client', name='review_direction', native_enum=False, create_constraint=True, length=40), nullable=False),
    sa.Column('reviewer_id', sa.Uuid(), nullable=False),
    sa.Column('creator_id', sa.Uuid(), nullable=False),
    sa.Column('rating', sa.Integer(), nullable=False),
    sa.Column('body', sa.Text(), nullable=False),
    sa.Column('is_hidden', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.CheckConstraint('rating BETWEEN 1 AND 5', name=op.f('ck_reviews_rating_range')),
    sa.ForeignKeyConstraint(['creator_id'], ['creator_profiles.id'], name=op.f('fk_reviews_creator_id_creator_profiles'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], name=op.f('fk_reviews_project_id_projects'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['reviewer_id'], ['users.id'], name=op.f('fk_reviews_reviewer_id_users'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_reviews')),
    sa.UniqueConstraint('project_id', 'direction', name=op.f('uq_reviews_project_id_direction'))
    )
    op.create_index(op.f('ix_reviews_creator_id'), 'reviews', ['creator_id'], unique=False)
    op.create_index(op.f('ix_reviews_project_id'), 'reviews', ['project_id'], unique=False)
    op.create_table('deliverables',
    sa.Column('milestone_id', sa.Uuid(), nullable=False),
    sa.Column('uploaded_by', sa.Uuid(), nullable=False),
    sa.Column('filename', sa.String(length=255), nullable=False),
    sa.Column('content_type', sa.String(length=100), nullable=False),
    sa.Column('size_bytes', sa.BigInteger(), nullable=False),
    sa.Column('storage_key', sa.String(length=500), nullable=False),
    sa.Column('checksum_sha256', sa.String(length=64), nullable=False),
    sa.Column('note', sa.Text(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['milestone_id'], ['milestones.id'], name=op.f('fk_deliverables_milestone_id_milestones'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['uploaded_by'], ['users.id'], name=op.f('fk_deliverables_uploaded_by_users'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_deliverables'))
    )
    op.create_index(op.f('ix_deliverables_milestone_id'), 'deliverables', ['milestone_id'], unique=False)
    op.create_table('gallery_items',
    sa.Column('gallery_id', sa.Uuid(), nullable=False),
    sa.Column('position', sa.Integer(), nullable=False),
    sa.Column('filename', sa.String(length=255), nullable=False),
    sa.Column('media_type', sa.String(length=10), nullable=False),
    sa.Column('status', sa.Enum('processing', 'ready', 'failed', name='gallery_item_status', native_enum=False, create_constraint=True, length=40), nullable=False),
    sa.Column('original_key', sa.String(length=500), nullable=True),
    sa.Column('original_content_type', sa.String(length=100), nullable=True),
    sa.Column('preview_key', sa.String(length=500), nullable=True),
    sa.Column('thumbnail_key', sa.String(length=500), nullable=True),
    sa.Column('width', sa.Integer(), nullable=True),
    sa.Column('height', sa.Integer(), nullable=True),
    sa.Column('size_bytes', sa.BigInteger(), nullable=True),
    sa.Column('is_favorite', sa.Boolean(), nullable=False),
    sa.Column('is_selected', sa.Boolean(), nullable=False),
    sa.Column('processing_error', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['gallery_id'], ['client_galleries.id'], name=op.f('fk_gallery_items_gallery_id_client_galleries'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_gallery_items'))
    )
    op.create_index('ix_gallery_items_gallery_position', 'gallery_items', ['gallery_id', 'position'], unique=False)
    op.create_table('project_disputes',
    sa.Column('project_id', sa.Uuid(), nullable=False),
    sa.Column('milestone_id', sa.Uuid(), nullable=False),
    sa.Column('opened_by', sa.Uuid(), nullable=False),
    sa.Column('reason', sa.String(length=60), nullable=False),
    sa.Column('description', sa.Text(), nullable=False),
    sa.Column('previous_status', sa.String(length=40), nullable=False),
    sa.Column('status', sa.Enum('open', 'resolved_release', 'resolved_refund', 'resolved_split', 'withdrawn', name='project_dispute_status', native_enum=False, create_constraint=True, length=40), nullable=False),
    sa.Column('creator_share_bps', sa.Integer(), nullable=True),
    sa.Column('resolution_note', sa.Text(), nullable=True),
    sa.Column('resolved_by', sa.Uuid(), nullable=True),
    sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['milestone_id'], ['milestones.id'], name=op.f('fk_project_disputes_milestone_id_milestones'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['opened_by'], ['users.id'], name=op.f('fk_project_disputes_opened_by_users'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], name=op.f('fk_project_disputes_project_id_projects'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['resolved_by'], ['users.id'], name=op.f('fk_project_disputes_resolved_by_users'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_project_disputes'))
    )
    op.create_index(op.f('ix_project_disputes_milestone_id'), 'project_disputes', ['milestone_id'], unique=False)
    op.create_index(op.f('ix_project_disputes_project_id'), 'project_disputes', ['project_id'], unique=False)
    op.create_table('revision_requests',
    sa.Column('milestone_id', sa.Uuid(), nullable=False),
    sa.Column('requested_by', sa.Uuid(), nullable=False),
    sa.Column('note', sa.Text(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['milestone_id'], ['milestones.id'], name=op.f('fk_revision_requests_milestone_id_milestones'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['requested_by'], ['users.id'], name=op.f('fk_revision_requests_requested_by_users'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_revision_requests'))
    )
    op.create_index(op.f('ix_revision_requests_milestone_id'), 'revision_requests', ['milestone_id'], unique=False)
    op.create_table('gallery_comments',
    sa.Column('gallery_id', sa.Uuid(), nullable=False),
    sa.Column('item_id', sa.Uuid(), nullable=True),
    sa.Column('author', sa.String(length=20), nullable=False),
    sa.Column('body', sa.Text(), nullable=False),
    sa.Column('is_revision_request', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['gallery_id'], ['client_galleries.id'], name=op.f('fk_gallery_comments_gallery_id_client_galleries'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['item_id'], ['gallery_items.id'], name=op.f('fk_gallery_comments_item_id_gallery_items'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_gallery_comments'))
    )
    op.create_index(op.f('ix_gallery_comments_gallery_id'), 'gallery_comments', ['gallery_id'], unique=False)
    # Existing tables: batch mode so SQLite (dev/tests) can alter columns and FKs.
    with op.batch_alter_table("earnings") as b:
        b.add_column(sa.Column("milestone_id", sa.Uuid(), nullable=True))
        b.alter_column("order_line_id", existing_type=sa.Uuid(), nullable=True)
        b.create_index(op.f("ix_earnings_milestone_id"), ["milestone_id"], unique=False)
        b.create_foreign_key(op.f("fk_earnings_milestone_id_milestones"), "milestones", ["milestone_id"], ["id"],
                             ondelete="RESTRICT")
    with op.batch_alter_table("orders") as b:
        b.add_column(sa.Column("purpose", sa.String(40), server_default="license", nullable=False))
        b.add_column(sa.Column("milestone_id", sa.Uuid(), nullable=True))
        b.create_index(op.f("ix_orders_milestone_id"), ["milestone_id"], unique=False)
        b.create_foreign_key(op.f("fk_orders_milestone_id_milestones"), "milestones", ["milestone_id"], ["id"],
                             ondelete="RESTRICT")
    with op.batch_alter_table("orders") as b:
        b.create_check_constraint(op.f("ck_orders_order_purpose"), sa.column("purpose").in_(["license", "milestone"]))
    with op.batch_alter_table("refunds") as b:
        b.add_column(sa.Column("milestone_id", sa.Uuid(), nullable=True))
        b.alter_column("order_line_id", existing_type=sa.Uuid(), nullable=True)
        b.create_index(op.f("ix_refunds_milestone_id"), ["milestone_id"], unique=False)
        b.create_foreign_key(op.f("fk_refunds_milestone_id_milestones"), "milestones", ["milestone_id"], ["id"],
                             ondelete="RESTRICT")

    for table, column, name, values in ENUM_CHANGES:
        _replace_enum_check(table, column, name, values[1])


def downgrade() -> None:
    for table, column, name, values in ENUM_CHANGES:
        _replace_enum_check(table, column, name, values[0])
    with op.batch_alter_table("refunds") as b:
        b.drop_constraint(op.f("fk_refunds_milestone_id_milestones"), type_="foreignkey")
        b.drop_index(op.f("ix_refunds_milestone_id"))
        b.alter_column("order_line_id", existing_type=sa.Uuid(), nullable=False)
        b.drop_column("milestone_id")
    with op.batch_alter_table("orders") as b:
        b.drop_constraint(op.f("ck_orders_order_purpose"), type_="check")
    with op.batch_alter_table("orders") as b:
        b.drop_constraint(op.f("fk_orders_milestone_id_milestones"), type_="foreignkey")
        b.drop_index(op.f("ix_orders_milestone_id"))
        b.drop_column("milestone_id")
        b.drop_column("purpose")
    with op.batch_alter_table("earnings") as b:
        b.drop_constraint(op.f("fk_earnings_milestone_id_milestones"), type_="foreignkey")
        b.drop_index(op.f("ix_earnings_milestone_id"))
        b.alter_column("order_line_id", existing_type=sa.Uuid(), nullable=False)
        b.drop_column("milestone_id")
    op.drop_index(op.f('ix_gallery_comments_gallery_id'), table_name='gallery_comments')
    op.drop_table('gallery_comments')
    op.drop_index(op.f('ix_revision_requests_milestone_id'), table_name='revision_requests')
    op.drop_table('revision_requests')
    op.drop_index(op.f('ix_project_disputes_project_id'), table_name='project_disputes')
    op.drop_index(op.f('ix_project_disputes_milestone_id'), table_name='project_disputes')
    op.drop_table('project_disputes')
    op.drop_index('ix_gallery_items_gallery_position', table_name='gallery_items')
    op.drop_table('gallery_items')
    op.drop_index(op.f('ix_deliverables_milestone_id'), table_name='deliverables')
    op.drop_table('deliverables')
    op.drop_index(op.f('ix_reviews_project_id'), table_name='reviews')
    op.drop_index(op.f('ix_reviews_creator_id'), table_name='reviews')
    op.drop_table('reviews')
    op.drop_index(op.f('ix_milestones_project_id'), table_name='milestones')
    op.drop_index(op.f('ix_milestones_auto_approve_at'), table_name='milestones')
    op.drop_table('milestones')
    op.drop_index(op.f('ix_client_galleries_creator_id'), table_name='client_galleries')
    op.drop_table('client_galleries')
    op.drop_index(op.f('ix_projects_creator_id'), table_name='projects')
    op.drop_index(op.f('ix_projects_client_user_id'), table_name='projects')
    op.drop_table('projects')
    op.drop_index(op.f('ix_service_packages_creator_id'), table_name='service_packages')
    op.drop_index(op.f('ix_service_packages_category'), table_name='service_packages')
    op.drop_table('service_packages')
    op.drop_index(op.f('ix_request_invitations_request_id'), table_name='request_invitations')
    op.drop_index(op.f('ix_request_invitations_creator_id'), table_name='request_invitations')
    op.drop_table('request_invitations')
    op.drop_index(op.f('ix_proposals_request_id'), table_name='proposals')
    op.drop_index(op.f('ix_proposals_creator_id'), table_name='proposals')
    op.drop_table('proposals')
    op.drop_index('ix_project_requests_status_category', table_name='project_requests')
    op.drop_index(op.f('ix_project_requests_location_country'), table_name='project_requests')
    op.drop_index(op.f('ix_project_requests_location_city'), table_name='project_requests')
    op.drop_index(op.f('ix_project_requests_deadline'), table_name='project_requests')
    op.drop_index(op.f('ix_project_requests_client_user_id'), table_name='project_requests')
    op.drop_table('project_requests')
    op.drop_index('ix_notifications_user_read', table_name='notifications')
    op.drop_index(op.f('ix_notifications_created_at'), table_name='notifications')
    op.drop_table('notifications')
    op.drop_index('ix_messages_conversation_created', table_name='messages')
    op.drop_table('messages')
    op.drop_index(op.f('ix_conversation_participants_user_id'), table_name='conversation_participants')
    op.drop_index(op.f('ix_conversation_participants_conversation_id'), table_name='conversation_participants')
    op.drop_table('conversation_participants')
    op.drop_index(op.f('ix_conversations_last_message_at'), table_name='conversations')
    op.drop_table('conversations')
