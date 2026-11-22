"""Sources without a pull API this server may use; they always report needs_connection.

naver_booking: https://help.naver.com/service/11712/contents/18310 describes a link with one partner program
that the owner sets up in Smart Place with that company. It documents no API for reading reservations.
Path: ask Naver for a partner integration, or keep entering bookings by hand.

naver_talktalk: the Chat Bot API (https://github.com/navertalk/chatbot-api) pushes events to a registered TLS
webhook and has no history endpoint. Path: create an account in https://partner.talk.naver.com, apply under
개발자도구 > 챗봇API 설정, and register a webhook. This deployment adds no inbound route, so it is not built.

kakao_channel: the Kakao Talk Channel API (https://developers.kakao.com/docs/latest/ko/kakaotalk-channel/common)
offers channel add, chat links, customer files, and relationship lookups, and no chat reading. Path: connect a
business channel to a biz app, then use a Kakao-approved consultation partner.
"""

from typing import Annotated, ClassVar, override

from pydantic import Field

from collectors.base import CollectedItem, Collector, NeedsConnectionError, SourceConfig, SourceId, Window

BOOKING_PATH = "네이버 예약은 아직 자동으로 가져올 수 없어요. 예약은 직접 입력해 주세요."
TALKTALK_PATH = "네이버 톡톡은 아직 자동으로 가져올 수 없어요. 톡톡 파트너센터에서 확인해 주세요."
KAKAO_PATH = "카카오톡 채널은 아직 자동으로 가져올 수 없어요. 채널 관리자센터에서 확인해 주세요."


class BookingConfig(SourceConfig):
    """The booking business number shown to the owner."""

    business_id: Annotated[str, Field(pattern=r"^[0-9]{1,20}$")] | None = None


class TalkTalkConfig(SourceConfig):
    """The talk-talk account shown to the owner."""

    partner_id: Annotated[str, Field(pattern=r"^[A-Za-z0-9]{2,20}$")] | None = None


class KakaoConfig(SourceConfig):
    """The channel profile shown to the owner."""

    profile_id: Annotated[str, Field(pattern=r"^_[A-Za-z0-9]{2,20}$")] | None = None


class NaverBookingCollector(Collector[BookingConfig]):
    """Naver booking stub."""

    source_id: ClassVar[SourceId] = "naver_booking"
    display_name: ClassVar[str] = "네이버 예약"

    @classmethod
    @override
    def config_model(cls) -> type[BookingConfig]:
        return BookingConfig

    @override
    def connection_problem(self) -> str | None:
        return BOOKING_PATH

    @override
    async def collect(self, window: Window) -> list[CollectedItem]:
        raise NeedsConnectionError(BOOKING_PATH)


class NaverTalkTalkCollector(Collector[TalkTalkConfig]):
    """Naver talk-talk stub."""

    source_id: ClassVar[SourceId] = "naver_talktalk"
    display_name: ClassVar[str] = "네이버 톡톡"

    @classmethod
    @override
    def config_model(cls) -> type[TalkTalkConfig]:
        return TalkTalkConfig

    @override
    def connection_problem(self) -> str | None:
        return TALKTALK_PATH

    @override
    async def collect(self, window: Window) -> list[CollectedItem]:
        raise NeedsConnectionError(TALKTALK_PATH)


class KakaoChannelCollector(Collector[KakaoConfig]):
    """Kakao Talk Channel stub."""

    source_id: ClassVar[SourceId] = "kakao_channel"
    display_name: ClassVar[str] = "카카오톡 채널"

    @classmethod
    @override
    def config_model(cls) -> type[KakaoConfig]:
        return KakaoConfig

    @override
    def connection_problem(self) -> str | None:
        return KAKAO_PATH

    @override
    async def collect(self, window: Window) -> list[CollectedItem]:
        raise NeedsConnectionError(KAKAO_PATH)
