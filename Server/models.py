"""Normalized business tables; display values are always derived from these rows."""

from datetime import UTC, date, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Double,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from database import Base

type TableArgs = tuple[CheckConstraint | Index | UniqueConstraint, ...]
REVISION_CHECK = "revision >= 0"


def utc_now() -> datetime:
    """Timestamp application updates without reloading server defaults."""
    return datetime.now(UTC)


def timestamp(*, nullable: bool = False) -> Mapped[datetime]:
    """Declare a timezone-aware column."""
    return mapped_column(DateTime(timezone=True), nullable=nullable)


class Audited:
    """Optimistic-concurrency revision and audit timestamps."""

    revision: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=utc_now,
    )


class Entity(Audited):
    """A row addressed by a stable text identifier."""

    id: Mapped[str] = mapped_column(Text, primary_key=True)


class WorkshopRow(Audited, Base):
    """The single workshop operated by this deployment."""

    __tablename__: str = "workshop_profile"
    __table_args__: TableArgs = (
        CheckConstraint("id = 1"), CheckConstraint("btrim(name) <> ''"), CheckConstraint(REVISION_CHECK),
    )
    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True, default=1)
    name: Mapped[str] = mapped_column(Text)
    owner_title: Mapped[str] = mapped_column(Text)
    phone: Mapped[str] = mapped_column(Text)
    address: Mapped[str] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text)
    latitude: Mapped[float | None] = mapped_column(Double)
    longitude: Mapped[float | None] = mapped_column(Double)


class CustomerRow(Entity, Base):
    """A person who books classes, buys products, or asks questions."""

    __tablename__: str = "customers"
    __table_args__: TableArgs = (
        CheckConstraint("btrim(name) <> ''"), CheckConstraint(REVISION_CHECK),
        Index("ix_customers_name", "name"),
    )
    name: Mapped[str] = mapped_column(Text)
    phone: Mapped[str | None] = mapped_column(Text)


class ChannelRow(Entity, Base):
    """A sales or marketing channel; connection records real integration state."""

    __tablename__: str = "channels"
    __table_args__: TableArgs = (
        CheckConstraint("kind IN ('instagram', 'naver_store', 'naver_booking')"),
        CheckConstraint("connection IN ('not_connected', 'connected')"),
        CheckConstraint(REVISION_CHECK),
    )
    kind: Mapped[str] = mapped_column(Text)
    name: Mapped[str] = mapped_column(Text)
    handle: Mapped[str | None] = mapped_column(Text)
    connection: Mapped[str] = mapped_column(Text)
    sort_order: Mapped[int] = mapped_column(Integer)


class ClassSessionRow(Entity, Base):
    """One scheduled class that bookings reserve seats in."""

    __tablename__: str = "class_sessions"
    __table_args__: TableArgs = (
        CheckConstraint("duration_minutes > 0"), CheckConstraint("capacity > 0"),
        CheckConstraint("deposit_won >= 0"),
        CheckConstraint("status IN ('scheduled', 'completed', 'cancelled')"),
        CheckConstraint(REVISION_CHECK), Index("ix_class_sessions_starts_at", "starts_at"),
    )
    title: Mapped[str] = mapped_column(Text)
    starts_at: Mapped[datetime] = timestamp()
    duration_minutes: Mapped[int] = mapped_column(Integer)
    capacity: Mapped[int] = mapped_column(Integer)
    deposit_won: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(Text)


