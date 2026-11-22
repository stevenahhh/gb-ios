"""Feed collected items into the business tables the app already reads.

Rules: a collected row is inserted once under a fixed id; an existing one is updated only while its
revision is 0, so anything the owner touched stays. Seed inquiries and seed orders of a channel stay until
the first real row of the same kind arrives for that channel; then the untouched seed rows (revision 0) are
removed. The seed command applies the same rule, so a later deploy does not bring them back.
"""

from datetime import date, datetime, timedelta
from hashlib import sha256
from typing import Final, NamedTuple

from sqlalchemy import delete, exists, func, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from collectors.base import SourceId
from display import day_start
from models import ChannelRow, CollectedItemRow, CustomerRow, InquiryRow, OrderRow, ShipmentRow
from seed_data import INSTAGRAM, STORE, build_seed

BLOG: Final = "channel-naver-blog"
INQUIRY_PREFIX: Final = "inquiry-collected-"
ORDER_PREFIX: Final = "order-collected-"
ORDER_NUMBER_LOCK: Final = 7_277_041_219
RECENT: Final = timedelta(days=7)
MAX_QUESTION: Final = 2000
ASKING: Final = ("?", "\uff1f", "문의", "가격", "얼마", "예약", "가능", "언제", "어디", "어떻게")
ORDER_STATES: Final = {
    "DELIVERING": "processing", "DELIVERED": "completed", "PURCHASE_DECIDED": "completed",
    "EXCHANGED": "completed", "CANCELED": "cancelled", "RETURNED": "cancelled",
    "CANCELED_BY_NOPAYMENT": "cancelled",
}


class SourceChannel(NamedTuple):
    """The channel row one source fills."""

    id: str
    kind: str
    name: str
    sort_order: int


SOURCE_CHANNELS: Final[dict[str, SourceChannel]] = {
    "instagram": SourceChannel(INSTAGRAM, "instagram", "Instagram", 1),
    "naver_smartstore": SourceChannel(STORE, "naver_store", "네이버 스마트스토어", 2),
    "naver_blog": SourceChannel(BLOG, "naver_blog", "네이버 블로그", 4),
}


def raw_text(row: CollectedItemRow, key: str) -> str:
    """Read a string from the stored source JSON."""
    value = row.raw.get(key)
    return value if isinstance(value, str) else ""


def raw_number(row: CollectedItemRow, key: str) -> int:
    """Read a whole number from the stored source JSON."""
    value = row.raw.get(key)
    return value if isinstance(value, int) else 0


def row_id(prefix: str, row: CollectedItemRow) -> str:
    """Build the fixed business id of one collected item."""
    return f"{prefix}{row.source_id}-{row.external_id.replace(':', '-')}"


async def connect_channel(db: AsyncSession, source: SourceId) -> None:
    """Show the channel as connected; its name and handle are never overwritten."""
    channel = SOURCE_CHANNELS.get(source)
    if channel is None:
        return
    _ = await db.execute(insert(ChannelRow).values(
        id=channel.id, kind=channel.kind, name=channel.name, handle=None, connection="connected",
        sort_order=channel.sort_order,
    ).on_conflict_do_nothing())
    await set_connection(db, channel.id, "connected")


async def disconnect_channel(db: AsyncSession, source: SourceId) -> None:
    """Show the source's own channel as not connected; other channels are never touched."""
    channel = SOURCE_CHANNELS.get(source)
    if channel is not None:
        await set_connection(db, channel.id, "not_connected")


async def set_connection(db: AsyncSession, channel_id: str, connection: str) -> None:
    """Change the recorded integration state once."""
    _ = await db.execute(
        update(ChannelRow).where(ChannelRow.id == channel_id, ChannelRow.connection != connection)
        .values(connection=connection, revision=ChannelRow.revision + 1),
    )


async def map_customer(db: AsyncSession, row: CollectedItemRow) -> str:
    """Find or add the buyer; an existing name is kept."""
    key = raw_text(row, "customerKey") or sha256(row.external_id.encode()).hexdigest()[:24]
    customer_id = f"customer-collected-{key}"
    _ = await db.execute(insert(CustomerRow).values(
        id=customer_id, name=(row.author or "").strip() or "스마트스토어 고객", phone=None,
    ).on_conflict_do_nothing())
    return customer_id


async def map_inquiry(
    db: AsyncSession, row: CollectedItemRow, channel: SourceChannel, customer_id: str | None,
) -> None:
    """Add a waiting inquiry once; a reply written on the platform closes it only while untouched."""
    inquiry_id = row_id(INQUIRY_PREFIX, row)
    answered = row.raw.get("answered") is True
    answer = raw_text(row, "answer") if answered else ""
    product = raw_text(row, "productName")
    _ = await db.execute(insert(InquiryRow).values(
        id=inquiry_id, customer=row.author or "고객", subject=row.title or "문의",
        question=row.body[:MAX_QUESTION], draft=answer, status="approved" if answered else "pending",
        facts=[f"문의 채널 · {channel.name}", *([f"문의 상품 · {product}"] if product else [])],
        revision=0, customer_id=customer_id, channel_id=channel.id, received_at=row.published_at,
    ).on_conflict_do_nothing())
    if answered:
        _ = await db.execute(
            update(InquiryRow)
            .where(InquiryRow.id == inquiry_id, InquiryRow.revision == 0, InquiryRow.status == "pending")
            .values(status="approved", draft=answer, revision=1),
        )


