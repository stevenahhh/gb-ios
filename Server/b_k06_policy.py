"""Refund rule versions and the moment each booking was told about one."""

from datetime import date, datetime
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, HTTPException
from pydantic import Field, TypeAdapter
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from b_k06_ai import Source, read_policy
from b_k06_logic import LateRule, Policy, Rule, change_summary, policy_summary, rule_label
from b_k06_models import WORKSHOP_ID, PolicyNoticeRow, PolicyVersionRow
from common import MAX_TEXT, Now, Session, ShortText, required_text
from contracts import ApiModel, ApiRequest
from display import local
from models import BookingRow

router = APIRouter()
RULES: TypeAdapter[list[Rule]] = TypeAdapter(list[Rule])
type SourceText = Annotated[str, Field(min_length=1, max_length=MAX_TEXT)]


class PolicyText(ApiRequest):
    """Rule text the owner dictated or pasted."""

    text: SourceText


class PolicyDraft(ApiModel):
    """A rule table for the owner to check before saving."""

    rules: list[Rule]
    late: LateRule | None
    unread: list[str]
    source: Source


class PolicySave(ApiRequest):
    """The table the owner approved."""

    rules: Annotated[list[Rule], Field(min_length=1, max_length=20)]
    late: LateRule | None = None
    unread: Annotated[list[ShortText], Field(max_length=20, default_factory=list)]
    source_text: SourceText


class PolicyVersion(ApiModel):
    """One saved version."""

    version: int
    approved_at: str
    rules: list[Rule]
    labels: list[str]
    late: LateRule | None
    unread: list[str]
    change: str
    summary: str


class NoticeRequest(ApiRequest):
    """The booking whose confirmation carries the rule summary."""

    booking_id: ShortText


class Notice(ApiModel):
    """The copied summary and when it was recorded."""

    version: int
    noticed_at: str
    summary: str


def iso(moment: datetime) -> str:
    """Send a moment in workshop time."""
    return local(moment).isoformat(timespec="seconds")


def policy_of(row: PolicyVersionRow) -> Policy:
    """Read stored JSON back into the calculator's types."""
    late = LateRule.model_validate(row.late) if row.late is not None else None
    return Policy(tuple(RULES.validate_python(row.rules)), late, tuple(row.unread))


def version_view(row: PolicyVersionRow, before: PolicyVersionRow | None) -> PolicyVersion:
    """Present one version and what changed in it."""
    policy = policy_of(row)
    return PolicyVersion(
        version=row.version, approved_at=iso(row.approved_at), rules=list(policy.rules),
        labels=[rule_label(rule) for rule in policy.rules], late=policy.late, unread=list(policy.unread),
        change=change_summary(policy_of(before) if before else None, policy),
        summary=policy_summary(policy.rules, policy.late),
    )


async def latest_policy(db: AsyncSession) -> PolicyVersionRow | None:
    """Read the newest version."""
    return await db.scalar(
        select(PolicyVersionRow).where(PolicyVersionRow.workshop_id == WORKSHOP_ID)
        .order_by(PolicyVersionRow.version.desc()).limit(1),
    )


async def noticed_policy(
    db: AsyncSession, booking_id: str, at: datetime,
) -> tuple[PolicyVersionRow, date] | None:
    """Read the last version this booking was told about before the moment."""
    row = (
        await db.execute(
            select(PolicyVersionRow, PolicyNoticeRow.noticed_at)
            .join(PolicyNoticeRow, PolicyNoticeRow.policy_version_id == PolicyVersionRow.id)
            .where(PolicyNoticeRow.booking_id == booking_id, PolicyNoticeRow.noticed_at <= at)
            .order_by(PolicyNoticeRow.noticed_at.desc()).limit(1),
        )
    ).tuples().one_or_none()
    return None if row is None else (row[0], local(row[1]).date())


@router.post("/policy/extract")
async def extract_policy(body: PolicyText) -> PolicyDraft:
    """Read rule text into a table; nothing is saved."""
    policy, source = await read_policy(required_text(body.text))
    return PolicyDraft(
        rules=list(policy.rules), late=policy.late, unread=list(policy.unread), source=source,
    )


@router.post("/policy/versions", status_code=201)
async def save_policy(body: PolicySave, db: Session, now: Now) -> PolicyVersion:
    """Save a new version; two devices saving at once cannot share a number."""
    days = [rule.days_before for rule in body.rules]
    if len(set(days)) != len(days):
        raise HTTPException(422, "days_before must be unique")
    before = await latest_policy(db)
    rules = sorted(body.rules, key=lambda rule: rule.days_before, reverse=True)
    row = PolicyVersionRow(
        id=f"policy-{uuid4().hex}", workshop_id=WORKSHOP_ID, version=(before.version if before else 0) + 1,
        rules=[rule.model_dump(mode="json") for rule in rules],
        late=body.late.model_dump(mode="json") if body.late else None,
        unread=list(body.unread), source_text=required_text(body.source_text), approved_at=now,
    )
    db.add(row)
    await db.flush()
    return version_view(row, before)


@router.get("/policy/versions")
async def list_policies(db: Session) -> list[PolicyVersion]:
    """List versions, newest first."""
    rows = list(await db.scalars(
        select(PolicyVersionRow).where(PolicyVersionRow.workshop_id == WORKSHOP_ID)
        .order_by(PolicyVersionRow.version.desc()),
    ))
    return [version_view(row, before) for row, before in zip(rows, [*rows[1:], None], strict=True)]


@router.get("/policy/versions/{version}")
async def read_version(version: int, db: Session) -> PolicyVersion:
    """Read one version in full."""
    rows = {
        row.version: row for row in await db.scalars(
            select(PolicyVersionRow).where(
                PolicyVersionRow.workshop_id == WORKSHOP_ID,
                PolicyVersionRow.version.in_([version, version - 1]),
            ),
        )
    }
    if version not in rows:
        raise HTTPException(404, "resource not found")
    return version_view(rows[version], rows.get(version - 1))


@router.post("/policy/notices", status_code=201)
async def record_notice(body: NoticeRequest, db: Session, now: Now) -> Notice:
    """Record that the owner copied the current rules for one booking."""
    policy = await latest_policy(db)
    known = await db.scalar(select(func.count()).where(BookingRow.id == body.booking_id))
    if policy is None or not known:
        raise HTTPException(404, "resource not found")
    db.add(PolicyNoticeRow(
        id=f"notice-{uuid4().hex}", booking_id=body.booking_id, policy_version_id=policy.id, noticed_at=now,
    ))
    await db.flush()
    current = policy_of(policy)
    return Notice(
        version=policy.version, noticed_at=iso(now), summary=policy_summary(current.rules, current.late),
    )
