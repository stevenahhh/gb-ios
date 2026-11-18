"""Add normalized business tables and remove sample wording from inquiries."""

from collections.abc import Sequence
from typing import Final

import sqlalchemy as sa
from alembic import op

revision: Final[str] = "0002"
down_revision: Final[str | None] = "0001"
branch_labels: Final[Sequence[str] | None] = None
depends_on: Final[Sequence[str] | None] = None

SAMPLE_SUFFIX: Final = r" \(가상 고객\)$"
SAMPLE_FACT: Final = "데모 규칙 · 문의 답변 승인으로 예약이 생성되지 않습니다."
REAL_FACT: Final = "예약 안내 · 문의 답변을 승인해도 예약은 자동으로 만들어지지 않습니다."


def upgrade() -> None:
    """Apply this revision."""
    op.create_table(
        "calendar_events",
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("detail", sa.Text(), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("revision", sa.Integer(), server_default="0", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("btrim(title) <> ''"),
        sa.CheckConstraint("kind IN ('booking', 'order', 'delivery', 'todo')"),
        sa.CheckConstraint("revision >= 0"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_calendar_events_starts_at", "calendar_events", ["starts_at"], unique=False)
    op.create_table(
        "channels",
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("handle", sa.Text(), nullable=True),
        sa.Column("connection", sa.Text(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("revision", sa.Integer(), server_default="0", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("connection IN ('not_connected', 'connected')"),
        sa.CheckConstraint("kind IN ('instagram', 'naver_store', 'naver_booking')"),
        sa.CheckConstraint("revision >= 0"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "class_sessions",
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("duration_minutes", sa.Integer(), nullable=False),
        sa.Column("capacity", sa.Integer(), nullable=False),
        sa.Column("deposit_won", sa.Integer(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("revision", sa.Integer(), server_default="0", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("status IN ('scheduled', 'completed', 'cancelled')"),
        sa.CheckConstraint("capacity > 0"),
        sa.CheckConstraint("deposit_won >= 0"),
        sa.CheckConstraint("duration_minutes > 0"),
        sa.CheckConstraint("revision >= 0"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_class_sessions_starts_at", "class_sessions", ["starts_at"], unique=False)
    op.create_table(
        "customers",
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("phone", sa.Text(), nullable=True),
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("revision", sa.Integer(), server_default="0", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("btrim(name) <> ''"),
        sa.CheckConstraint("revision >= 0"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_customers_name", "customers", ["name"], unique=False)
    op.create_table(
        "settings_items",
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("section", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("symbol", sa.Text(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("is_editable", sa.Boolean(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("revision", sa.Integer(), server_default="0", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("revision >= 0"),
        sa.PrimaryKeyConstraint("key"),
    )
    op.create_table(
        "tasks",
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("detail", sa.Text(), nullable=False),
        sa.Column("vendor", sa.Text(), nullable=True),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("revision", sa.Integer(), server_default="0", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("(status = 'done') = (completed_at IS NOT NULL)"),
        sa.CheckConstraint("kind IN ('general', 'material', 'channel')"),
        sa.CheckConstraint("status IN ('open', 'done')"),
        sa.CheckConstraint("revision >= 0"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_tasks_status_due_at", "tasks", ["status", "due_at"], unique=False)
    op.create_table(
        "workshop_profile",
        sa.Column("id", sa.SmallInteger(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("owner_title", sa.Text(), nullable=False),
        sa.Column("phone", sa.Text(), nullable=False),
        sa.Column("address", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("latitude", sa.Double(), nullable=True),
        sa.Column("longitude", sa.Double(), nullable=True),
        sa.Column("revision", sa.Integer(), server_default="0", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("btrim(name) <> ''"),
        sa.CheckConstraint("id = 1"),
        sa.CheckConstraint("revision >= 0"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "bookings",
        sa.Column("session_id", sa.Text(), nullable=False),
        sa.Column("customer_id", sa.Text(), nullable=False),
        sa.Column("channel_id", sa.Text(), nullable=True),
        sa.Column("party_size", sa.Integer(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("deposit_won", sa.Integer(), nullable=False),
        sa.Column("deposit_due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deposit_confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("revision", sa.Integer(), server_default="0", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("status <> 'deposit_pending' OR deposit_due_at IS NOT NULL"),
        sa.CheckConstraint("status IN ('deposit_pending', 'confirmed', 'cancelled')"),
        sa.CheckConstraint("deposit_won >= 0"),
        sa.CheckConstraint("party_size > 0"),
        sa.CheckConstraint("revision >= 0"),
        sa.ForeignKeyConstraint(["channel_id"], ["channels.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["session_id"], ["class_sessions.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_bookings_customer_id", "bookings", ["customer_id"], unique=False)
    op.create_index("ix_bookings_session_id", "bookings", ["session_id"], unique=False)
    op.create_index("ix_bookings_status", "bookings", ["status"], unique=False)
    op.create_table(
        "content_drafts",
        sa.Column("channel_id", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("revision", sa.Integer(), server_default="0", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("btrim(body) <> ''"),
        sa.CheckConstraint("status IN ('draft', 'reviewed')"),
        sa.CheckConstraint("revision >= 0"),
        sa.ForeignKeyConstraint(["channel_id"], ["channels.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_content_drafts_status", "content_drafts", ["status"], unique=False)
    op.create_table(
        "orders",
        sa.Column("order_number", sa.Integer(), nullable=False),
        sa.Column("customer_id", sa.Text(), nullable=False),
        sa.Column("channel_id", sa.Text(), nullable=True),
        sa.Column("product_name", sa.Text(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("amount_won", sa.Integer(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("ordered_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("revision", sa.Integer(), server_default="0", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("status IN ('paid', 'processing', 'completed', 'cancelled')"),
        sa.CheckConstraint("amount_won >= 0"),
        sa.CheckConstraint("order_number > 0"),
        sa.CheckConstraint("quantity > 0"),
        sa.CheckConstraint("revision >= 0"),
        sa.ForeignKeyConstraint(["channel_id"], ["channels.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("order_number"),
    )
    op.create_index("ix_orders_channel_id", "orders", ["channel_id"], unique=False)
    op.create_index("ix_orders_customer_id", "orders", ["customer_id"], unique=False)
    op.create_index("ix_orders_ordered_at", "orders", ["ordered_at"], unique=False)
    op.create_index("ix_orders_status", "orders", ["status"], unique=False)
    op.create_table(
        "assistant_recommendations",
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("source_name", sa.Text(), nullable=True),
        sa.Column("draft_id", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("revision", sa.Integer(), server_default="0", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("kind IN ('seat_promotion', 'deposit_reminder', 'opportunity')"),
        sa.CheckConstraint("status IN ('open', 'acknowledged')"),
        sa.CheckConstraint("revision >= 0"),
        sa.ForeignKeyConstraint(["draft_id"], ["content_drafts.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_recommendations_status", "assistant_recommendations", ["status"], unique=False)
    op.create_table(
        "shipments",
        sa.Column("order_id", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("ship_by_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("handling_note", sa.Text(), nullable=True),
        sa.Column("carrier", sa.Text(), nullable=True),
        sa.Column("tracking_number", sa.Text(), nullable=True),
        sa.Column("packed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("shipped_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expected_arrival_on", sa.Date(), nullable=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("revision", sa.Integer(), server_default="0", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("status IN ('packing', 'invoice_pending', 'in_transit', 'delivered')"),
        sa.CheckConstraint(
            (
                "status NOT IN ('in_transit', 'delivered') "
                "OR (carrier IS NOT NULL AND tracking_number IS NOT NULL)"
            ),
        ),
        sa.CheckConstraint("revision >= 0"),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("order_id"),
    )
    op.create_index("ix_shipments_status_ship_by", "shipments", ["status", "ship_by_at"], unique=False)
    op.add_column("inquiries", sa.Column("customer_id", sa.Text(), nullable=True))
    op.add_column("inquiries", sa.Column("channel_id", sa.Text(), nullable=True))
    op.add_column(
        "inquiries",
        sa.Column("received_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.add_column(
        "inquiries",
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.add_column(
        "inquiries",
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_inquiries_channel_id", "inquiries", ["channel_id"], unique=False)
    op.create_index("ix_inquiries_status", "inquiries", ["status"], unique=False)
    op.create_foreign_key(None, "inquiries", "channels", ["channel_id"], ["id"], ondelete="SET NULL")
    op.create_foreign_key(None, "inquiries", "customers", ["customer_id"], ["id"], ondelete="SET NULL")
    # These fields are never user-editable, so drafts, decisions and revisions stay untouched.
    op.execute(
        sa.text(
            "UPDATE inquiries SET customer = regexp_replace(customer, :suffix, ''), "
            "facts = array_replace(facts, :old_fact, :new_fact)",
        ).bindparams(suffix=SAMPLE_SUFFIX, old_fact=SAMPLE_FACT, new_fact=REAL_FACT),
    )


def downgrade() -> None:
    """Revert this revision."""
    op.drop_index("ix_inquiries_status", table_name="inquiries")
    op.drop_index("ix_inquiries_channel_id", table_name="inquiries")
    op.drop_column("inquiries", "updated_at")
    op.drop_column("inquiries", "created_at")
    op.drop_column("inquiries", "received_at")
    op.drop_column("inquiries", "channel_id")
    op.drop_column("inquiries", "customer_id")
    op.drop_index("ix_shipments_status_ship_by", table_name="shipments")
    op.drop_table("shipments")
    op.drop_index("ix_recommendations_status", table_name="assistant_recommendations")
    op.drop_table("assistant_recommendations")
    op.drop_index("ix_orders_status", table_name="orders")
    op.drop_index("ix_orders_ordered_at", table_name="orders")
    op.drop_index("ix_orders_customer_id", table_name="orders")
    op.drop_index("ix_orders_channel_id", table_name="orders")
    op.drop_table("orders")
    op.drop_index("ix_content_drafts_status", table_name="content_drafts")
    op.drop_table("content_drafts")
    op.drop_index("ix_bookings_status", table_name="bookings")
    op.drop_index("ix_bookings_session_id", table_name="bookings")
    op.drop_index("ix_bookings_customer_id", table_name="bookings")
    op.drop_table("bookings")
    op.drop_table("workshop_profile")
    op.drop_index("ix_tasks_status_due_at", table_name="tasks")
    op.drop_table("tasks")
    op.drop_table("settings_items")
    op.drop_index("ix_customers_name", table_name="customers")
    op.drop_table("customers")
    op.drop_index("ix_class_sessions_starts_at", table_name="class_sessions")
    op.drop_table("class_sessions")
    op.drop_table("channels")
    op.drop_index("ix_calendar_events_starts_at", table_name="calendar_events")
    op.drop_table("calendar_events")
