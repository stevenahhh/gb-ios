"""HyperCLOVA X endpoints: inquiry reply drafts, owner questions, and rewrites."""

import logging
from collections.abc import Callable, Sequence
from functools import partial
from typing import ClassVar, Final, assert_never

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from ai_output import empty_problems, normalize, reply_problems
from assistant import build_context, shop_facts
from common import Now
from prompts import (
    ASK_SAMPLING,
    DRAFT_SAMPLING,
    RETRY_EMPTY,
    REWRITE_SAMPLING,
    HistoryTurn,
    Inquiry,
    RewriteKind,
    ask_messages,
    draft_messages,
    retry_message,
    rewrite_messages,
)
from providers import UPSTREAM_FAILED, ChatMessage, Sampling, chat

LOGGER: Final = logging.getLogger("roundup.ai")
ATTEMPTS: Final = 2
MAX_HISTORY_ITEMS: Final = 40
router = APIRouter()
type Check = Callable[[str], list[str]]


class DraftRequest(BaseModel):
    """Inquiry fields used to write a reply draft."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)
    customer: str = Field(max_length=200)
    subject: str = Field(max_length=200)
    question: str = Field(max_length=4000)
    facts: list[str] = Field(max_length=30)


class DraftResponse(BaseModel):
    """Generated reply draft."""

    draft: str


class AskRequest(BaseModel):
    """Owner question; workshop facts are always loaded by the server, never accepted here."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)
    question: str = Field(min_length=1, max_length=1000)
    history: list[HistoryTurn] = Field(default=[], max_length=MAX_HISTORY_ITEMS)


class AskResponse(BaseModel):
    """Assistant answer."""

    answer: str


class RewriteRequest(BaseModel):
    """Text to polish for one purpose, with an optional owner instruction."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid")
    kind: RewriteKind
    title: str = Field(max_length=200)
    text: str = Field(min_length=1, max_length=4000)
    instruction: str = Field(default="", max_length=300)


class RewriteResponse(BaseModel):
    """Rewritten text."""

    draft: str


async def generate(messages: Sequence[ChatMessage], sampling: Sampling, check: Check) -> str:
    """Return cleaned output, retrying once with the reason when the check refuses it."""
    conversation = list(messages)
    for _ in range(ATTEMPTS):
        text = normalize(await chat(conversation, sampling))
        problems = check(text)
        if not problems:
            return text
        LOGGER.warning("ai_output_rejected")
        correction = retry_message(problems) if text else ChatMessage("user", RETRY_EMPTY)
        conversation += [ChatMessage("assistant", text), correction]
    raise HTTPException(502, UPSTREAM_FAILED)


@router.post("/draft")
async def draft(body: DraftRequest) -> DraftResponse:
    """Write a reply draft from the inquiry's facts, the workshop profile, and written rules."""
    shop = await shop_facts()
    inquiry = Inquiry(body.customer, body.subject, body.question, tuple(body.facts))
    basis = "\n".join([*inquiry.facts, shop.text])
    question = f"{body.subject}\n{body.question}"
    check = partial(reply_problems, basis=basis, question=question)
    return DraftResponse(draft=await generate(draft_messages(inquiry, shop), DRAFT_SAMPLING, check))


@router.post("/ask")
async def ask(body: AskRequest, now: Now) -> AskResponse:
    """Answer from facts read from PostgreSQL for this request."""
    context = await build_context(now)
    messages = ask_messages(context, body.history, body.question)
    return AskResponse(answer=await generate(messages, ASK_SAMPLING, empty_problems))


@router.post("/rewrite")
async def rewrite(body: RewriteRequest) -> RewriteResponse:
    """Polish a promotion, recommendation, or reply while keeping its facts."""
    messages = rewrite_messages(body.kind, (body.title, body.text), body.instruction)
    match body.kind:
        case "inquiry":
            check: Check = partial(reply_problems, basis=f"{body.title}\n{body.text}", question="")
        case "content" | "recommendation":
            check = empty_problems
        case _:
            assert_never(body.kind)
    return RewriteResponse(draft=await generate(messages, REWRITE_SAMPLING, check))
