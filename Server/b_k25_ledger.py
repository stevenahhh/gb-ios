"""Read what a grounded reply may rely on from PostgreSQL, in one short transaction."""

from datetime import datetime
from typing import Final

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from b_k25_claims import CardFact, Ledger, RuleFact, SessionFact
from b_k25_prompts import masked_question
from b_k25_tables import FactCardRow, JudgmentRow, OwnerRuleRow
from bookings import seats_taken
from display import local
from models import ClassSessionRow, InquiryRow, SettingItemRow

UPCOMING_LIMIT: Final = 100


def card_fact(row: FactCardRow) -> CardFact:
    """Describe one stored fact card; blank columns stay None."""
    return CardFact(
        class_name=row.class_name, duration_minutes=row.duration_minutes, capacity=row.capacity,
        included_materials=row.included_materials, parking=row.parking, refund_policy=row.refund_policy,
        price_won=row.price_won, deposit_won=row.deposit_won,
    )


async def upcoming_sessions(db: AsyncSession, now: datetime) -> tuple[SessionFact, ...]:
    """Scheduled classes still ahead, with the seats each has left."""
    rows = await db.execute(
        select(ClassSessionRow, seats_taken())
        .where(ClassSessionRow.status == "scheduled", ClassSessionRow.starts_at > now)
        .order_by(ClassSessionRow.starts_at, ClassSessionRow.id).limit(UPCOMING_LIMIT),
    )
    return tuple(
        SessionFact(
            title=row.title, starts_at=local(row.starts_at), capacity=row.capacity,
            seats_left=max(row.capacity - taken, 0), deposit_won=row.deposit_won,
            duration_minutes=row.duration_minutes,
        )
        for row, taken in rows.tuples()
    )


async def saved_cards(db: AsyncSession) -> tuple[CardFact, ...]:
    """Every fact card the owner confirmed."""
    rows = await db.scalars(select(FactCardRow).order_by(FactCardRow.class_name))
    return tuple(card_fact(row) for row in rows)


async def active_rules(db: AsyncSession) -> tuple[RuleFact, ...]:
    """Rules the owner still uses, newest first, with the class they belong to."""
    rows = await db.execute(
        select(OwnerRuleRow.rule_text, FactCardRow.class_name)
        .outerjoin(FactCardRow, FactCardRow.id == OwnerRuleRow.card_id)
        .where(OwnerRuleRow.retired_at.is_(None)).order_by(OwnerRuleRow.created_at.desc()),
    )
    return tuple(RuleFact(text=text, class_name=name) for text, name in rows.tuples())


async def written_policies(db: AsyncSession) -> tuple[str, ...]:
    """Read the workshop's editable guidance, as the existing draft prompt does."""
    rows = await db.scalars(
        select(SettingItemRow).where(SettingItemRow.is_editable).order_by(SettingItemRow.sort_order),
    )
    return tuple(f"{row.title}: {row.body}" for row in rows)


async def asked_text(db: AsyncSession, inquiry_id: str, question: str) -> str:
    """Join the customer's question with what the owner already decided about it."""
    rows = await db.execute(
        select(JudgmentRow.issue, JudgmentRow.answer_text)
        .where(JudgmentRow.inquiry_id == inquiry_id).order_by(JudgmentRow.created_at),
    )
    parts = [part for issue, answer in rows.tuples() for part in (issue, answer) if part]
    return "\n".join([question, *parts])


async def load_ledger(db: AsyncSession, inquiry: InquiryRow, now: datetime) -> Ledger:
    """Collect the classes, cards, rules, and notes one inquiry's reply may use."""
    question = masked_question(inquiry.customer, inquiry.subject, inquiry.question)
    return Ledger(
        today=now.date(), sessions=await upcoming_sessions(db, now), cards=await saved_cards(db),
        rules=await active_rules(db), facts=tuple(inquiry.facts),
        policies=await written_policies(db), question=question,
        asked=await asked_text(db, inquiry.id, question),
    )
