"""Every known source; the status endpoint covers the ones the app shows."""

from typing import Final

from collectors.base import JsonObject, SourceId
from collectors.http import Gateway
from collectors.instagram import InstagramCollector
from collectors.manual import KakaoChannelCollector, NaverBookingCollector, NaverTalkTalkCollector
from collectors.naver_blog import NaverBlogCollector
from collectors.naver_smartstore import SmartStoreCollector

STATUS_SOURCES: Final[tuple[SourceId, ...]] = (
    "instagram", "naver_smartstore", "naver_blog", "naver_booking", "naver_talktalk",
)
ALL_SOURCES: Final[tuple[SourceId, ...]] = (*STATUS_SOURCES, "kakao_channel")
type AnyCollector = (
    InstagramCollector | SmartStoreCollector | NaverBlogCollector
    | NaverBookingCollector | NaverTalkTalkCollector | KakaoChannelCollector
)
COLLECTORS: Final[dict[SourceId, type[AnyCollector]]] = {
    "instagram": InstagramCollector,
    "naver_smartstore": SmartStoreCollector,
    "naver_blog": NaverBlogCollector,
    "naver_booking": NaverBookingCollector,
    "naver_talktalk": NaverTalkTalkCollector,
    "kakao_channel": KakaoChannelCollector,
}


def build(source: SourceId, gateway: Gateway, stored: JsonObject) -> AnyCollector:
    """Create one collector from its stored setup values."""
    return COLLECTORS[source](gateway, stored)
