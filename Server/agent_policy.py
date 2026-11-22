"""Decide whether one tool call runs, waits for the owner, or is refused.

Pure on purpose: the model proposes, the rules below decide, and every rule is testable on its own.
Evidence is only the owner's current turn or a trusted adapter result. Customer text, history,
memos, and tool results never count, whatever they say.
"""

import re
import unicodedata
from collections.abc import Sequence
from datetime import date, time
from typing import Final

from agent_invoice import is_verbatim
from agent_text import (
    Mention,
    clock_times,
    contact_spans,
    dates_named,
    excerpt,
    is_negated,
    is_question,
    is_quoted,
    is_relayed,
    is_retold,
    is_unfinished,
    mentions,
    same_clock,
    sentence_around,
    sentences,
)
from agent_types import (
    CONFIDENCE_THRESHOLD,
    AdapterFact,
    Claim,
    Decision,
    EvidenceItem,
    EvidenceRule,
    Mode,
    PolicyContext,
    PolicySettings,
    ToolRule,
    Verdict,
)

OFF: Final = "꺼진 상태라 비서는 쉬었어요. 바뀐 건 없어요."
TOOL_OFF: Final = "이 기능은 꺼 두셔서 그냥 뒀어요."
ASKED: Final = "질문이 섞여 있어서 먼저 여쭤보고 할게요."
READ_ONLY: Final = "보기만 하고 바꾼 건 없어요."
NOT_FOUND: Final = "어떤 건지 모르겠어요. 하나만 콕 집어 주세요."
SEVERAL: Final = "{count}건이 비슷해요. 그중 하나를 골라 주세요."
ALWAYS_ASK: Final = "'물어보고 하기'로 정해 두셔서 확인 요청을 보냈어요."
NOT_SAID: Final = "부탁하신 일이 아니라서 그냥 뒀어요."
NO_EVIDENCE: Final = "방금 말씀에 없던 내용이 있어서 확인 요청을 보냈어요: {labels}"
CHECK_NEEDED: Final = "{labels}: 이건 사장님 눈으로 보셔야 해서 확인 요청으로 넘겼어요."
UNSURE_TARGET: Final = "무엇을 말씀하신 건지 헷갈려서 확인 요청을 보냈어요."
SPOKEN: Final = "음성으로 하신 부탁은 먼저 여쭤보고 해요."
CAP_REACHED: Final = "오늘 몫 {cap}건을 이미 알아서 했어요. 나머지는 확인 요청으로 넘겼어요."
SAID: Final = "부탁하신 일, 끝냈어요."
DONE: Final = "바로 해 뒀어요."
SEPARATOR: Final = re.compile(r"[\s.,·!?~…\-]")
MIN_TEXT_CLAIM: Final = 2
SHARED_DIGITS: Final = 3
DIGIT_RUN: Final = re.compile(r"\d[\d\s.\-]*\d|\d")


def tool_mode(tool: ToolRule, settings: PolicySettings) -> Mode:
    """Return the owner's switch for a tool; the general off always wins."""
    if settings.mode == "off":
        return "off"
    return settings.per_tool.get(tool.name, settings.mode)


def folded(text: str) -> tuple[str, list[int]]:
    """Fold case and width and drop separators, keeping where each letter came from."""
    letters: list[str] = []
    positions: list[int] = []
    for index, char in enumerate(text):
        if SEPARATOR.match(char):
            continue
        for letter in unicodedata.normalize("NFKC", char).casefold():
            letters.append(letter)
            positions.append(index)
    return "".join(letters), positions


def spans_of_text(value: str, turn: str, shortest: int = MIN_TEXT_CLAIM) -> list[tuple[int, int]]:
    """Find a name or quote in the turn, ignoring case, spaces, and separators."""
    wanted, _ = folded(value)
    haystack, positions = folded(turn)
    if len(wanted) < shortest:
        return []
    found: list[tuple[int, int]] = []
    start = haystack.find(wanted)
    while start >= 0:
        found.append((positions[start], positions[start + len(wanted) - 1] + 1))
        start = haystack.find(wanted, start + 1)
    return found


