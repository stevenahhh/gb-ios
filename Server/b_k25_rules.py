"""Reusable owner rules (K25): saved from an owner's answer, shown on the class card, and retired by hand."""

from datetime import datetime
from uuid import uuid4

from fastapi import APIRouter, HTTPException
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from b_k25_tables import FactCardRow, OwnerRuleRow
from common import Session
from contracts import ApiModel

router = APIRouter()


class RuleView(ApiModel):
    """One saved rule and the class it belongs to; no class means the whole workshop."""

    id: str
    card_id: str | None
    class_name: str | None
    rule_text: str
    question_summary: str
    created_at: datetime


async def rule_views(db: AsyncSession) -> list[RuleView]:
    """Every rule the owner still uses, newest first."""
    rows = await db.execute(
        select(OwnerRuleRow, FactCardRow.class_name)
        .outerjoin(FactCardRow, FactCardRow.id == OwnerRuleRow.card_id)
        .where(OwnerRuleRow.retired_at.is_(None)).order_by(OwnerRuleRow.created_at.desc()),
    )
    return [
        RuleView(
            id=rule.id, card_id=rule.card_id, class_name=name, rule_text=rule.rule_text,
            question_summary=rule.question_summary, created_at=rule.created_at,
        )
        for rule, name in rows.tuples()
    ]


async def card_for_rule(db: AsyncSession, class_name: str, card_id: str) -> str:
    """Return the card of a class, creating an empty one so the rule has a place to show."""
    _ = await db.execute(
        insert(FactCardRow).values(id=card_id, class_name=class_name, revision=1)
        .on_conflict_do_nothing(index_elements=[FactCardRow.class_name]),
    )
    found = await db.scalar(select(FactCardRow.id).where(FactCardRow.class_name == class_name))
    if found is None:
        raise HTTPException(409, "card conflicts with another class")
    return found


async def save_rule(
    db: AsyncSession, card_id: str | None, text: str, source: tuple[str, str | None], now: datetime,
) -> str:
    """Store one reusable sentence and return its id."""
    question_summary, inquiry_id = source
    rule_id = f"rule-{uuid4().hex}"
    db.add(OwnerRuleRow(
        id=rule_id, card_id=card_id, question_summary=question_summary, rule_text=text,
        source_inquiry_id=inquiry_id, created_at=now,
    ))
    await db.flush()
    return rule_id


@router.get("/owner-rules")
async def list_rules(db: Session) -> list[RuleView]:
    """Return every saved rule, for the fact card screens."""
    return await rule_views(db)


@router.delete("/owner-rules/{rule_id}")
async def retire_rule(rule_id: str, db: Session) -> RuleView:
    """Retire one rule; it stays in the history but no draft uses it again."""
    row = await db.get(OwnerRuleRow, rule_id, with_for_update=True)
    if row is None or row.retired_at is not None:
        raise HTTPException(404, "resource not found")
    name = None
    if row.card_id is not None:
        card = await db.get(FactCardRow, row.card_id)
        name = None if card is None else card.class_name
    row.retired_at = datetime.now().astimezone()
    await db.flush()
    return RuleView(
        id=row.id, card_id=row.card_id, class_name=name, rule_text=row.rule_text,
        question_summary=row.question_summary, created_at=row.created_at,
    )
