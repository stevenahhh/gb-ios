"""Classify the owner's newest turn so a reaction never makes the model answer again.

The patterns only accept a whole message built from known reaction words; anything else
goes to the model, whose prompt carries the same rule as a backup.
"""

import re
from collections.abc import Sequence
from typing import Final, Literal

from prompts import HistoryTurn

type Reaction = Literal["praise", "thanks", "closing", "ack"]

MAX_REACTION_CHARS: Final = 30
MAX_REVISION_CHARS: Final = 60

PRAISE: Final = (
    r"좋(?:았어요|았어|습니다|은데요|네요|아요|은데|다|네|아|군)"
    r"|괜찮(?:은데요|네요|아요|은데|다|네|아|군)"
    r"|(?:마음|맘)에\s*(?:쏙\s*)?(?:들어요|들어|드네요|드네|든다|듭니다)"
    r"|완벽(?:하네요|해요|하네|하다|해)?|최고(?:예요|에요|야|다|네요|네)?"
    r"|훌륭(?:하네요|해요|하네|하다|해)|멋지(?:네요|다|네)|멋있(?:네요|다|네)"
    r"|예쁘(?:네요|다|네)|이쁘(?:네요|다|네)|딱\s*(?:좋|이)(?:네요|에요|아요|야|네|다|아)"
    r"|잘\s*(?:썼|쓰셨|했|하셨|만들었)(?:네요|어요|네|다|어)|끝내주(?:네요|는데|네|다)"
    r"|굿|good|nice|대박|짱"
)
THANKS: Final = (
    r"고마(?:웠어요|웠어|워요|워|웡)|고맙(?:습니다|네요|다|네)|감사(?:합니다|했어요|해요|하다|해|요)?"
    r"|땡큐|땡스|thank\s*you|thanks|thx"
)
CLOSING: Final = (
    r"수고(?:하셨어요|많았어요|많았어|했어요|했어|해요|해)?|끝(?:이에요|이야|났어|났다)?"
    r"|(?:이제\s*)?됐(?:어요|어|다)|그만(?:할게요|할게)?|바이|잘\s*자|다음에\s*봐|이만"
)
ACK: Final = (
    r"알겠(?:습니다|어요|어|다)|알았(?:어요|어|다)|오케이|오키|오케|okay|ok|ㅇㅋ|ㅇㅇ"
    r"|넵|넹|네|응|웅|예|그래요|그래|확인(?:했습니다|했어요|했어)?"
)
FILLER: Final = (
    r"우와|와우|오호|오오+|와+|오+|헐|음+|아주|아+|ㅋ+|ㅎ+|ㅠ+|ㅜ+|진짜|정말로|정말|너무|완전|엄청|되게"
    r"|굉장히|매우|많이|진심|넘|역시|이야|이번\s*(?:것|거)도?|이거|그거|이게|그게|이건|그건|이렇게"
    r"|그럼|글(?:이|도)?|문구(?:가|도)?|다"
)
SEPARATOR: Final = r"[\s.,!?~…^·]*"
# Earlier groups win when finditer scans, so 끝내주네 counts as praise before 끝 can count as closing.
UNIT: Final = rf"(?P<praise>{PRAISE})|(?P<thanks>{THANKS})|(?P<closing>{CLOSING})|(?P<ack>{ACK})|(?:{FILLER})"
UNITS: Final = re.compile(UNIT)
WHOLE: Final = re.compile(rf"{SEPARATOR}(?:(?:{UNIT}){SEPARATOR})+")
EMOJI: Final = re.compile("[\U0001f000-\U0001faff\u2600-\u27bf\ufe0f\u200d\u2661\u2665]")
PRIORITY: Final[tuple[Reaction, ...]] = ("closing", "thanks", "praise", "ack")

WRITING: Final = re.compile(r"써|작성|글|문구|문자|홍보|공지|안내문|게시")
OFFER: Final = re.compile(r"\?\s*$")
REVISION_WORDS: Final = (
    r"짧게|길게|간단(?:히|하게)|줄여|늘려|자세(?:히|하게)|부드럽게|친근하게|정중하게|딱딱|캐주얼|톤|말투"
    r"|해시태그|이모지|다시\s*(?:써|작성|만들|해)|고쳐|바꿔|수정해|다른\s*(?:버전|느낌|스타일)|하나\s*더"
    r"|빼\s*(?:줘|주세요)|넣어|추가해"
)
REVISION: Final = re.compile(REVISION_WORDS)
NEW_QUESTION: Final = re.compile(r"몇|언제|어디|누구|얼마|무슨|뭐|무엇|어떻게|왜|알려|일정|현황")

REPLIES: Final[dict[Reaction, tuple[str, str]]] = {
    "praise": (
        "마음에 드신다니 다행이에요! 더 궁금한 게 있으면 언제든 물어봐 주세요.",
        "마음에 드신다니 다행이에요! 바로 올릴 수 있게 복사해 두시고, 더 고칠 곳이 있으면 말씀해 주세요.",
    ),
    "thanks": (
        "천만에요! 또 필요한 게 있으면 언제든 불러 주세요.",
        "천만에요! 올리기 전에 더 다듬고 싶은 곳이 있으면 말씀해 주세요.",
    ),
    "closing": (
        "수고 많으셨어요! 필요할 때 언제든 다시 불러 주세요.",
        "수고 많으셨어요! 필요할 때 언제든 다시 불러 주세요.",
    ),
    "ack": (
        "네, 알겠어요. 필요한 게 생기면 말씀해 주세요.",
        "네! 고칠 곳이 생기면 언제든 말씀해 주세요.",
    ),
}


def last_text(history: Sequence[HistoryTurn], role: Literal["owner", "assistant"]) -> str | None:
    """Return the newest turn spoken by one side."""
    return next((turn.text for turn in reversed(history) if turn.role == role), None)


def reaction(question: str, history: Sequence[HistoryTurn]) -> Reaction | None:
    """Name the reaction when the whole message only praises, thanks, acknowledges, or closes.

    A yes-like reply to an assistant question ("더 짧게 해 드릴까요?" -> "좋아") is consent to act,
    and a trailing question mark turns "됐어?" or "그래?" into a question, so both go to the model.
    """
    text = EMOJI.sub("", question).strip().lower()
    if not text or len(text) > MAX_REACTION_CHARS or WHOLE.fullmatch(text) is None:
        return None
    matches = list(UNITS.finditer(text))
    ranked: list[Reaction] = [
        name for name in PRIORITY if any(match.group(name) is not None for match in matches)
    ]
    kind: Reaction = ranked[0] if ranked else "ack"
    if kind in {"praise", "ack"} and OFFER.search(last_text(history, "assistant") or ""):
        return None
    if kind in {"closing", "ack"} and OFFER.search(text):
        return None
    return kind


def reaction_reply(kind: Reaction, history: Sequence[HistoryTurn]) -> str:
    """Answer a reaction in a short sentence, pointing at the next step after a written piece."""
    plain, after_writing = REPLIES[kind]
    request = last_text(history, "owner")
    return after_writing if request is not None and WRITING.search(request) else plain


def revision_target(question: str, history: Sequence[HistoryTurn]) -> str | None:
    """Return the previous answer when the owner asks to change it rather than ask something new."""
    previous = last_text(history, "assistant")
    if previous is None or len(question) > MAX_REVISION_CHARS:
        return None
    if REVISION.search(question) is None or NEW_QUESTION.search(question) is not None:
        return None
    return previous