def order_state(row: CollectedItemRow) -> str | None:
    """Translate the store's order state; an unpaid order has none yet."""
    status = raw_text(row, "productOrderStatus")
    if status == "PAYED":
        return "processing" if raw_text(row, "placeOrderStatus") == "OK" else "paid"
    return ORDER_STATES.get(status)


async def map_order(db: AsyncSession, row: CollectedItemRow, channel: SourceChannel, now: datetime) -> None:
    """Add an order once and follow the store's state while the owner has not touched it."""
    state = order_state(row)
    quantity = raw_number(row, "quantity")
    if state is None or row.published_at is None or quantity < 1:
        return
    order_id = row_id(ORDER_PREFIX, row)
    confirmed = now if state in {"processing", "completed"} else None
    current = await db.scalar(select(OrderRow).where(OrderRow.id == order_id).with_for_update())
    if current is not None:
        if current.revision == 0 and current.status != state:
            current.status = state
            current.confirmed_at = current.confirmed_at or confirmed
        return
    customer_id = await map_customer(db, row)
    _ = await db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": ORDER_NUMBER_LOCK})
    number = (await db.scalar(select(func.coalesce(func.max(OrderRow.order_number), 0)))) or 0
    db.add(OrderRow(
        id=order_id, order_number=number + 1, customer_id=customer_id, channel_id=channel.id,
        product_name=row.title or "상품", quantity=quantity,
        amount_won=max(raw_number(row, "totalPaymentAmount"), 0), status=state,
        ordered_at=row.published_at, confirmed_at=confirmed,
    ))
    await db.flush()


def is_question(row: CollectedItemRow) -> bool:
    """Treat a comment as an inquiry when it asks something and the owner did not write it."""
    owner = raw_text(row, "owner")
    return row.author != owner and any(word in row.body for word in ASKING)


async def map_items(db: AsyncSession, source: SourceId, now: datetime) -> int:
    """Apply every item not yet reflected, oldest first, then retire matching seed rows."""
    rows = (await db.scalars(
        select(CollectedItemRow)
        .where(CollectedItemRow.source_id == source, CollectedItemRow.mapped.is_(False))
        .order_by(CollectedItemRow.published_at, CollectedItemRow.id).with_for_update(),
    )).all()
    channel = SOURCE_CHANNELS.get(source)
    applied = 0
    for row in rows:
        if channel is not None:
            match row.kind:
                case "order":
                    await map_order(db, row, channel, now)
                case "inquiry":
                    await map_inquiry(db, row, channel, await map_customer(db, row))
                case "comment" if is_question(row):
                    await map_inquiry(db, row, channel, None)
                case _:
                    pass
        row.mapped = True
        applied += 1
    await db.flush()
    _ = await retire_seed_rows(db, now.date())
    return applied


async def retire_seed_rows(db: AsyncConnection | AsyncSession, today: date) -> int:
    """Remove untouched seed inquiries and orders of channels that now have real ones."""
    ids = {model: [str(row["id"]) for row in rows] for model, rows in build_seed(today) if rows[0].get("id")}
    real_inquiry = (
        select(InquiryRow.channel_id)
        .where(InquiryRow.id.startswith(INQUIRY_PREFIX), InquiryRow.channel_id.is_not(None))
    )
    inquiries = await db.execute(delete(InquiryRow).where(
        InquiryRow.id.in_(ids[InquiryRow]), InquiryRow.revision == 0, InquiryRow.channel_id.in_(real_inquiry),
    ).returning(InquiryRow.id))
    real_order = (
        select(OrderRow.channel_id)
        .where(OrderRow.id.startswith(ORDER_PREFIX), OrderRow.channel_id.is_not(None))
    )
    seed_orders = select(OrderRow.id).where(
        OrderRow.id.in_(ids[OrderRow]), OrderRow.revision == 0, OrderRow.channel_id.in_(real_order),
    )
    shipments = await db.execute(delete(ShipmentRow).where(
        ShipmentRow.id.in_(ids[ShipmentRow]), ShipmentRow.revision == 0,
        ShipmentRow.order_id.in_(seed_orders),
    ).returning(ShipmentRow.id))
    orders = await db.execute(delete(OrderRow).where(
        OrderRow.id.in_(seed_orders), ~exists().where(ShipmentRow.order_id == OrderRow.id),
    ).returning(OrderRow.id))
    return len(inquiries.all()) + len(shipments.all()) + len(orders.all())


async def recent_posts(db: AsyncSession, today: date) -> dict[str, int]:
    """Count collected posts of the last seven days by channel."""
    rows = await db.execute(
        select(CollectedItemRow.source_id, func.count())
        .where(CollectedItemRow.kind == "post", CollectedItemRow.published_at >= day_start(today) - RECENT)
        .group_by(CollectedItemRow.source_id),
    )
    return {
        SOURCE_CHANNELS[source].id: total for source, total in rows.tuples() if source in SOURCE_CHANNELS
    }