def numbers_in(turn: str, today: date) -> list[Mention]:
    """List numbers the owner stated, leaving out the digits of times and dates."""
    taken = [(start, end) for *_, start, end in clock_times(turn)]
    taken += [(start, end) for _, start, end in dates_named(turn, today)]
    taken += contact_spans(turn)
    return [
        found
        for found in mentions(turn)
        if not any(found.start < end and start < found.end for start, end in taken)
    ]


def spans_of_number(claim: Claim, turn: str, today: date) -> list[tuple[int, int]]:
    """Find a count, an amount, or a tracking number the turn states."""
    if claim.kind == "tracking":
        if not is_verbatim(claim.value, turn):
            return []
        spans = [match.span() for match in DIGIT_RUN.finditer(turn)]
        wanted = re.sub(r"\D", "", claim.value)
        exact = [(start, end) for start, end in spans if wanted in re.sub(r"\D", "", turn[start:end])]
        return exact or [(0, len(turn))]
    wanted = int(claim.value)
    excluded = {"clock", "date"} | ({"people"} if claim.kind == "money" else {"money"})
    stated = [found for found in numbers_in(turn, today) if found.unit not in excluded]
    if claim.kind == "number" and any(
        found.value != wanted
        and len(str(found.value)) == len(str(wanted))
        and len(str(wanted)) >= SHARED_DIGITS
        for found in stated
    ):
        return []
    return [(found.start, found.end) for found in stated if found.value == wanted]


def spans_of_moment(claim: Claim, turn: str, today: date) -> list[tuple[int, int]]:
    """Find a stated time or date."""
    if claim.kind == "time":
        wanted = time.fromisoformat(claim.value)
        return [
            (start, end) for hour, minute, start, end in clock_times(turn) if same_clock(hour, minute, wanted)
        ]
    day = date.fromisoformat(claim.value)
    return [(start, end) for named, start, end in dates_named(turn, today) if named == day]


def spans_of(claim: Claim, turn: str, today: date) -> list[tuple[int, int]]:
    """Find every place in the turn that states a claim, whatever the sentence around it says."""
    match claim.kind:
        case "text" | "quote":
            return spans_of_text(claim.value, turn)
        case "words":
            return [span for word in claim.value.split("|") for span in spans_of_text(word, turn, 1)]
        case "number" | "money" | "tracking":
            return spans_of_number(claim, turn, today)
        case "time" | "date":
            return spans_of_moment(claim, turn, today)


def find_evidence(claim: Claim, turn: str, today: date) -> str | None:
    """Return the owner's words that state a claim, or nothing when the turn asks or denies it."""
    for start, end in spans_of(claim, turn, today):
        own_words = claim.kind != "quote"
        sentence = sentence_around(turn, start, following=1 if own_words else 0)
        denied = is_negated(sentence) or is_unfinished(sentence) if own_words else is_retold(sentence)
        pasted = claim.kind != "tracking" and is_relayed(turn, start)
        said_by_another = is_quoted(turn, start, end) or pasted
        if not is_question(sentence) and not denied and not said_by_another:
            return excerpt(turn, start, end)
    return None


def confirmed_by_adapter(claim: Claim, facts: Sequence[AdapterFact]) -> AdapterFact | None:
    """Return a trusted adapter's record of the same value."""
    return next(
        (
            fact
            for fact in facts
            if fact.claim.kind == claim.kind and folded(fact.claim.value)[0] == folded(claim.value)[0]
        ),
        None,
    )


