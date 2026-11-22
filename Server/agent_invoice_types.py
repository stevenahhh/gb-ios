"""What the invoice reader returns: rows that name a parcel by id and carry no personal data."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Final, Literal

from agent_types import CONFIDENCE_THRESHOLD, Check, Resolution, TargetRef
from carriers import FormatCheck

type ParcelStatus = Literal["packing", "invoice_pending", "in_transit", "delivered"]
type MatchKind = Literal["one", "none", "several"]
type CarrierStatus = Literal["known", "guessed", "unknown"]


class Problem(StrEnum):
    """Why a row must go to the owner instead of being registered."""

    DUPLICATE_IN_TEXT = "duplicate_in_text"
    ALREADY_USED = "already_used"
    ALREADY_SHIPPED = "already_shipped"
    NOT_PACKED = "not_packed"
    WRONG_FORMAT = "wrong_format"
    RECIPIENT_MISMATCH = "recipient_mismatch"
    SPOKEN_DIGITS = "spoken_digits"
    COLUMNS_SWAPPED = "columns_swapped"
    UNKNOWN_ORDER = "unknown_order"
    BANK_LINE = "bank_line"


PROBLEM_TEXT: Final[Mapping[Problem, str]] = {
    Problem.DUPLICATE_IN_TEXT: "같은 송장번호나 주문이 글에 두 번 나와요.",
    Problem.ALREADY_USED: "이미 다른 주문에 등록된 송장번호예요.",
    Problem.ALREADY_SHIPPED: "이미 발송한 주문이에요.",
    Problem.NOT_PACKED: "아직 포장 완료 전인 주문이에요.",
    Problem.WRONG_FORMAT: "알려진 송장번호 자릿수와 달라요. 맞는 번호인지 확인해 주세요.",
    Problem.RECIPIENT_MISMATCH: "받는 분이 주문과 달라요.",
    Problem.SPOKEN_DIGITS: "말로 불러 준 번호라 한 번 확인이 필요해요.",
    Problem.COLUMNS_SWAPPED: "주문번호와 송장번호 칸이 바뀐 것 같아요.",
    Problem.UNKNOWN_ORDER: "열린 주문에 없는 번호가 함께 적혀 있어요.",
    Problem.BANK_LINE: "계좌나 입금 이야기가 함께 있어요. 송장번호가 맞는지 확인해 주세요.",
}
CHECK_LABEL: Final[Mapping[Problem, str]] = {
    Problem.DUPLICATE_IN_TEXT: "두 번 나온 송장번호나 주문",
    Problem.ALREADY_USED: "이미 등록된 송장번호",
    Problem.ALREADY_SHIPPED: "이미 발송한 주문",
    Problem.NOT_PACKED: "포장이 끝나지 않은 주문",
    Problem.WRONG_FORMAT: "송장번호 자릿수",
    Problem.RECIPIENT_MISMATCH: "주문과 다른 받는 분",
    Problem.SPOKEN_DIGITS: "말로 불러 준 송장번호",
    Problem.COLUMNS_SWAPPED: "주문번호와 송장번호 칸",
    Problem.UNKNOWN_ORDER: "열린 주문에 없는 번호",
    Problem.BANK_LINE: "계좌나 입금 이야기",
}
CARRIER_LABEL: Final = "택배사"
BLOCKING: Final = frozenset({
    Problem.DUPLICATE_IN_TEXT, Problem.ALREADY_USED, Problem.ALREADY_SHIPPED, Problem.NOT_PACKED,
    Problem.RECIPIENT_MISMATCH,
})


@dataclass(frozen=True, slots=True)
class Parcel:
    """A shipment the owner may be naming; recipient and phone are used in memory only."""

    shipment_id: str
    order_id: str
    order_number: int
    status: ParcelStatus
    revision: int
    recipient: str
    phone: str | None
    tracking_number: str | None

    @property
    def target(self) -> TargetRef:
        """Name this parcel for the policy without personal data."""
        return TargetRef("shipment", self.shipment_id, f"#{self.order_number}", self.revision)


@dataclass(frozen=True, slots=True)
class InvoiceRow:
    """One tracking number read from the owner and what it matched."""

    line: int
    number: str
    excerpt: str
    match: MatchKind
    candidates: tuple[TargetRef, ...]
    carrier: str | None
    carrier_status: CarrierStatus
    check: FormatCheck
    problems: tuple[Problem, ...]
    confidence: float
    checked_at: datetime
    unknown_orders: tuple[int, ...] = ()

    @property
    def parcel(self) -> TargetRef | None:
        """Return the parcel only when exactly one matched."""
        return self.candidates[0] if self.match == "one" else None

    @property
    def resolution(self) -> Resolution:
        """Hand the match to the policy."""
        return Resolution(self.candidates, self.confidence)

    @property
    def checks(self) -> tuple[Check, ...]:
        """Hand every problem to the policy as a failed check, and whether the carrier is certain."""
        failed = tuple(Check(CHECK_LABEL[problem], passed=False) for problem in self.problems)
        return (*failed, Check(CARRIER_LABEL, passed=self.carrier_status == "known"))

    @property
    def blocks(self) -> tuple[Problem, ...]:
        """List the problems that even the owner's approval cannot override; the rest are warnings."""
        return tuple(problem for problem in self.problems if problem in BLOCKING)

    @property
    def needs_owner(self) -> bool:
        """Tell whether the caller must propose this row instead of registering it."""
        unsure = self.confidence < CONFIDENCE_THRESHOLD or self.match != "one"
        return unsure or not all(check.passed for check in self.checks)