class BookingRow(Entity, Base):
    """A customer's seats in one class session."""

    __tablename__: str = "bookings"
    __table_args__: TableArgs = (
        CheckConstraint("party_size > 0"), CheckConstraint("deposit_won >= 0"),
        CheckConstraint("status IN ('deposit_pending', 'confirmed', 'cancelled')"),
        CheckConstraint("status <> 'deposit_pending' OR deposit_due_at IS NOT NULL"),
        CheckConstraint(REVISION_CHECK),
        Index("ix_bookings_session_id", "session_id"), Index("ix_bookings_status", "status"),
        Index("ix_bookings_customer_id", "customer_id"),
    )
    session_id: Mapped[str] = mapped_column(ForeignKey("class_sessions.id", ondelete="RESTRICT"))
    customer_id: Mapped[str] = mapped_column(ForeignKey("customers.id", ondelete="RESTRICT"))
    channel_id: Mapped[str | None] = mapped_column(ForeignKey("channels.id", ondelete="SET NULL"))
    party_size: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(Text)
    deposit_won: Mapped[int] = mapped_column(Integer)
    deposit_due_at: Mapped[datetime | None] = timestamp(nullable=True)
    deposit_confirmed_at: Mapped[datetime | None] = timestamp(nullable=True)


class OrderRow(Entity, Base):
    """A paid product order."""

    __tablename__: str = "orders"
    __table_args__: TableArgs = (
        UniqueConstraint("order_number"), CheckConstraint("order_number > 0"),
        CheckConstraint("quantity > 0"), CheckConstraint("amount_won >= 0"),
        CheckConstraint("status IN ('paid', 'processing', 'completed', 'cancelled')"),
        CheckConstraint(REVISION_CHECK),
        Index("ix_orders_ordered_at", "ordered_at"), Index("ix_orders_status", "status"),
        Index("ix_orders_customer_id", "customer_id"), Index("ix_orders_channel_id", "channel_id"),
    )
    order_number: Mapped[int] = mapped_column(Integer)
    customer_id: Mapped[str] = mapped_column(ForeignKey("customers.id", ondelete="RESTRICT"))
    channel_id: Mapped[str | None] = mapped_column(ForeignKey("channels.id", ondelete="SET NULL"))
    product_name: Mapped[str] = mapped_column(Text)
    quantity: Mapped[int] = mapped_column(Integer)
    amount_won: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(Text)
    ordered_at: Mapped[datetime] = timestamp()
    confirmed_at: Mapped[datetime | None] = timestamp(nullable=True)


class ShipmentRow(Entity, Base):
    """Fulfilment state of one confirmed order."""

    __tablename__: str = "shipments"
    __table_args__: TableArgs = (
        UniqueConstraint("order_id"),
        CheckConstraint("status IN ('packing', 'invoice_pending', 'in_transit', 'delivered')"),
        CheckConstraint(
            (
                "status NOT IN ('in_transit', 'delivered') "
                "OR (carrier IS NOT NULL AND tracking_number IS NOT NULL)"
            ),
        ),
        CheckConstraint(REVISION_CHECK), Index("ix_shipments_status_ship_by", "status", "ship_by_at"),
    )
    order_id: Mapped[str] = mapped_column(ForeignKey("orders.id", ondelete="RESTRICT"))
    status: Mapped[str] = mapped_column(Text)
    ship_by_at: Mapped[datetime] = timestamp()
    handling_note: Mapped[str | None] = mapped_column(Text)
    carrier: Mapped[str | None] = mapped_column(Text)
    tracking_number: Mapped[str | None] = mapped_column(Text)
    packed_at: Mapped[datetime | None] = timestamp(nullable=True)
    shipped_at: Mapped[datetime | None] = timestamp(nullable=True)
    expected_arrival_on: Mapped[date | None] = mapped_column(Date)
    delivered_at: Mapped[datetime | None] = timestamp(nullable=True)


class ContentDraftRow(Entity, Base):
    """A promotional post waiting for the owner's review."""

    __tablename__: str = "content_drafts"
    __table_args__: TableArgs = (
        CheckConstraint("status IN ('draft', 'reviewed')"), CheckConstraint("btrim(body) <> ''"),
        CheckConstraint(REVISION_CHECK), Index("ix_content_drafts_status", "status"),
    )
    channel_id: Mapped[str] = mapped_column(ForeignKey("channels.id", ondelete="RESTRICT"))
    title: Mapped[str] = mapped_column(Text)
    summary: Mapped[str] = mapped_column(Text)
    body: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text)
    reviewed_at: Mapped[datetime | None] = timestamp(nullable=True)


