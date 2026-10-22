"""Phase 1 foundation: accounts, roles, organizations, storefronts, media,
releases, copyright declarations, licensing catalog, versioned agreements and
revenue-share rules, rights grants, downloads, moderation, complaints, audit.

Revision ID: 0001
Revises: 
Create Date: 2026-10-22 18:59:54.519940
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = '0001'
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('license_types',
    sa.Column('code', sa.String(length=40), nullable=False),
    sa.Column('name', sa.String(length=120), nullable=False),
    sa.Column('summary', sa.Text(), nullable=False),
    sa.Column('is_free', sa.Boolean(), nullable=False),
    sa.Column('is_exclusive', sa.Boolean(), nullable=False),
    sa.Column('allows_commercial_use', sa.Boolean(), nullable=False),
    sa.Column('allows_editorial_use', sa.Boolean(), nullable=False),
    sa.Column('requires_attribution', sa.Boolean(), nullable=False),
    sa.Column('permitted_uses', sa.JSON(), nullable=False),
    sa.Column('terms_version', sa.String(length=20), nullable=False),
    sa.Column('terms_markdown', sa.Text(), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('sort_order', sa.Integer(), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_license_types')),
    sa.UniqueConstraint('code', name=op.f('uq_license_types_code'))
    )
    op.create_table('roles',
    sa.Column('code', sa.String(length=40), nullable=False),
    sa.Column('name', sa.String(length=80), nullable=False),
    sa.Column('description', sa.String(length=255), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_roles')),
    sa.UniqueConstraint('code', name=op.f('uq_roles_code'))
    )
    op.create_table('users',
    sa.Column('email', sa.String(length=320), nullable=False),
    sa.Column('password_hash', sa.String(length=255), nullable=False),
    sa.Column('display_name', sa.String(length=120), nullable=False),
    sa.Column('status', sa.Enum('active', 'suspended', 'banned', 'deactivated', name='user_status', native_enum=False, create_constraint=True, length=40), nullable=False),
    sa.Column('email_verified_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('mfa_secret', sa.String(length=64), nullable=True),
    sa.Column('mfa_enabled', sa.Boolean(), nullable=False),
    sa.Column('token_version', sa.Integer(), nullable=False),
    sa.Column('country_code', sa.String(length=2), nullable=True),
    sa.Column('last_login_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('referred_by_code', sa.String(length=40), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_users'))
    )
    op.create_index(op.f('ix_users_email'), 'users', ['email'], unique=True)
    op.create_table('audit_logs',
    sa.Column('actor_user_id', sa.Uuid(), nullable=True),
    sa.Column('action', sa.String(length=80), nullable=False),
    sa.Column('subject_type', sa.String(length=40), nullable=True),
    sa.Column('subject_id', sa.String(length=64), nullable=True),
    sa.Column('details', sa.JSON(), nullable=False),
    sa.Column('ip_address', sa.String(length=45), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['actor_user_id'], ['users.id'], name=op.f('fk_audit_logs_actor_user_id_users'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_audit_logs'))
    )
    op.create_index('ix_audit_created', 'audit_logs', ['created_at'], unique=False)
    op.create_index('ix_audit_subject', 'audit_logs', ['subject_type', 'subject_id'], unique=False)
    op.create_table('collections',
    sa.Column('owner_id', sa.Uuid(), nullable=False),
    sa.Column('name', sa.String(length=120), nullable=False),
    sa.Column('is_private', sa.Boolean(), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['owner_id'], ['users.id'], name=op.f('fk_collections_owner_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_collections'))
    )
    op.create_index(op.f('ix_collections_owner_id'), 'collections', ['owner_id'], unique=False)
    op.create_table('email_tokens',
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('purpose', sa.Enum('verify_email', 'reset_password', name='email_token_purpose', native_enum=False, create_constraint=True, length=40), nullable=False),
    sa.Column('token_hash', sa.String(length=64), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('used_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_email_tokens_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_email_tokens')),
    sa.UniqueConstraint('token_hash', name=op.f('uq_email_tokens_token_hash'))
    )
    op.create_index(op.f('ix_email_tokens_user_id'), 'email_tokens', ['user_id'], unique=False)
    op.create_table('moderation_decisions',
    sa.Column('subject_type', sa.String(length=40), nullable=False),
    sa.Column('subject_id', sa.Uuid(), nullable=False),
    sa.Column('action', sa.Enum('approve', 'reject', 'request_changes', 'disable', 'restore', name='moderation_action', native_enum=False, create_constraint=True, length=40), nullable=False),
    sa.Column('reason', sa.Text(), nullable=False),
    sa.Column('automated_signals', sa.JSON(), nullable=False),
    sa.Column('moderator_id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['moderator_id'], ['users.id'], name=op.f('fk_moderation_decisions_moderator_id_users'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_moderation_decisions'))
    )
    op.create_index('ix_moderation_subject', 'moderation_decisions', ['subject_type', 'subject_id'], unique=False)
    op.create_table('organizations',
    sa.Column('name', sa.String(length=160), nullable=False),
    sa.Column('slug', sa.String(length=80), nullable=False),
    sa.Column('org_type', sa.Enum('production_studio', 'media_agency', 'corporate_buyer', 'university', 'film_club', 'association', 'vendor', name='organization_type', native_enum=False, create_constraint=True, length=40), nullable=False),
    sa.Column('website', sa.String(length=255), nullable=True),
    sa.Column('country_code', sa.String(length=2), nullable=True),
    sa.Column('verified_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_by', sa.Uuid(), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], name=op.f('fk_organizations_created_by_users'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_organizations'))
    )
    op.create_index(op.f('ix_organizations_slug'), 'organizations', ['slug'], unique=True)
    op.create_table('revenue_share_rules',
    sa.Column('code', sa.String(length=40), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('revenue_model', sa.Enum('nonexclusive', 'exclusive', 'free', name='revenue_model', native_enum=False, create_constraint=True, length=40), nullable=False),
    sa.Column('creator_bps', sa.Integer(), nullable=False),
    sa.Column('initial_exclusive_creator_bps', sa.Integer(), nullable=True),
    sa.Column('affiliate_bps_of_platform', sa.Integer(), nullable=False),
    sa.Column('net_revenue_deductions', sa.JSON(), nullable=False),
    sa.Column('notes', sa.Text(), nullable=False),
    sa.Column('effective_from', sa.DateTime(timezone=True), nullable=False),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.CheckConstraint('affiliate_bps_of_platform BETWEEN 0 AND 10000', name=op.f('ck_revenue_share_rules_affiliate_bps_range')),
    sa.CheckConstraint('creator_bps BETWEEN 0 AND 10000', name=op.f('ck_revenue_share_rules_creator_bps_range')),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], name=op.f('fk_revenue_share_rules_created_by_users'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_revenue_share_rules')),
    sa.UniqueConstraint('code', 'version', name=op.f('uq_revenue_share_rules_code_version'))
    )
    op.create_table('user_roles',
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('role_id', sa.Uuid(), nullable=False),
    sa.Column('granted_by', sa.Uuid(), nullable=True),
    sa.Column('granted_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['granted_by'], ['users.id'], name=op.f('fk_user_roles_granted_by_users'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['role_id'], ['roles.id'], name=op.f('fk_user_roles_role_id_roles'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_user_roles_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_user_roles')),
    sa.UniqueConstraint('user_id', 'role_id', name=op.f('uq_user_roles_user_id_role_id'))
    )
    op.create_index(op.f('ix_user_roles_user_id'), 'user_roles', ['user_id'], unique=False)
    op.create_table('agreement_templates',
    sa.Column('code', sa.String(length=40), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('title', sa.String(length=200), nullable=False),
    sa.Column('revenue_model', sa.Enum('nonexclusive', 'exclusive', 'free', name='agreement_revenue_model', native_enum=False, create_constraint=True, length=40), nullable=False),
    sa.Column('revenue_share_rule_id', sa.Uuid(), nullable=False),
    sa.Column('body_markdown', sa.Text(), nullable=False),
    sa.Column('body_sha256', sa.String(length=64), nullable=False),
    sa.Column('territory', sa.JSON(), nullable=False),
    sa.Column('permitted_uses', sa.JSON(), nullable=False),
    sa.Column('sublicensing_allowed', sa.Boolean(), nullable=False),
    sa.Column('duration', sa.String(length=40), nullable=False),
    sa.Column('withdrawal_terms', sa.Text(), nullable=False),
    sa.Column('legal_review_status', sa.Enum('draft', 'under_review', 'approved', 'retired', name='legal_review_status', native_enum=False, create_constraint=True, length=40), nullable=False),
    sa.Column('legal_reviewed_by', sa.String(length=200), nullable=True),
    sa.Column('legal_reviewed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['revenue_share_rule_id'], ['revenue_share_rules.id'], name=op.f('fk_agreement_templates_revenue_share_rule_id_revenue_share_rules'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_agreement_templates')),
    sa.UniqueConstraint('code', 'version', name=op.f('uq_agreement_templates_code_version'))
    )
    op.create_table('content_appeals',
    sa.Column('decision_id', sa.Uuid(), nullable=False),
    sa.Column('appellant_id', sa.Uuid(), nullable=False),
    sa.Column('statement', sa.Text(), nullable=False),
    sa.Column('status', sa.Enum('open', 'upheld', 'overturned', name='appeal_status', native_enum=False, create_constraint=True, length=40), nullable=False),
    sa.Column('resolved_by', sa.Uuid(), nullable=True),
    sa.Column('resolution_note', sa.Text(), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['appellant_id'], ['users.id'], name=op.f('fk_content_appeals_appellant_id_users'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['decision_id'], ['moderation_decisions.id'], name=op.f('fk_content_appeals_decision_id_moderation_decisions'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['resolved_by'], ['users.id'], name=op.f('fk_content_appeals_resolved_by_users'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_content_appeals'))
    )
    op.create_index(op.f('ix_content_appeals_decision_id'), 'content_appeals', ['decision_id'], unique=False)
    op.create_table('creator_profiles',
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('organization_id', sa.Uuid(), nullable=True),
    sa.Column('handle', sa.String(length=40), nullable=False),
    sa.Column('display_name', sa.String(length=120), nullable=False),
    sa.Column('headline', sa.String(length=200), nullable=False),
    sa.Column('bio', sa.Text(), nullable=False),
    sa.Column('avatar_url', sa.String(length=500), nullable=True),
    sa.Column('banner_url', sa.String(length=500), nullable=True),
    sa.Column('categories', sa.JSON(), nullable=False),
    sa.Column('specialties', sa.JSON(), nullable=False),
    sa.Column('city', sa.String(length=120), nullable=True),
    sa.Column('region', sa.String(length=120), nullable=True),
    sa.Column('country_code', sa.String(length=2), nullable=True),
    sa.Column('service_radius_km', sa.Integer(), nullable=True),
    sa.Column('remote_available', sa.Boolean(), nullable=False),
    sa.Column('travel_available', sa.Boolean(), nullable=False),
    sa.Column('website', sa.String(length=255), nullable=True),
    sa.Column('verification_status', sa.Enum('unverified', 'pending', 'verified', 'rejected', name='verification_status', native_enum=False, create_constraint=True, length=40), nullable=False),
    sa.Column('is_emerging_talent', sa.Boolean(), nullable=False),
    sa.Column('is_featured', sa.Boolean(), nullable=False),
    sa.Column('follower_count', sa.Integer(), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], name=op.f('fk_creator_profiles_organization_id_organizations'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_creator_profiles_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_creator_profiles')),
    sa.UniqueConstraint('user_id', name=op.f('uq_creator_profiles_user_id'))
    )
    op.create_index(op.f('ix_creator_profiles_city'), 'creator_profiles', ['city'], unique=False)
    op.create_index(op.f('ix_creator_profiles_country_code'), 'creator_profiles', ['country_code'], unique=False)
    op.create_index(op.f('ix_creator_profiles_handle'), 'creator_profiles', ['handle'], unique=True)
    op.create_index(op.f('ix_creator_profiles_is_emerging_talent'), 'creator_profiles', ['is_emerging_talent'], unique=False)
    op.create_index(op.f('ix_creator_profiles_is_featured'), 'creator_profiles', ['is_featured'], unique=False)
    op.create_index(op.f('ix_creator_profiles_organization_id'), 'creator_profiles', ['organization_id'], unique=False)
    op.create_table('organization_members',
    sa.Column('organization_id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('member_role', sa.Enum('owner', 'admin', 'member', 'student', name='org_member_role', native_enum=False, create_constraint=True, length=40), nullable=False),
    sa.Column('joined_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], name=op.f('fk_organization_members_organization_id_organizations'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_organization_members_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_organization_members')),
    sa.UniqueConstraint('organization_id', 'user_id', name=op.f('uq_organization_members_organization_id_user_id'))
    )
    op.create_index(op.f('ix_organization_members_organization_id'), 'organization_members', ['organization_id'], unique=False)
    op.create_index(op.f('ix_organization_members_user_id'), 'organization_members', ['user_id'], unique=False)
    op.create_table('contributor_agreements',
    sa.Column('template_id', sa.Uuid(), nullable=False),
    sa.Column('creator_id', sa.Uuid(), nullable=False),
    sa.Column('signer_user_id', sa.Uuid(), nullable=False),
    sa.Column('signer_legal_name', sa.String(length=200), nullable=False),
    sa.Column('rights_owner_name', sa.String(length=200), nullable=False),
    sa.Column('territory', sa.JSON(), nullable=False),
    sa.Column('permitted_uses', sa.JSON(), nullable=False),
    sa.Column('sublicensing_allowed', sa.Boolean(), nullable=False),
    sa.Column('duration', sa.String(length=40), nullable=False),
    sa.Column('signature_method', sa.Enum('clickwrap', 'esign_provider', name='signature_method', native_enum=False, create_constraint=True, length=40), nullable=False),
    sa.Column('signature_evidence', sa.JSON(), nullable=False),
    sa.Column('effective_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('status', sa.Enum('active', 'superseded', 'terminated', name='agreement_status', native_enum=False, create_constraint=True, length=40), nullable=False),
    sa.Column('terminated_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('termination_reason', sa.Text(), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['creator_id'], ['creator_profiles.id'], name=op.f('fk_contributor_agreements_creator_id_creator_profiles'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['signer_user_id'], ['users.id'], name=op.f('fk_contributor_agreements_signer_user_id_users'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['template_id'], ['agreement_templates.id'], name=op.f('fk_contributor_agreements_template_id_agreement_templates'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_contributor_agreements'))
    )
    op.create_index('ix_contributor_agreements_creator_status', 'contributor_agreements', ['creator_id', 'status'], unique=False)
    op.create_table('follows',
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('creator_id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['creator_id'], ['creator_profiles.id'], name=op.f('fk_follows_creator_id_creator_profiles'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_follows_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_follows')),
    sa.UniqueConstraint('user_id', 'creator_id', name=op.f('uq_follows_user_id_creator_id'))
    )
    op.create_index(op.f('ix_follows_creator_id'), 'follows', ['creator_id'], unique=False)
    op.create_index(op.f('ix_follows_user_id'), 'follows', ['user_id'], unique=False)
    op.create_table('media_assets',
    sa.Column('creator_id', sa.Uuid(), nullable=False),
    sa.Column('uploaded_by', sa.Uuid(), nullable=False),
    sa.Column('contributor_agreement_id', sa.Uuid(), nullable=True),
    sa.Column('media_type', sa.Enum('photo', 'video', name='media_type', native_enum=False, create_constraint=True, length=40), nullable=False),
    sa.Column('status', sa.Enum('processing', 'pending_review', 'approved', 'changes_requested', 'rejected', 'disabled', 'withdrawn', 'failed', name='media_status', native_enum=False, create_constraint=True, length=40), nullable=False),
    sa.Column('title', sa.String(length=200), nullable=False),
    sa.Column('description', sa.Text(), nullable=False),
    sa.Column('category', sa.String(length=40), nullable=False),
    sa.Column('keywords', sa.JSON(), nullable=False),
    sa.Column('search_text', sa.Text(), nullable=False),
    sa.Column('orientation', sa.Enum('horizontal', 'vertical', 'square', name='orientation', native_enum=False, create_constraint=True, length=40), nullable=True),
    sa.Column('width', sa.Integer(), nullable=True),
    sa.Column('height', sa.Integer(), nullable=True),
    sa.Column('duration_seconds', sa.Float(), nullable=True),
    sa.Column('frame_rate', sa.Float(), nullable=True),
    sa.Column('resolution_label', sa.String(length=10), nullable=True),
    sa.Column('file_format', sa.String(length=10), nullable=True),
    sa.Column('file_size_bytes', sa.BigInteger(), nullable=True),
    sa.Column('checksum_sha256', sa.String(length=64), nullable=True),
    sa.Column('perceptual_hash', sa.String(length=32), nullable=True),
    sa.Column('scan_status', sa.Enum('not_scanned', 'clean', 'infected', 'error', name='scan_status', native_enum=False, create_constraint=True, length=40), nullable=False),
    sa.Column('location_city', sa.String(length=120), nullable=True),
    sa.Column('location_region', sa.String(length=120), nullable=True),
    sa.Column('location_country', sa.String(length=2), nullable=True),
    sa.Column('captured_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('is_editorial_only', sa.Boolean(), nullable=False),
    sa.Column('is_ai_generated', sa.Boolean(), nullable=False),
    sa.Column('is_materially_altered', sa.Boolean(), nullable=False),
    sa.Column('has_model_release', sa.Boolean(), nullable=False),
    sa.Column('has_property_release', sa.Boolean(), nullable=False),
    sa.Column('is_free', sa.Boolean(), nullable=False),
    sa.Column('is_featured', sa.Boolean(), nullable=False),
    sa.Column('view_count', sa.Integer(), nullable=False),
    sa.Column('download_count', sa.Integer(), nullable=False),
    sa.Column('published_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('processing_error', sa.Text(), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['contributor_agreement_id'], ['contributor_agreements.id'], name=op.f('fk_media_assets_contributor_agreement_id_contributor_agreements'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['creator_id'], ['creator_profiles.id'], name=op.f('fk_media_assets_creator_id_creator_profiles'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['uploaded_by'], ['users.id'], name=op.f('fk_media_assets_uploaded_by_users'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_media_assets'))
    )
    op.create_index(op.f('ix_media_assets_category'), 'media_assets', ['category'], unique=False)
    op.create_index(op.f('ix_media_assets_checksum_sha256'), 'media_assets', ['checksum_sha256'], unique=False)
    op.create_index('ix_media_assets_creator_status', 'media_assets', ['creator_id', 'status'], unique=False)
    op.create_index(op.f('ix_media_assets_is_free'), 'media_assets', ['is_free'], unique=False)
    op.create_index(op.f('ix_media_assets_location_country'), 'media_assets', ['location_country'], unique=False)
    op.create_index(op.f('ix_media_assets_perceptual_hash'), 'media_assets', ['perceptual_hash'], unique=False)
    op.create_index(op.f('ix_media_assets_published_at'), 'media_assets', ['published_at'], unique=False)
    op.create_index(op.f('ix_media_assets_resolution_label'), 'media_assets', ['resolution_label'], unique=False)
    op.create_index('ix_media_assets_status_type', 'media_assets', ['status', 'media_type'], unique=False)
    op.create_table('collection_items',
    sa.Column('collection_id', sa.Uuid(), nullable=False),
    sa.Column('asset_id', sa.Uuid(), nullable=False),
    sa.Column('added_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['asset_id'], ['media_assets.id'], name=op.f('fk_collection_items_asset_id_media_assets'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['collection_id'], ['collections.id'], name=op.f('fk_collection_items_collection_id_collections'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_collection_items')),
    sa.UniqueConstraint('collection_id', 'asset_id', name=op.f('uq_collection_items_collection_id_asset_id'))
    )
    op.create_index(op.f('ix_collection_items_collection_id'), 'collection_items', ['collection_id'], unique=False)
    op.create_table('copyright_complaints',
    sa.Column('asset_id', sa.Uuid(), nullable=False),
    sa.Column('complainant_user_id', sa.Uuid(), nullable=True),
    sa.Column('complainant_name', sa.String(length=200), nullable=False),
    sa.Column('complainant_email', sa.String(length=320), nullable=False),
    sa.Column('complainant_address', sa.Text(), nullable=False),
    sa.Column('copyrighted_work_description', sa.Text(), nullable=False),
    sa.Column('good_faith_statement', sa.Boolean(), nullable=False),
    sa.Column('accuracy_statement', sa.Boolean(), nullable=False),
    sa.Column('electronic_signature', sa.String(length=200), nullable=False),
    sa.Column('status', sa.Enum('received', 'under_review', 'content_disabled', 'counter_notice_received', 'restored', 'rejected', 'closed', name='complaint_status', native_enum=False, create_constraint=True, length=40), nullable=False),
    sa.Column('counter_notice', sa.JSON(), nullable=True),
    sa.Column('handled_by', sa.Uuid(), nullable=True),
    sa.Column('resolution_note', sa.Text(), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['asset_id'], ['media_assets.id'], name=op.f('fk_copyright_complaints_asset_id_media_assets'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['complainant_user_id'], ['users.id'], name=op.f('fk_copyright_complaints_complainant_user_id_users'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['handled_by'], ['users.id'], name=op.f('fk_copyright_complaints_handled_by_users'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_copyright_complaints'))
    )
    op.create_index(op.f('ix_copyright_complaints_asset_id'), 'copyright_complaints', ['asset_id'], unique=False)
    op.create_table('copyright_declarations',
    sa.Column('asset_id', sa.Uuid(), nullable=False),
    sa.Column('declarant_user_id', sa.Uuid(), nullable=False),
    sa.Column('rights_owner_name', sa.String(length=200), nullable=False),
    sa.Column('is_original_author', sa.Boolean(), nullable=False),
    sa.Column('holds_necessary_rights', sa.Boolean(), nullable=False),
    sa.Column('existing_licenses_disclosure', sa.Text(), nullable=False),
    sa.Column('has_prior_exclusive_grant', sa.Boolean(), nullable=False),
    sa.Column('declaration_version', sa.String(length=20), nullable=False),
    sa.Column('declaration_text', sa.Text(), nullable=False),
    sa.Column('ip_address', sa.String(length=45), nullable=True),
    sa.Column('user_agent', sa.String(length=400), nullable=True),
    sa.Column('accepted_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['asset_id'], ['media_assets.id'], name=op.f('fk_copyright_declarations_asset_id_media_assets'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['declarant_user_id'], ['users.id'], name=op.f('fk_copyright_declarations_declarant_user_id_users'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_copyright_declarations')),
    sa.UniqueConstraint('asset_id', name=op.f('uq_copyright_declarations_asset_id'))
    )
    op.create_table('favorites',
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('asset_id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['asset_id'], ['media_assets.id'], name=op.f('fk_favorites_asset_id_media_assets'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_favorites_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_favorites')),
    sa.UniqueConstraint('user_id', 'asset_id', name=op.f('uq_favorites_user_id_asset_id'))
    )
    op.create_index(op.f('ix_favorites_user_id'), 'favorites', ['user_id'], unique=False)
    op.create_table('media_files',
    sa.Column('asset_id', sa.Uuid(), nullable=False),
    sa.Column('kind', sa.Enum('original', 'preview', 'thumbnail', 'poster', name='file_kind', native_enum=False, create_constraint=True, length=40), nullable=False),
    sa.Column('is_public', sa.Boolean(), nullable=False),
    sa.Column('storage_key', sa.String(length=500), nullable=False),
    sa.Column('content_type', sa.String(length=100), nullable=False),
    sa.Column('width', sa.Integer(), nullable=True),
    sa.Column('height', sa.Integer(), nullable=True),
    sa.Column('size_bytes', sa.BigInteger(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['asset_id'], ['media_assets.id'], name=op.f('fk_media_files_asset_id_media_assets'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_media_files')),
    sa.UniqueConstraint('asset_id', 'kind', name=op.f('uq_media_files_asset_id_kind'))
    )
    op.create_table('media_releases',
    sa.Column('asset_id', sa.Uuid(), nullable=False),
    sa.Column('release_type', sa.Enum('model', 'property', name='release_type', native_enum=False, create_constraint=True, length=40), nullable=False),
    sa.Column('subject_name', sa.String(length=200), nullable=False),
    sa.Column('document_storage_key', sa.String(length=500), nullable=True),
    sa.Column('signed_on', sa.DateTime(timezone=True), nullable=True),
    sa.Column('verified_by', sa.Uuid(), nullable=True),
    sa.Column('verified_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['asset_id'], ['media_assets.id'], name=op.f('fk_media_releases_asset_id_media_assets'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['verified_by'], ['users.id'], name=op.f('fk_media_releases_verified_by_users'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_media_releases'))
    )
    op.create_index(op.f('ix_media_releases_asset_id'), 'media_releases', ['asset_id'], unique=False)
    op.create_table('price_listings',
    sa.Column('asset_id', sa.Uuid(), nullable=False),
    sa.Column('license_type_id', sa.Uuid(), nullable=False),
    sa.Column('size_tier', sa.String(length=20), nullable=False),
    sa.Column('price_cents', sa.Integer(), nullable=False),
    sa.Column('currency', sa.String(length=3), nullable=False),
    sa.Column('subscription_credit_eligible', sa.Boolean(), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint('price_cents >= 0', name=op.f('ck_price_listings_price_non_negative')),
    sa.ForeignKeyConstraint(['asset_id'], ['media_assets.id'], name=op.f('fk_price_listings_asset_id_media_assets'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['license_type_id'], ['license_types.id'], name=op.f('fk_price_listings_license_type_id_license_types'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_price_listings')),
    sa.UniqueConstraint('asset_id', 'license_type_id', 'size_tier', name=op.f('uq_price_listings_asset_id_license_type_id_size_tier'))
    )
    op.create_index(op.f('ix_price_listings_asset_id'), 'price_listings', ['asset_id'], unique=False)
    op.create_table('rights_grants',
    sa.Column('certificate_number', sa.String(length=32), nullable=False),
    sa.Column('asset_id', sa.Uuid(), nullable=False),
    sa.Column('license_type_id', sa.Uuid(), nullable=False),
    sa.Column('licensee_user_id', sa.Uuid(), nullable=False),
    sa.Column('licensee_organization_id', sa.Uuid(), nullable=True),
    sa.Column('licensee_name', sa.String(length=200), nullable=False),
    sa.Column('source', sa.Enum('free_download', 'purchase', 'subscription', 'exclusive_agreement', 'negotiated', name='grant_source', native_enum=False, create_constraint=True, length=40), nullable=False),
    sa.Column('is_exclusive', sa.Boolean(), nullable=False),
    sa.Column('territory', sa.JSON(), nullable=False),
    sa.Column('permitted_uses', sa.JSON(), nullable=False),
    sa.Column('size_tier', sa.String(length=20), nullable=False),
    sa.Column('starts_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('ends_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('price_cents', sa.Integer(), nullable=False),
    sa.Column('currency', sa.String(length=3), nullable=False),
    sa.Column('terms_version', sa.String(length=20), nullable=False),
    sa.Column('terms_snapshot', sa.JSON(), nullable=False),
    sa.Column('status', sa.Enum('active', 'expired', 'revoked', 'refunded', name='grant_status', native_enum=False, create_constraint=True, length=40), nullable=False),
    sa.Column('issued_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('revocation_reason', sa.Text(), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['asset_id'], ['media_assets.id'], name=op.f('fk_rights_grants_asset_id_media_assets'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['license_type_id'], ['license_types.id'], name=op.f('fk_rights_grants_license_type_id_license_types'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['licensee_organization_id'], ['organizations.id'], name=op.f('fk_rights_grants_licensee_organization_id_organizations'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['licensee_user_id'], ['users.id'], name=op.f('fk_rights_grants_licensee_user_id_users'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_rights_grants')),
    sa.UniqueConstraint('certificate_number', name=op.f('uq_rights_grants_certificate_number'))
    )
    op.create_index('ix_rights_grants_asset_status', 'rights_grants', ['asset_id', 'status'], unique=False)
    op.create_table('download_entitlements',
    sa.Column('rights_grant_id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('asset_id', sa.Uuid(), nullable=False),
    sa.Column('max_downloads', sa.Integer(), nullable=False),
    sa.Column('download_count', sa.Integer(), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_downloaded_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['asset_id'], ['media_assets.id'], name=op.f('fk_download_entitlements_asset_id_media_assets'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['rights_grant_id'], ['rights_grants.id'], name=op.f('fk_download_entitlements_rights_grant_id_rights_grants'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_download_entitlements_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_download_entitlements'))
    )
    op.create_index(op.f('ix_download_entitlements_rights_grant_id'), 'download_entitlements', ['rights_grant_id'], unique=False)
    op.create_index(op.f('ix_download_entitlements_user_id'), 'download_entitlements', ['user_id'], unique=False)


    # PostgreSQL full-text search index for the media catalog.
    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            "CREATE INDEX ix_media_assets_search_fts ON media_assets "
            "USING GIN (to_tsvector('english', search_text))"
        )

def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP INDEX IF EXISTS ix_media_assets_search_fts")
    op.drop_index(op.f('ix_download_entitlements_user_id'), table_name='download_entitlements')
    op.drop_index(op.f('ix_download_entitlements_rights_grant_id'), table_name='download_entitlements')
    op.drop_table('download_entitlements')
    op.drop_index('ix_rights_grants_asset_status', table_name='rights_grants')
    op.drop_table('rights_grants')
    op.drop_index(op.f('ix_price_listings_asset_id'), table_name='price_listings')
    op.drop_table('price_listings')
    op.drop_index(op.f('ix_media_releases_asset_id'), table_name='media_releases')
    op.drop_table('media_releases')
    op.drop_table('media_files')
    op.drop_index(op.f('ix_favorites_user_id'), table_name='favorites')
    op.drop_table('favorites')
    op.drop_table('copyright_declarations')
    op.drop_index(op.f('ix_copyright_complaints_asset_id'), table_name='copyright_complaints')
    op.drop_table('copyright_complaints')
    op.drop_index(op.f('ix_collection_items_collection_id'), table_name='collection_items')
    op.drop_table('collection_items')
    op.drop_index('ix_media_assets_status_type', table_name='media_assets')
    op.drop_index(op.f('ix_media_assets_resolution_label'), table_name='media_assets')
    op.drop_index(op.f('ix_media_assets_published_at'), table_name='media_assets')
    op.drop_index(op.f('ix_media_assets_perceptual_hash'), table_name='media_assets')
    op.drop_index(op.f('ix_media_assets_location_country'), table_name='media_assets')
    op.drop_index(op.f('ix_media_assets_is_free'), table_name='media_assets')
    op.drop_index('ix_media_assets_creator_status', table_name='media_assets')
    op.drop_index(op.f('ix_media_assets_checksum_sha256'), table_name='media_assets')
    op.drop_index(op.f('ix_media_assets_category'), table_name='media_assets')
    op.drop_table('media_assets')
    op.drop_index(op.f('ix_follows_user_id'), table_name='follows')
    op.drop_index(op.f('ix_follows_creator_id'), table_name='follows')
    op.drop_table('follows')
    op.drop_index('ix_contributor_agreements_creator_status', table_name='contributor_agreements')
    op.drop_table('contributor_agreements')
    op.drop_index(op.f('ix_organization_members_user_id'), table_name='organization_members')
    op.drop_index(op.f('ix_organization_members_organization_id'), table_name='organization_members')
    op.drop_table('organization_members')
    op.drop_index(op.f('ix_creator_profiles_organization_id'), table_name='creator_profiles')
    op.drop_index(op.f('ix_creator_profiles_is_featured'), table_name='creator_profiles')
    op.drop_index(op.f('ix_creator_profiles_is_emerging_talent'), table_name='creator_profiles')
    op.drop_index(op.f('ix_creator_profiles_handle'), table_name='creator_profiles')
    op.drop_index(op.f('ix_creator_profiles_country_code'), table_name='creator_profiles')
    op.drop_index(op.f('ix_creator_profiles_city'), table_name='creator_profiles')
    op.drop_table('creator_profiles')
    op.drop_index(op.f('ix_content_appeals_decision_id'), table_name='content_appeals')
    op.drop_table('content_appeals')
    op.drop_table('agreement_templates')
    op.drop_index(op.f('ix_user_roles_user_id'), table_name='user_roles')
    op.drop_table('user_roles')
    op.drop_table('revenue_share_rules')
    op.drop_index(op.f('ix_organizations_slug'), table_name='organizations')
    op.drop_table('organizations')
    op.drop_index('ix_moderation_subject', table_name='moderation_decisions')
    op.drop_table('moderation_decisions')
    op.drop_index(op.f('ix_email_tokens_user_id'), table_name='email_tokens')
    op.drop_table('email_tokens')
    op.drop_index(op.f('ix_collections_owner_id'), table_name='collections')
    op.drop_table('collections')
    op.drop_index('ix_audit_subject', table_name='audit_logs')
    op.drop_index('ix_audit_created', table_name='audit_logs')
    op.drop_table('audit_logs')
    op.drop_index(op.f('ix_users_email'), table_name='users')
    op.drop_table('users')
    op.drop_table('roles')
    op.drop_table('license_types')