def evidence_for(
    claims: Sequence[Claim],
    context: PolicyContext,
) -> tuple[list[EvidenceItem], list[str]]:
    """Split the claims into the evidence found, each excerpt once, and the labels still missing."""
    found: list[EvidenceItem] = []
    missing: list[str] = []
    for claim in claims:
        fact = confirmed_by_adapter(claim, context.adapter)
        said = None if context.turn is None else find_evidence(claim, context.turn, context.today)
        if fact is not None:
            found.append(EvidenceItem("adapter", fact.source))
        elif said is not None:
            found.append(EvidenceItem("owner_turn", said))
        else:
            missing.append(claim.label)
    return list(dict.fromkeys(found)), missing


def undecided(context: PolicyContext) -> Verdict | None:
    """Ask the owner when the call does not point at exactly one row."""
    candidates = context.resolution.candidates
    if len(candidates) == 1:
        return None
    if not candidates:
        return Verdict("clarify", context.resolution.note or NOT_FOUND)
    return Verdict("clarify", SEVERAL.format(count=len(candidates)))


def switched(tool: ToolRule, context: PolicyContext) -> Verdict | None:
    """Settle what the owner's switches and the target alone decide."""
    mode = tool_mode(tool, context.settings)
    if mode == "off":
        return Verdict("refused", OFF if context.settings.mode == "off" else TOOL_OFF)
    if tool.tier == "T0":
        return Verdict("auto", READ_ONLY)
    unclear = undecided(context)
    if unclear is not None:
        return unclear
    return Verdict("proposed", ALWAYS_ASK) if mode == "ask" else None


def evidence_rule(tool: ToolRule, context: PolicyContext) -> EvidenceRule:
    """Hold an internal tool to the owner's turn; a run without one keeps its own rule."""
    if tool.tier == "T1" and tool.evidence == "none" and context.turn is not None:
        return "propose"
    return tool.evidence


def asks_anything(turn: str) -> bool:
    """Tell when any sentence of a turn asks something; the owner's question comes before any action."""
    return any(is_question(sentence) for sentence in sentences(turn))


def unstated(
    tool: ToolRule,
    rule: EvidenceRule,
    claims: Sequence[Claim],
    missing: Sequence[str],
    context: PolicyContext,
) -> tuple[Decision, str] | None:
    """Name what still needs the owner: spoken money, a question in the turn, or a missing fact."""
    if tool.tier == "T2" and context.source == "voice":
        return "proposed", SPOKEN
    if rule == "propose" and context.turn is not None and asks_anything(context.turn):
        return "proposed", ASKED
    if rule == "none" or (claims and not missing):
        return None
    if rule == "refuse":
        return "refused", NOT_SAID
    return "proposed", NO_EVIDENCE.format(labels=", ".join(missing) or "내용")


def decide(tool: ToolRule, claims: Sequence[Claim], context: PolicyContext) -> Verdict:
    """Apply the contract: switches, one target, evidence, checks, confidence, and the daily cap."""
    settled = switched(tool, context)
    if settled is not None:
        return settled
    rule = evidence_rule(tool, context)
    evidence, missing = evidence_for(claims, context)
    waiting = unstated(tool, rule, claims, missing, context)
    if waiting is not None:
        return Verdict(waiting[0], waiting[1], tuple(evidence), tuple(missing))
    decision, reason = weighed(rule, context)
    return Verdict(decision, reason, tuple(evidence))


def weighed(rule: EvidenceRule, context: PolicyContext) -> tuple[Decision, str]:
    """Apply the checks, the confidence threshold, and the daily cap to a supported call."""
    failed = [check.label for check in context.checks if not check.passed]
    if failed:
        return "proposed", CHECK_NEEDED.format(labels=", ".join(failed))
    if context.resolution.confidence < CONFIDENCE_THRESHOLD:
        return "proposed", UNSURE_TARGET
    cap = context.settings.daily_cap
    if context.auto_today >= cap:
        return "proposed", CAP_REACHED.format(cap=cap)
    return "auto", SAID if rule != "none" else DONE
