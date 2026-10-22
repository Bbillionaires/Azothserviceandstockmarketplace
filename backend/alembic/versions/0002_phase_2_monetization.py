"""Phase 2 monetization: orders, financial events, double-entry ledger,
royalty allocations, earnings, payout accounts, payouts, refunds, referrals,
reconciliation runs.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-22 19:42:26.375728
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = '0002'
down_revision: str | None = '0001'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('financial_events',
    sa.Column('provider', sa.String(length=20), nullable=False),
    sa.Column('provider_event_id', sa.String(length=255), nullable=False),
    sa.Column('event_type', sa.String(length=100), nullable=False),
    sa.Column('payload', sa.JSON(), nullable=False),
    sa.Column('received_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('processed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('processing_error', sa.Text(), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_financial_events')),
    sa.UniqueConstraint('provider', 'provider_event_id', name=op.f('uq_financial_events_provider_provider_event_id'))
    )
    op.create_index(op.f('ix_financial_events_event_type'), 'financial_events', ['event_type'], unique=False)
    op.create_table('ledger_accounts',
    sa.Column('code', sa.String(length=120), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('account_type', sa.Enum('asset', 'liability', 'revenue', 'expense', name='ledger_account_type', native_enum=False, create_constraint=True, length=40), nullable=False),
    sa.Column('owner_user_id', sa.Uuid(), nullable=True),
    sa.Column('currency', sa.String(length=3), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['owner_user_id'], ['users.id'], name=op.f('fk_ledger_accounts_owner_user_id_users'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_ledger_accounts')),
    sa.UniqueConstraint('code', 'currency', name=op.f('uq_ledger_accounts_code_currency'))
    )
    op.create_index(op.f('ix_ledger_accounts_owner_user_id'), 'ledger_accounts', ['owner_user_id'], unique=False)
    op.create_table('ledger_journals',
    sa.Column('kind', sa.Enum('sale', 'refund', 'dispute', 'dispute_reinstated', 'payout', 'payout_reversal', 'adjustment', name='journal_kind', native_enum=False, create_constraint=True, length=40), nullable=False),
    sa.Column('idempotency_key', sa.String(length=160), nullable=False),
    sa.Column('reference_type', sa.String(length=40), nullable=False),
    sa.Column('reference_id', sa.String(length=64), nullable=False),
    sa.Column('description', sa.String(length=300), nullable=False),
    sa.Column('currency', sa.String(length=3), nullable=False),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], name=op.f('fk_ledger_journals_created_by_users'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_ledger_journals')),
    sa.UniqueConstraint('idempotency_key', name=op.f('uq_ledger_journals_idempotency_key'))
    )
    op.create_index(op.f('ix_ledger_journals_created_at'), 'ledger_journals', ['created_at'], unique=False)
    op.create_index(op.f('ix_ledger_journals_reference_id'), 'ledger_journals', ['reference_id'], unique=False)
    op.create_table('orders',
    sa.Column('buyer_user_id', sa.Uuid(), nullable=False),
    sa.Column('status', sa.Enum('pending', 'paid', 'partially_refunded', 'refunded', 'disputed', 'canceled', name='order_status', native_enum=False, create_constraint=True, length=40), nullable=False),
    sa.Column('currency', sa.String(length=3), nullable=False),
    sa.Column('subtotal_cents', sa.Integer(), nullable=False),
    sa.Column('tax_cents', sa.Integer(), nullable=False),
    sa.Column('total_cents', sa.Integer(), nullable=False),
    sa.Column('processing_fee_cents', sa.Integer(), nullable=False),
    sa.Column('idempotency_key', sa.String(length=80), nullable=False),
    sa.Column('provider', sa.String(length=20), nullable=False),
    sa.Column('provider_session_id', sa.String(length=255), nullable=True),
    sa.Column('provider_payment_id', sa.String(length=255), nullable=True),
    sa.Column('checkout_url', sa.Text(), nullable=True),
    sa.Column('affiliate_user_id', sa.Uuid(), nullable=True),
    sa.Column('paid_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint('subtotal_cents >= 0', name=op.f('ck_orders_subtotal_non_negative')),
    sa.ForeignKeyConstraint(['affiliate_user_id'], ['users.id'], name=op.f('fk_orders_affiliate_user_id_users'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['buyer_user_id'], ['users.id'], name=op.f('fk_orders_buyer_user_id_users'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_orders')),
    sa.UniqueConstraint('buyer_user_id', 'idempotency_key', name=op.f('uq_orders_buyer_user_id_idempotency_key')),
    sa.UniqueConstraint('provider_payment_id', name=op.f('uq_orders_provider_payment_id')),
    sa.UniqueConstraint('provider_session_id', name=op.f('uq_orders_provider_session_id'))
    )
    op.create_index(op.f('ix_orders_buyer_user_id'), 'orders', ['buyer_user_id'], unique=False)
    op.create_index('ix_orders_status_created', 'orders', ['status', 'created_at'], unique=False)
    op.create_table('payout_accounts',
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('provider', sa.String(length=20), nullable=False),
    sa.Column('provider_account_id', sa.String(length=255), nullable=False),
    sa.Column('status', sa.Enum('onboarding', 'enabled', 'restricted', name='payout_account_status', native_enum=False, create_constraint=True, length=40), nullable=False),
    sa.Column('country', sa.String(length=2), nullable=True),
    sa.Column('details_submitted', sa.Boolean(), nullable=False),
    sa.Column('payouts_enabled', sa.Boolean(), nullable=False),
    sa.Column('requirements_due', sa.JSON(), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_payout_accounts_user_id_users'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_payout_accounts')),
    sa.UniqueConstraint('provider_account_id', name=op.f('uq_payout_accounts_provider_account_id')),
    sa.UniqueConstraint('user_id', name=op.f('uq_payout_accounts_user_id'))
    )
    op.create_table('reconciliation_runs',
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('checks', sa.JSON(), nullable=False),
    sa.Column('findings', sa.JSON(), nullable=False),
    sa.Column('triggered_by', sa.Uuid(), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['triggered_by'], ['users.id'], name=op.f('fk_reconciliation_runs_triggered_by_users'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_reconciliation_runs'))
    )
    op.create_table('referral_codes',
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('code', sa.String(length=40), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_referral_codes_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_referral_codes')),
    sa.UniqueConstraint('code', name=op.f('uq_referral_codes_code')),
    sa.UniqueConstraint('user_id', name=op.f('uq_referral_codes_user_id'))
    )
    op.create_table('referrals',
    sa.Column('referrer_user_id', sa.Uuid(), nullable=False),
    sa.Column('referred_user_id', sa.Uuid(), nullable=False),
    sa.Column('code', sa.String(length=40), nullable=False),
    sa.Column('status', sa.Enum('active', 'rejected', name='referral_status', native_enum=False, create_constraint=True, length=40), nullable=False),
    sa.Column('fraud_flags', sa.JSON(), nullable=False),
    sa.Column('signup_ip', sa.String(length=45), nullable=True),
    sa.Column('attributed_until', sa.DateTime(timezone=True), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['referred_user_id'], ['users.id'], name=op.f('fk_referrals_referred_user_id_users'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['referrer_user_id'], ['users.id'], name=op.f('fk_referrals_referrer_user_id_users'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_referrals')),
    sa.UniqueConstraint('referred_user_id', name=op.f('uq_referrals_referred_user_id'))
    )
    op.create_index(op.f('ix_referrals_referrer_user_id'), 'referrals', ['referrer_user_id'], unique=False)
    op.create_table('ledger_entries',
    sa.Column('journal_id', sa.Uuid(), nullable=False),
    sa.Column('account_id', sa.Uuid(), nullable=False),
    sa.Column('debit_cents', sa.Integer(), nullable=False),
    sa.Column('credit_cents', sa.Integer(), nullable=False),
    sa.Column('memo', sa.String(length=300), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.CheckConstraint('(debit_cents > 0 AND credit_cents = 0) OR (credit_cents > 0 AND debit_cents = 0)', name=op.f('ck_ledger_entries_one_sided_positive')),
    sa.ForeignKeyConstraint(['account_id'], ['ledger_accounts.id'], name=op.f('fk_ledger_entries_account_id_ledger_accounts'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['journal_id'], ['ledger_journals.id'], name=op.f('fk_ledger_entries_journal_id_ledger_journals'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_ledger_entries'))
    )
    op.create_index('ix_ledger_entries_account', 'ledger_entries', ['account_id'], unique=False)
    op.create_index(op.f('ix_ledger_entries_journal_id'), 'ledger_entries', ['journal_id'], unique=False)
    op.create_table('payouts',
    sa.Column('payee_user_id', sa.Uuid(), nullable=False),
    sa.Column('payout_account_id', sa.Uuid(), nullable=False),
    sa.Column('amount_cents', sa.Integer(), nullable=False),
    sa.Column('currency', sa.String(length=3), nullable=False),
    sa.Column('status', sa.Enum('processing', 'sent', 'failed', 'reversed', name='payout_status', native_enum=False, create_constraint=True, length=40), nullable=False),
    sa.Column('idempotency_key', sa.String(length=120), nullable=False),
    sa.Column('provider_transfer_id', sa.String(length=255), nullable=True),
    sa.Column('journal_id', sa.Uuid(), nullable=True),
    sa.Column('failure_reason', sa.Text(), nullable=True),
    sa.Column('sent_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint('amount_cents > 0', name=op.f('ck_payouts_amount_positive')),
    sa.ForeignKeyConstraint(['journal_id'], ['ledger_journals.id'], name=op.f('fk_payouts_journal_id_ledger_journals'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['payee_user_id'], ['users.id'], name=op.f('fk_payouts_payee_user_id_users'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['payout_account_id'], ['payout_accounts.id'], name=op.f('fk_payouts_payout_account_id_payout_accounts'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_payouts')),
    sa.UniqueConstraint('idempotency_key', name=op.f('uq_payouts_idempotency_key')),
    sa.UniqueConstraint('provider_transfer_id', name=op.f('uq_payouts_provider_transfer_id'))
    )
    op.create_index(op.f('ix_payouts_payee_user_id'), 'payouts', ['payee_user_id'], unique=False)
    op.create_table('order_lines',
    sa.Column('order_id', sa.Uuid(), nullable=False),
    sa.Column('position', sa.Integer(), nullable=False),
    sa.Column('asset_id', sa.Uuid(), nullable=False),
    sa.Column('creator_id', sa.Uuid(), nullable=False),
    sa.Column('price_listing_id', sa.Uuid(), nullable=False),
    sa.Column('license_type_id', sa.Uuid(), nullable=False),
    sa.Column('contributor_agreement_id', sa.Uuid(), nullable=False),
    sa.Column('revenue_share_rule_id', sa.Uuid(), nullable=False),
    sa.Column('size_tier', sa.String(length=20), nullable=False),
    sa.Column('licensee_name', sa.String(length=200), nullable=False),
    sa.Column('description', sa.String(length=300), nullable=False),
    sa.Column('unit_price_cents', sa.Integer(), nullable=False),
    sa.Column('tax_cents', sa.Integer(), nullable=False),
    sa.Column('processing_fee_cents', sa.Integer(), nullable=False),
    sa.Column('currency', sa.String(length=3), nullable=False),
    sa.Column('status', sa.Enum('pending', 'fulfilled', 'refunded', 'disputed', name='order_line_status', native_enum=False, create_constraint=True, length=40), nullable=False),
    sa.Column('rights_grant_id', sa.Uuid(), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.CheckConstraint('unit_price_cents > 0', name=op.f('ck_order_lines_price_positive')),
    sa.ForeignKeyConstraint(['asset_id'], ['media_assets.id'], name=op.f('fk_order_lines_asset_id_media_assets'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['contributor_agreement_id'], ['contributor_agreements.id'], name=op.f('fk_order_lines_contributor_agreement_id_contributor_agreements'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['creator_id'], ['creator_profiles.id'], name=op.f('fk_order_lines_creator_id_creator_profiles'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['license_type_id'], ['license_types.id'], name=op.f('fk_order_lines_license_type_id_license_types'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['order_id'], ['orders.id'], name=op.f('fk_order_lines_order_id_orders'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['price_listing_id'], ['price_listings.id'], name=op.f('fk_order_lines_price_listing_id_price_listings'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['revenue_share_rule_id'], ['revenue_share_rules.id'], name=op.f('fk_order_lines_revenue_share_rule_id_revenue_share_rules'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['rights_grant_id'], ['rights_grants.id'], name=op.f('fk_order_lines_rights_grant_id_rights_grants'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_order_lines'))
    )
    op.create_index(op.f('ix_order_lines_asset_id'), 'order_lines', ['asset_id'], unique=False)
    op.create_index(op.f('ix_order_lines_creator_id'), 'order_lines', ['creator_id'], unique=False)
    op.create_index(op.f('ix_order_lines_order_id'), 'order_lines', ['order_id'], unique=False)
    op.create_table('earnings',
    sa.Column('payee_user_id', sa.Uuid(), nullable=False),
    sa.Column('kind', sa.Enum('stock_license', 'affiliate_commission', name='earning_kind', native_enum=False, create_constraint=True, length=40), nullable=False),
    sa.Column('order_line_id', sa.Uuid(), nullable=False),
    sa.Column('amount_cents', sa.Integer(), nullable=False),
    sa.Column('currency', sa.String(length=3), nullable=False),
    sa.Column('status', sa.Enum('pending', 'available', 'paid', 'reversed', name='earning_status', native_enum=False, create_constraint=True, length=40), nullable=False),
    sa.Column('available_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('journal_id', sa.Uuid(), nullable=False),
    sa.Column('payout_id', sa.Uuid(), nullable=True),
    sa.Column('reverses_earning_id', sa.Uuid(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['journal_id'], ['ledger_journals.id'], name=op.f('fk_earnings_journal_id_ledger_journals'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['order_line_id'], ['order_lines.id'], name=op.f('fk_earnings_order_line_id_order_lines'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['payee_user_id'], ['users.id'], name=op.f('fk_earnings_payee_user_id_users'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['payout_id'], ['payouts.id'], name=op.f('fk_earnings_payout_id_payouts'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['reverses_earning_id'], ['earnings.id'], name=op.f('fk_earnings_reverses_earning_id_earnings'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_earnings'))
    )
    op.create_index(op.f('ix_earnings_created_at'), 'earnings', ['created_at'], unique=False)
    op.create_index(op.f('ix_earnings_order_line_id'), 'earnings', ['order_line_id'], unique=False)
    op.create_index('ix_earnings_payee_status', 'earnings', ['payee_user_id', 'status'], unique=False)
    op.create_index(op.f('ix_earnings_payout_id'), 'earnings', ['payout_id'], unique=False)
    op.create_table('refunds',
    sa.Column('order_id', sa.Uuid(), nullable=False),
    sa.Column('order_line_id', sa.Uuid(), nullable=False),
    sa.Column('amount_cents', sa.Integer(), nullable=False),
    sa.Column('currency', sa.String(length=3), nullable=False),
    sa.Column('reason', sa.Enum('requested_by_customer', 'duplicate', 'fraudulent', 'rights_issue', 'chargeback', 'other', name='refund_reason', native_enum=False, create_constraint=True, length=40), nullable=False),
    sa.Column('note', sa.Text(), nullable=False),
    sa.Column('provider_refund_id', sa.String(length=255), nullable=True),
    sa.Column('journal_id', sa.Uuid(), nullable=False),
    sa.Column('initiated_by', sa.Uuid(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['initiated_by'], ['users.id'], name=op.f('fk_refunds_initiated_by_users'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['journal_id'], ['ledger_journals.id'], name=op.f('fk_refunds_journal_id_ledger_journals'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['order_id'], ['orders.id'], name=op.f('fk_refunds_order_id_orders'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['order_line_id'], ['order_lines.id'], name=op.f('fk_refunds_order_line_id_order_lines'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_refunds')),
    sa.UniqueConstraint('order_line_id', name=op.f('uq_refunds_order_line_id')),
    sa.UniqueConstraint('provider_refund_id', name=op.f('uq_refunds_provider_refund_id'))
    )
    op.create_index(op.f('ix_refunds_order_id'), 'refunds', ['order_id'], unique=False)
    op.create_table('royalty_allocations',
    sa.Column('order_line_id', sa.Uuid(), nullable=False),
    sa.Column('rule_code', sa.String(length=40), nullable=False),
    sa.Column('rule_version', sa.Integer(), nullable=False),
    sa.Column('gross_cents', sa.Integer(), nullable=False),
    sa.Column('deductions', sa.JSON(), nullable=False),
    sa.Column('net_cents', sa.Integer(), nullable=False),
    sa.Column('creator_bps', sa.Integer(), nullable=False),
    sa.Column('creator_pool_cents', sa.Integer(), nullable=False),
    sa.Column('platform_share_cents', sa.Integer(), nullable=False),
    sa.Column('affiliate_cents', sa.Integer(), nullable=False),
    sa.Column('platform_net_cents', sa.Integer(), nullable=False),
    sa.Column('allocations', sa.JSON(), nullable=False),
    sa.Column('explanation', sa.JSON(), nullable=False),
    sa.Column('currency', sa.String(length=3), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['order_line_id'], ['order_lines.id'], name=op.f('fk_royalty_allocations_order_line_id_order_lines'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_royalty_allocations')),
    sa.UniqueConstraint('order_line_id', name=op.f('uq_royalty_allocations_order_line_id'))
    )


def downgrade() -> None:
    op.drop_table('royalty_allocations')
    op.drop_index(op.f('ix_refunds_order_id'), table_name='refunds')
    op.drop_table('refunds')
    op.drop_index(op.f('ix_earnings_payout_id'), table_name='earnings')
    op.drop_index('ix_earnings_payee_status', table_name='earnings')
    op.drop_index(op.f('ix_earnings_order_line_id'), table_name='earnings')
    op.drop_index(op.f('ix_earnings_created_at'), table_name='earnings')
    op.drop_table('earnings')
    op.drop_index(op.f('ix_order_lines_order_id'), table_name='order_lines')
    op.drop_index(op.f('ix_order_lines_creator_id'), table_name='order_lines')
    op.drop_index(op.f('ix_order_lines_asset_id'), table_name='order_lines')
    op.drop_table('order_lines')
    op.drop_index(op.f('ix_payouts_payee_user_id'), table_name='payouts')
    op.drop_table('payouts')
    op.drop_index(op.f('ix_ledger_entries_journal_id'), table_name='ledger_entries')
    op.drop_index('ix_ledger_entries_account', table_name='ledger_entries')
    op.drop_table('ledger_entries')
    op.drop_index(op.f('ix_referrals_referrer_user_id'), table_name='referrals')
    op.drop_table('referrals')
    op.drop_table('referral_codes')
    op.drop_table('reconciliation_runs')
    op.drop_table('payout_accounts')
    op.drop_index('ix_orders_status_created', table_name='orders')
    op.drop_index(op.f('ix_orders_buyer_user_id'), table_name='orders')
    op.drop_table('orders')
    op.drop_index(op.f('ix_ledger_journals_reference_id'), table_name='ledger_journals')
    op.drop_index(op.f('ix_ledger_journals_created_at'), table_name='ledger_journals')
    op.drop_table('ledger_journals')
    op.drop_index(op.f('ix_ledger_accounts_owner_user_id'), table_name='ledger_accounts')
    op.drop_table('ledger_accounts')
    op.drop_index(op.f('ix_financial_events_event_type'), table_name='financial_events')
    op.drop_table('financial_events')
