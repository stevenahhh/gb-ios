"""A scripted chat model and small helpers for the agent core tests."""

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Final

from httpx2 import AsyncClient
from pydantic import JsonValue
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from agent_api import tool_chat
from agent_hcx import ChatTurn, ModelUnavailableError, ToolDefinition, Turn
from agent_types import ToolCall
from main import app

ORDER: Final = "shipment-order-1040"
type Body = dict[str, JsonValue]


def wants(name: str, /, **arguments: JsonValue) -> ChatTurn:
    """The model asks for one tool."""
    return ChatTurn("", (ToolCall(f"call-{name}", name, arguments),), 5)


def wants_many(*calls: tuple[str, dict[str, JsonValue]]) -> ChatTurn:
    """The model asks for several tools in one turn."""
    return ChatTurn(
        "", tuple(ToolCall(f"call-{index}", name, args) for index, (name, args) in enumerate(calls)), 5,
    )


def says(words: str) -> ChatTurn:
    """The model answers the owner."""
    return ChatTurn(words, (), 7)


@dataclass(slots=True)
class ScriptedChat:
    """Plays turns in order and remembers everything the model was shown."""

    turns: list[ChatTurn | Exception | Callable[[], Awaitable[ChatTurn]]]
    seen: list[list[Turn]] = field(default_factory=list[list[Turn]])
    offered: list[list[ToolDefinition]] = field(default_factory=list[list[ToolDefinition]])
    on_call: Callable[[int], Awaitable[None]] | None = None

    async def __call__(
        self,
        messages: Sequence[Turn],
        tools: Sequence[ToolDefinition],
        *,
        max_tokens: int,
        seconds: float,
    ) -> ChatTurn:
        assert max_tokens == 1024
        assert seconds > 0
        self.seen.append(list(messages))
        self.offered.append(list(tools))
        if self.on_call is not None:
            await self.on_call(len(self.seen))
        turn = self.turns[len(self.seen) - 1]
        if isinstance(turn, ModelUnavailableError):
            raise turn
        if callable(turn):
            return await turn()
        assert isinstance(turn, ChatTurn)
        return turn

    def shown(self) -> str:
        """Everything the model has been shown, as one text."""
        return "\n".join(turn.content for call in self.seen for turn in call)


def chat_of(*turns: ChatTurn | Exception | Callable[[], Awaitable[ChatTurn]]) -> ScriptedChat:
    """Build a scripted chat."""
    return ScriptedChat(list(turns))


def use(chat: ScriptedChat) -> None:
    """Let the app talk to a scripted chat instead of the real model."""
    app.dependency_overrides[tool_chat] = lambda: chat


async def ask(client: AsyncClient, chat: ScriptedChat, question: str, **more: JsonValue) -> Body:
    """Send one owner turn and return the response body."""
    use(chat)
    response = await client.post("/agent/run", json={"question": question, **more})
    assert response.status_code == 200, response.text
    return response.json()


async def scalar(engine: AsyncEngine, query: str, **params: JsonValue) -> object:
    """Read one value."""
    async with engine.connect() as connection:
        return await connection.scalar(text(query), params)


async def rows(engine: AsyncEngine, query: str, **params: JsonValue) -> list[tuple[object, ...]]:
    """Read rows."""
    async with engine.connect() as connection:
        return [tuple(row) for row in (await connection.execute(text(query), params)).all()]


async def execute(engine: AsyncEngine, query: str, **params: JsonValue) -> None:
    """Change rows directly, as another session would."""
    async with engine.begin() as connection:
        _ = await connection.execute(text(query), params)


async def set_mode(engine: AsyncEngine, mode: str, **per_tool: str) -> None:
    """Change the owner's switches."""
    if per_tool:
        values = ", ".join(f'"{name}": "{value}"' for name, value in per_tool.items())
        await execute(
            engine,
            "UPDATE agent_settings SET per_tool = cast(:switches AS jsonb)",
            switches="{" + values + "}",
        )
    await execute(engine, "UPDATE agent_settings SET mode = :mode", mode=mode)


@asynccontextmanager
async def bounded(seconds: float = 20) -> AsyncIterator[None]:
    """Fail a test that waits forever instead of hanging the suite."""
    async with asyncio.timeout(seconds):
        yield
