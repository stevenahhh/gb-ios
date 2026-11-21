"""Intent gate: name what the owner's newest turn wants before /ask writes an answer.

turns.py rules decide first at no cost (reactions, change requests, and a "그거 다시" with
nothing to redo). Otherwise one short model call classifies the turn. When that call fails,
times out, or returns something unreadable, keyword heuristics pick act, write, or lookup,
so /ask always answers.
"""

import asyncio
import logging
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import ClassVar, Final, Literal

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field

from prompts import CLASSIFY_SAMPLING, HistoryTurn, Intent, classify_messages
from providers import chat
from turns import WRITING, previous_answer, without_drafts

type Source = Literal["rules", "model", "fallback"]

LOGGER: Final = logging.getLogger("roundup.intents")
CLASSIFY_SECONDS: Final = 3.0
MAX_READING_CHARS: Final = 200
JSON_OBJECT: Final = re.compile(r"\{.*\}", re.DOTALL)
ACTION: Final = re.compile(
    r"처리해|완료\s*(?:처리|해|로)|확정해|취소해|환불해|등록해|변경해|입금\s*확인해|(?:답장|문자)\s*보내",
)
# A judgment about the draft or a change to it still needs the draft; every other intent starts fresh.
KEEPS_DRAFTS: Final[frozenset[Intent]] = frozenset({"edit", "advise", "react"})


class Classification(BaseModel):
    """The classifier's JSON, validated at the trust boundary."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)
    intent: Intent
    confidence: float = Field(ge=0, le=1)
    reading: str = ""


@dataclass(frozen=True, slots=True)
class Reading:
    """The intent chosen for one turn, where it came from, and the classifier's paraphrase."""

    intent: Intent
    source: Source
    confidence: float = 1.0
    reading: str = ""


def fallback(question: str) -> Intent:
    """Guess from keywords when the classifier is unavailable."""
    if ACTION.search(question):
        return "act"
    return "write" if WRITING.search(question) else "lookup"


def parse(raw: str) -> Classification | None:
    """Read the first JSON object in the classifier output, or nothing when it is malformed."""
    found = JSON_OBJECT.search(raw)
    if found is None:
        return None
    try:
        return Classification.model_validate_json(found.group())
    except ValueError:
        return None


async def classify(question: str, history: Sequence[HistoryTurn]) -> Reading:
    """Ask the model for the turn's intent within a short deadline, falling back to keywords."""
    try:
        async with asyncio.timeout(CLASSIFY_SECONDS):
            raw = await chat(classify_messages(history, question), CLASSIFY_SAMPLING)
    except (TimeoutError, HTTPException) as error:
        LOGGER.warning("intent_fallback", extra={"error_type": type(error).__name__})
        return Reading(fallback(question), "fallback")
    parsed = parse(raw)
    if parsed is None:
        LOGGER.warning("intent_fallback", extra={"error_type": "malformed"})
        return Reading(fallback(question), "fallback")
    # Editing needs something to edit; without an earlier answer the owner must say what they mean.
    intent: Intent = parsed.intent
    if intent == "edit" and previous_answer(history) is None:
        intent = "clarify"
    return Reading(intent, "model", parsed.confidence, parsed.reading.strip()[:MAX_READING_CHARS])


def context_turns(intent: Intent, history: Sequence[HistoryTurn]) -> list[HistoryTurn]:
    """Keep earlier drafts only when this turn is about them; a new direction drops them."""
    return list(history) if intent in KEEPS_DRAFTS else without_drafts(history)


def log_intent(reading: Reading) -> None:
    """Record the routing decision for later tuning; the owner's words stay out of the log."""
    LOGGER.info("ask_intent", extra={
        "intent": reading.intent, "intent_source": reading.source, "confidence": reading.confidence,
    })
