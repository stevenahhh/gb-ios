"""Spoken answers for the app's live voice mode."""

import re
from typing import Annotated, Final

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field

from providers import synthesize

router = APIRouter()

LINK: Final = re.compile(r"\[([^\]]*)\]\([^)]*\)")
LINE_MARK: Final = re.compile(r"^\s*(?:#{1,6}|[-*+•>]|\d+[.)])\s+", re.MULTILINE)
SYMBOLS: Final = re.compile(r"[*_`#~|<>\[\]{}\\^=]+")
SPACES: Final = re.compile(r"[ \t]+")


class SpeechRequest(BaseModel):
    """Answer text to read aloud."""

    text: Annotated[str, Field(min_length=1, max_length=2000)]


def speakable(text: str) -> str:
    """Drop markdown and symbols the voice would otherwise read out literally."""
    plain = SYMBOLS.sub(" ", LINE_MARK.sub("", LINK.sub(r"\1", text)))
    lines = (SPACES.sub(" ", line).strip() for line in plain.splitlines())
    return "\n".join(line for line in lines if line)


@router.post("/tts")
async def tts(body: SpeechRequest) -> Response:
    """Synthesize Korean speech as MP3."""
    text = speakable(body.text)
    if not text:
        raise HTTPException(422, "nothing to speak")
    return Response(await synthesize(text), media_type="audio/mpeg")
