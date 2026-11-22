"""The interface every collector implements and the values it returns."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import ClassVar, Literal, override

from pydantic import BaseModel, ConfigDict, JsonValue, ValidationError

from collectors.http import Gateway

type JsonObject = dict[str, JsonValue]
type SourceId = Literal[
    "instagram", "naver_smartstore", "naver_blog", "naver_booking", "naver_talktalk", "kakao_channel",
]
type ItemKind = Literal["post", "comment", "insight", "order", "inquiry"]


class NeedsConnectionError(Exception):
    """The owner or operator must connect or allow the source first; the message is shown to the owner."""

    def __init__(self, message: str) -> None:
        """Keep the Korean message for the status endpoint."""
        super().__init__(message)
        self.message: str = message

    @override
    def __str__(self) -> str:
        return self.message


@dataclass(frozen=True, slots=True)
class CollectedItem:
    """One external item in the shape every source shares."""

    external_id: str
    kind: ItemKind
    title: str
    body: str
    author: str | None
    url: str | None
    published_at: datetime | None
    raw: JsonObject


@dataclass(frozen=True, slots=True)
class Window:
    """The period one run covers."""

    since: datetime
    now: datetime


class SourceConfig(BaseModel):
    """Owner-visible setup values; unknown fields, including anything secret, are rejected."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid", strict=True)


class Collector[C: SourceConfig](ABC):
    """One source: what it needs, how fast it may call, and what it collects."""

    source_id: ClassVar[SourceId]
    display_name: ClassVar[str]
    min_interval: ClassVar[float] = 1.0

    def __init__(self, gateway: Gateway, stored: JsonObject) -> None:
        """Read stored setup values; values an older release accepted fall back to none."""
        self.gateway: Gateway = gateway
        try:
            self.config: C = self.config_model().model_validate(stored)
        except ValidationError:
            self.config = self.config_model()()

    @classmethod
    @abstractmethod
    def config_model(cls) -> type[C]:
        """Return the setup values this source accepts."""

    @abstractmethod
    def connection_problem(self) -> str | None:
        """Say in Korean what is missing, or return nothing when the source can run."""

    @abstractmethod
    async def collect(self, window: Window) -> list[CollectedItem]:
        """Read new items; raise NeedsConnectionError or SourceError instead of returning partial data."""
