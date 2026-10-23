"""Gap closure: direct-upload sessions, gallery add-on sales (print options,
orders, items), partial refunds (per-line refunded amount, refund allocations,
several refunds per line), referral creator bonus, booking referral
commissions and refunds after release (milestone release breakdown,
chargeback snapshots), deliverable scan status, guest gallery buyers; new
enum values.

Downgrade note: restoring the old CHECK constraints and NOT NULL columns fails
while rows that use the new values exist (gallery orders, gallery earnings,
referral bonuses, several refunds on one line, deliverables awaiting a scan).
Remove that data first.

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-23 01:33:53.312918
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = '0004'
down_revision: str | None = '0003'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_JOURNAL = ["sale", "refund", "dispute", "dispute_reinstated", "payout", "payout_reversal", "adjustment",
            "service_funding", "service_release", "service_refund"]
_REASONS = ["requested_by_customer", "duplicate", "fraudulent", "rights_issue", "chargeback", "project_canceled",
            "dispute_resolution", "other"]
_EARNINGS = ["stock_license", "affiliate_commission", "service_milestone"]
# (table, column, constraint name, (old values, new values))
ENUM_CHANGES = [
    ("orders", "purpose", "order_purpose", (["license", "milestone"], ["license", "milestone", "gallery"])),
    ("earnings", "kind", "earning_kind", (_EARNINGS, _EARNINGS + ["gallery_sale", "referral_bonus"])),
    ("ledger_journals", "kind", "journal_kind", (_JOURNAL, _JOURNAL + ["gallery_sale", "referral_bonus"])),
    ("refunds", "reason", "refund_reason", (_REASONS, _REASONS[:-1] + ["price_adjustment", "other"])),
]


def _sqlite() -> bool:
    return op.get_bind().dialect.name == "sqlite"


def _replace_enum_check(table: str, column: str, name: str, values: list[str]) -> None:
    constraint = f"ck_{table}_{name}"
    with op.batch_alter_table(table, recreate="always" if _sqlite() else "auto") as b:
        b.drop_constraint(op.f(constraint), type_="check")
        b.create_check_constraint(op.f(constraint), sa.column(column).in_(values))


def upgrade() -> None:
    op.create_table('upload_sessions',
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('purpose', sa.Enum('media', 'deliverable', 'gallery_item', name='upload_purpose', native_enum=False, create_constraint=True, length=40), nullable=False),
    sa.Column('target_id', sa.Uuid(), nullable=True),
    sa.Column('filename', sa.String(length=255), nullable=False),
    sa.Column('content_type', sa.String(length=100), nullable=False),
    sa.Column('declared_size', sa.BigInteger(), nullable=False),
    sa.Column('max_size', sa.BigInteger(), nullable=False),
    sa.Column('storage_key', sa.String(length=500), nullable=False),
    sa.Column('status', sa.Enum('pending', 'consumed', name='upload_status', native_enum=False, create_constraint=True, length=40), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_upload_sessions_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_upload_sessions')),
    sa.UniqueConstraint('storage_key', name=op.f('uq_upload_sessions_storage_key'))
    )
    op.create_index(op.f('ix_upload_sessions_user_id'), 'upload_sessions', ['user_id'], unique=False)
    op.create_table('gallery_print_options',
    sa.Column('gallery_id', sa.Uuid(), nullable=False),
    sa.Column('name', sa.String(length=120), nullable=False),
    sa.Column('price_cents', sa.Integer(), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.CheckConstraint('price_cents >= 100', name=op.f('ck_gallery_print_options_price_minimum')),
    sa.ForeignKeyConstraint(['gallery_id'], ['client_galleries.id'], name=op.f('fk_gallery_print_options_gallery_id_client_galleries'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_gallery_print_options'))
    )
    op.create_index(op.f('ix_gallery_print_options_gallery_id'), 'gallery_print_options', ['gallery_id'], unique=False)
    op.create_table('gallery_orders',
    sa.Column('gallery_id', sa.Uuid(), nullable=False),
    sa.Column('order_id', sa.Uuid(), nullable=False),
    sa.Column('client_name', sa.String(length=200), nullable=False),
    sa.Column('client_email', sa.String(length=320), nullable=False),
    sa.Column('shipping_address', sa.JSON(), nullable=True),
    sa.Column('status', sa.Enum('pending', 'paid', 'shipped', 'partially_refunded', 'refunded', 'disputed', 'canceled', name='gallery_order_status', native_enum=False, create_constraint=True, length=40), nullable=False),
    sa.Column('commission_rule_id', sa.Uuid(), nullable=False),
    sa.Column('allocation', sa.JSON(), nullable=False),
    sa.Column('chargeback_snapshot', sa.JSON(), nullable=True),
    sa.Column('carrier', sa.String(length=60), nullable=True),
    sa.Column('tracking_number', sa.String(length=120), nullable=True),
    sa.Column('shipped_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['commission_rule_id'], ['revenue_share_rules.id'], name=op.f('fk_gallery_orders_commission_rule_id_revenue_share_rules'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['gallery_id'], ['client_galleries.id'], name=op.f('fk_gallery_orders_gallery_id_client_galleries'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['order_id'], ['orders.id'], name=op.f('fk_gallery_orders_order_id_orders'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_gallery_orders')),
    sa.UniqueConstraint('order_id', name=op.f('uq_gallery_orders_order_id'))
    )
    op.create_index(op.f('ix_gallery_orders_gallery_id'), 'gallery_orders', ['gallery_id'], unique=False)
    op.create_table('gallery_order_items',
    sa.Column('gallery_order_id', sa.Uuid(), nullable=False),
    sa.Column('item_id', sa.Uuid(), nullable=False),
    sa.Column('kind', sa.String(length=10), nullable=False),
    sa.Column('print_option_id', sa.Uuid(), nullable=True),
    sa.Column('description', sa.String(length=300), nullable=False),
    sa.Column('quantity', sa.Integer(), nullable=False),
    sa.Column('unit_price_cents', sa.Integer(), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.CheckConstraint('quantity BETWEEN 1 AND 50', name=op.f('ck_gallery_order_items_quantity_range')),
    sa.ForeignKeyConstraint(['gallery_order_id'], ['gallery_orders.id'], name=op.f('fk_gallery_order_items_gallery_order_id_gallery_orders'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['item_id'], ['gallery_items.id'], name=op.f('fk_gallery_order_items_item_id_gallery_items'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['print_option_id'], ['gallery_print_options.id'], name=op.f('fk_gallery_order_items_print_option_id_gallery_print_options'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_gallery_order_items'))
    )
    op.create_index(op.f('ix_gallery_order_items_gallery_order_id'), 'gallery_order_items', ['gallery_order_id'], unique=False)
    # Existing tables: batch mode so SQLite (dev/tests) can alter columns and FKs.
    with op.batch_alter_table("client_galleries") as b:
        b.add_column(sa.Column("download_price_cents", sa.Integer(), nullable=True))
        b.add_column(sa.Column("currency", sa.String(length=3), server_default="USD", nullable=False))
    with op.batch_alter_table("gallery_items") as b:
        b.add_column(sa.Column("download_unlocked", sa.Boolean(), server_default=sa.false(), nullable=False))
    with op.batch_alter_table("deliverables") as b:
        b.add_column(sa.Column("scan_status", sa.String(length=20), server_default="clean", nullable=False))
        b.alter_column("checksum_sha256", existing_type=sa.String(length=64), nullable=True)
    with op.batch_alter_table("earnings") as b:
        b.add_column(sa.Column("order_id", sa.Uuid(), nullable=True))
        b.create_index(op.f("ix_earnings_order_id"), ["order_id"], unique=False)
        b.create_foreign_key(op.f("fk_earnings_order_id_orders"), "orders", ["order_id"], ["id"], ondelete="RESTRICT")
    with op.batch_alter_table("milestones") as b:
        for col in ("reversed_release_cents", "tax_refunded_cents", "release_creator_cents",
                    "release_affiliate_cents", "release_platform_cents"):
            b.add_column(sa.Column(col, sa.Integer(), server_default="0", nullable=False))
        b.add_column(sa.Column("affiliate_user_id", sa.Uuid(), nullable=True))
        b.add_column(sa.Column("chargeback_snapshot", sa.JSON(), nullable=True))
        b.create_foreign_key(op.f("fk_milestones_affiliate_user_id_users"), "users", ["affiliate_user_id"], ["id"],
                             ondelete="RESTRICT")
    with op.batch_alter_table("order_lines") as b:
        b.add_column(sa.Column("refunded_cents", sa.Integer(), server_default="0", nullable=False))
    with op.batch_alter_table("orders") as b:
        b.add_column(sa.Column("buyer_email", sa.String(length=320), nullable=True))
        b.alter_column("buyer_user_id", existing_type=sa.Uuid(), nullable=True)
    with op.batch_alter_table("referrals") as b:
        b.add_column(sa.Column("creator_bonus_paid_at", sa.DateTime(timezone=True), nullable=True))
    with op.batch_alter_table("refunds") as b:
        b.add_column(sa.Column("allocation", sa.JSON(), server_default="{}", nullable=False))
        b.drop_constraint(op.f("uq_refunds_order_line_id"), type_="unique")
        b.create_index(op.f("ix_refunds_order_line_id"), ["order_line_id"], unique=False)
    # Refunds recorded before this revision reversed their whole line.
    op.execute("UPDATE order_lines SET refunded_cents = unit_price_cents + tax_cents WHERE status = 'refunded'")

    for table, column, name, values in ENUM_CHANGES:
        _replace_enum_check(table, column, name, values[1])


def downgrade() -> None:
    for table, column, name, values in ENUM_CHANGES:
        _replace_enum_check(table, column, name, values[0])
    with op.batch_alter_table("refunds") as b:
        b.drop_index(op.f("ix_refunds_order_line_id"))
        b.create_unique_constraint(op.f("uq_refunds_order_line_id"), ["order_line_id"])
        b.drop_column("allocation")
    with op.batch_alter_table("referrals") as b:
        b.drop_column("creator_bonus_paid_at")
    with op.batch_alter_table("orders") as b:
        b.alter_column("buyer_user_id", existing_type=sa.Uuid(), nullable=False)
        b.drop_column("buyer_email")
    with op.batch_alter_table("order_lines") as b:
        b.drop_column("refunded_cents")
    with op.batch_alter_table("milestones") as b:
        b.drop_constraint(op.f("fk_milestones_affiliate_user_id_users"), type_="foreignkey")
        for col in ("chargeback_snapshot", "affiliate_user_id", "release_platform_cents", "release_affiliate_cents",
                    "release_creator_cents", "tax_refunded_cents", "reversed_release_cents"):
            b.drop_column(col)
    with op.batch_alter_table("earnings") as b:
        b.drop_constraint(op.f("fk_earnings_order_id_orders"), type_="foreignkey")
        b.drop_index(op.f("ix_earnings_order_id"))
        b.drop_column("order_id")
    with op.batch_alter_table("deliverables") as b:
        b.alter_column("checksum_sha256", existing_type=sa.String(length=64), nullable=False)
        b.drop_column("scan_status")
    with op.batch_alter_table("gallery_items") as b:
        b.drop_column("download_unlocked")
    with op.batch_alter_table("client_galleries") as b:
        b.drop_column("currency")
        b.drop_column("download_price_cents")
    op.drop_index(op.f('ix_gallery_order_items_gallery_order_id'), table_name='gallery_order_items')
    op.drop_table('gallery_order_items')
    op.drop_index(op.f('ix_gallery_orders_gallery_id'), table_name='gallery_orders')
    op.drop_table('gallery_orders')
    op.drop_index(op.f('ix_gallery_print_options_gallery_id'), table_name='gallery_print_options')
    op.drop_table('gallery_print_options')
    op.drop_index(op.f('ix_upload_sessions_user_id'), table_name='upload_sessions')
    op.drop_table('upload_sessions')
