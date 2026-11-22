"""One adapter for CLOVA Studio v3 chat completions with tools.

ASSUMPTION, not readable from this repository: the request carries
`tools: [{type: "function", function: {name, description, parameters}}]` and `toolChoice: "auto"`,
an assistant turn that called tools carries `toolCalls: [{id, type: "function", function: {name,
arguments}}]`, a result is `{role: "tool", toolCallId, content}`, the answer's calls are at
`result.message.toolCalls[].function.arguments` as an object or as a JSON string, and
`result.usage.totalTokens` counts the call. `scripts/agent_eval.py` can call `hcx_tool_chat` to
prove it on the real model; only this module would change if it is wrong.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from math import isfinite
from typing import ClassVar, Final, Literal, Protocol
from uuid import uuid4

import anyio
import httpx
from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, JsonValue, TypeAdapter, ValidationError

from agent_types import ToolCall
from providers import CLOVA_URL, parsed, require_env, send

TEMPERATURE: Final = 0.1
OBJECT: Final = TypeAdapter(dict[str, JsonValue])
type TurnRole = Literal["system", "user", "assistant", "tool"]
type ToolDefinition = dict[str, JsonValue]


class ModelUnavailableError(Exception):
    """The chat model could not answer; the caller decides whether that is a failure or a fallback."""


@dataclass(frozen=True, slots=True)
class Turn:
    """One conversation message in the model's wire format."""

    role: TurnRole
    content: str
    calls: tuple[ToolCall, ...] = ()
    call_id: str | None = None

    def wire(self) -> dict[str, JsonValue]:
        """Write the message the way CLOVA Studio reads it."""
        message: dict[str, JsonValue] = {"role": self.role, "content": self.content}
        if self.calls:
            message["toolCalls"] = [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {"name": call.name, "arguments": call.arguments},
                }
                for call in self.calls
            ]
        if self.call_id is not None:
            message["toolCallId"] = self.call_id
        return message


@dataclass(frozen=True, slots=True)
class ChatTurn:
    """The model's answer: text, the tool calls it asked for, and the tokens it used."""

    content: str
    calls: tuple[ToolCall, ...]
    tokens: int


class ToolChat(Protocol):
    """A chat model that may ask for tools; tests pass a fake."""

    async def __call__(
        self,
        messages: Sequence[Turn],
        tools: Sequence[ToolDefinition],
        *,
        max_tokens: int,
        seconds: float,
    ) -> ChatTurn:
        """Return the model's next turn within the time limit, or raise ModelUnavailableError."""
        ...


class WireFunction(BaseModel):
    """The name and arguments of one requested call."""

    name: str
    arguments: dict[str, JsonValue] | str = Field(default_factory=dict[str, JsonValue])


class WireCall(BaseModel):
    """One requested call."""

    id: str = ""
    function: WireFunction


class WireMessage(BaseModel):
    """The assistant message of an answer."""

    model_config: ClassVar[ConfigDict] = ConfigDict(populate_by_name=True)
    content: str | None = None
    tool_calls: list[WireCall] = Field(default_factory=list[WireCall], alias="toolCalls")


class WireUsage(BaseModel):
    """The token counts of an answer."""

    model_config: ClassVar[ConfigDict] = ConfigDict(populate_by_name=True)
    total_tokens: int = Field(default=0, alias="totalTokens")


class WireResult(BaseModel):
    """The result envelope of an answer."""

    message: WireMessage
    usage: WireUsage = Field(default_factory=WireUsage)


class WireAnswer(BaseModel):
    """Only the fields this server uses."""

    result: WireResult


def storable(value: JsonValue) -> JsonValue:
    """Drop what PostgreSQL cannot store, so a call is refused or run and never breaks the run."""
    if isinstance(value, str):
        return value.replace("\x00", "")
    if isinstance(value, float) and not isfinite(value):
        return None
    if isinstance(value, list):
        return [storable(item) for item in value]
    if isinstance(value, dict):
        return {key.replace("\x00", ""): storable(item) for key, item in value.items()}
    return value


def arguments_of(raw: dict[str, JsonValue] | str) -> dict[str, JsonValue]:
    """Read arguments that arrive as an object or as JSON text; unreadable text becomes no arguments."""
    try:
        values = raw if isinstance(raw, dict) else OBJECT.validate_json(raw)
    except ValidationError:
        return {}
    return OBJECT.validate_python(storable(values))


def chat_turn(answer: WireAnswer) -> ChatTurn:
    """Turn an answer into text and calls; a missing id gets one so results can refer to it."""
    message = answer.result.message
    calls = tuple(
        ToolCall(
            call.id or f"call-{uuid4().hex}",
            call.function.name.replace("\x00", ""),
            arguments_of(call.function.arguments),
        )
        for call in message.tool_calls
    )
    return ChatTurn((message.content or "").strip(), calls, answer.result.usage.total_tokens)


async def hcx_tool_chat(
    messages: Sequence[Turn],
    tools: Sequence[ToolDefinition],
    *,
    max_tokens: int,
    seconds: float,
) -> ChatTurn:
    """Ask HyperCLOVA X for the next turn, with tools; any failure becomes ModelUnavailableError."""
    body: dict[str, JsonValue] = {
        "messages": [message.wire() for message in messages],
        "maxTokens": max_tokens,
        "temperature": TEMPERATURE,
    }
    if tools:
        body["tools"] = list(tools)
        body["toolChoice"] = "auto"
    try:
        request = httpx.Request(
            "POST",
            CLOVA_URL,
            headers={"Authorization": f"Bearer {require_env('CLOVA_STUDIO_API_KEY')}"},
            json=body,
        )
        with anyio.fail_after(seconds):
            response = await send(request)
        return chat_turn(parsed(WireAnswer, response))
    except (HTTPException, TimeoutError) as error:
        raise ModelUnavailableError from error