class TaskRow(Entity, Base):
    """Owner work: general to-dos, material orders, and channel chores."""

    __tablename__: str = "tasks"
    __table_args__: TableArgs = (
        CheckConstraint("kind IN ('general', 'material', 'channel')"),
        CheckConstraint("status IN ('open', 'done')"),
        CheckConstraint("(status = 'done') = (completed_at IS NOT NULL)"),
        CheckConstraint(REVISION_CHECK), Index("ix_tasks_status_due_at", "status", "due_at"),
    )
    kind: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text)
    detail: Mapped[str] = mapped_column(Text)
    vendor: Mapped[str | None] = mapped_column(Text)
    due_at: Mapped[datetime] = timestamp()
    status: Mapped[str] = mapped_column(Text)
    completed_at: Mapped[datetime | None] = timestamp(nullable=True)


class CalendarEventRow(Entity, Base):
    """An owner-added schedule entry not derivable from other tables."""

    __tablename__: str = "calendar_events"
    __table_args__: TableArgs = (
        CheckConstraint("kind IN ('booking', 'order', 'delivery', 'todo')"),
        CheckConstraint("btrim(title) <> ''"), CheckConstraint(REVISION_CHECK),
        Index("ix_calendar_events_starts_at", "starts_at"),
    )
    kind: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text)
    detail: Mapped[str] = mapped_column(Text)
    starts_at: Mapped[datetime] = timestamp()


class RecommendationRow(Entity, Base):
    """A suggestion; counts in its text are computed when it is read."""

    __tablename__: str = "assistant_recommendations"
    __table_args__: TableArgs = (
        CheckConstraint("kind IN ('seat_promotion', 'deposit_reminder', 'opportunity')"),
        CheckConstraint("status IN ('open', 'acknowledged')"),
        CheckConstraint(REVISION_CHECK), Index("ix_recommendations_status", "status"),
    )
    kind: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text)
    body: Mapped[str] = mapped_column(Text)
    source_name: Mapped[str | None] = mapped_column(Text)
    draft_id: Mapped[str | None] = mapped_column(ForeignKey("content_drafts.id", ondelete="SET NULL"))
    status: Mapped[str] = mapped_column(Text)
    acknowledged_at: Mapped[datetime | None] = timestamp(nullable=True)


class SettingItemRow(Audited, Base):
    """Owner-maintained policy and guidance text."""

    __tablename__: str = "settings_items"
    __table_args__: TableArgs = (CheckConstraint(REVISION_CHECK),)
    key: Mapped[str] = mapped_column(Text, primary_key=True)
    section: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text)
    symbol: Mapped[str] = mapped_column(Text)
    body: Mapped[str] = mapped_column(Text)
    is_editable: Mapped[bool] = mapped_column(Boolean)
    sort_order: Mapped[int] = mapped_column(Integer)


class InquiryRow(Base):
    """Customer inquiry; all application writes hold its transaction row lock."""

    __tablename__: str = "inquiries"
    __table_args__: TableArgs = (
        CheckConstraint("status IN ('pending', 'approved', 'rejected')"),
        CheckConstraint(REVISION_CHECK), Index("ix_inquiries_status", "status"),
        Index("ix_inquiries_channel_id", "channel_id"),
    )
    id: Mapped[str] = mapped_column(Text, primary_key=True)
    customer: Mapped[str] = mapped_column(Text)
    subject: Mapped[str] = mapped_column(Text)
    question: Mapped[str] = mapped_column(Text)
    facts: Mapped[list[str]] = mapped_column(ARRAY(Text))
    draft: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text)
    revision: Mapped[int] = mapped_column(Integer)
    customer_id: Mapped[str | None] = mapped_column(ForeignKey("customers.id", ondelete="SET NULL"))
    channel_id: Mapped[str | None] = mapped_column(ForeignKey("channels.id", ondelete="SET NULL"))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=utc_now,
    )
