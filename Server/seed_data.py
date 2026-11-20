"""Initial workshop data, anchored to the first seeding day in Asia/Seoul."""

from collections.abc import Mapping, Sequence
from datetime import date, datetime, time, timedelta

from database import Base
from display import SEOUL, month_start, previous_month
from models import (
    BookingRow,
    CalendarEventRow,
    ChannelRow,
    ClassSessionRow,
    ContentDraftRow,
    CustomerRow,
    InquiryRow,
    OrderRow,
    RecommendationRow,
    SettingItemRow,
    ShipmentRow,
    TaskRow,
    WorkshopRow,
)

type SeedValue = str | int | float | bool | date | datetime | list[str] | None
type SeedRow = Mapping[str, SeedValue]
type SeedTable = tuple[type[Base], Sequence[SeedRow]]

STORE = "channel-naver-store"
INSTAGRAM = "channel-instagram"
BOOKING = "channel-naver-booking"
CUSTOMERS = (
    ("jung-eunju", "정은주", "010-2841-1934"),
    ("han-yuna", "한유나", "010-7312-4408"),
    ("oh-junho", "오준호", "010-5520-1187"),
    ("park-jieun", "박지은", "010-9043-2271"),
    ("choi-minwoo", "최민우", "010-3382-6610"),
    ("lee-sujin", "이수진", "010-6175-0932"),
    ("moon-gayoung", "문가영", "010-4406-7725"),
    ("kim-seoyeon", "김서연", "010-8254-3316"),
    ("lim-dohyun", "임도현", "010-2297-5084"),
    ("an-yeji", "안예지", "010-7718-9023"),
    ("choi-haseo", "최하서", "010-3640-1259"),
    ("yoon-sua", "윤수아", "010-5093-8846"),
    ("jung-taeu", "정태우", "010-9126-4470"),
    ("kim-haneul", "김하늘", "010-4471-2085"),
    ("lee-doyoon", "이도윤", "010-6638-1702"),
    ("park-seoyeon", "박서연", "010-2905-7316"),
)


def customers() -> list[SeedRow]:
    """Build customer rows."""
    return [{"id": f"customer-{key}", "name": name, "phone": phone} for key, name, phone in CUSTOMERS]


def channels() -> list[SeedRow]:
    """Build channels; none has a live integration yet."""
    return [
        {
            "id": INSTAGRAM,
            "kind": "instagram",
            "name": "Instagram",
            "handle": "@orot.studio",
            "connection": "not_connected",
            "sort_order": 1,
        },
        {
            "id": STORE,
            "kind": "naver_store",
            "name": "네이버 스마트스토어",
            "handle": "오롯 공방",
            "connection": "not_connected",
            "sort_order": 2,
        },
        {
            "id": BOOKING,
            "kind": "naver_booking",
            "name": "네이버 예약",
            "handle": "오롯 공방 클래스",
            "connection": "not_connected",
            "sort_order": 3,
        },
    ]


class SeedCalendar:
    """Date arithmetic for one seeding day."""

    def __init__(self, today: date) -> None:
        """Anchor all seed dates."""
        self.today: date = today
        days_to_saturday = (5 - today.weekday()) % 7 or 7
        self.saturday: date = today + timedelta(days=days_to_saturday)
        self.last_month: date = previous_month(month_start(today))

    def at(self, offset: int, hour: int, minute: int = 0) -> datetime:
        """Return a time relative to the seeding day."""
        return datetime.combine(self.today + timedelta(days=offset), time(hour, minute), SEOUL)

    def last_month_at(self, day: int, hour: int) -> datetime:
        """Return a time inside the previous calendar month."""
        return datetime.combine(self.last_month + timedelta(days=day), time(hour), SEOUL)


def sessions(cal: SeedCalendar) -> list[SeedRow]:
    """Build classes around the seeding day."""

    def row(
        key: str, title: str, starts: datetime, shape: tuple[int, int, int], status: str = "scheduled",
    ) -> SeedRow:
        duration, capacity, deposit = shape
        return {
            "id": f"session-{key}",
            "title": title,
            "starts_at": starts,
            "duration_minutes": duration,
            "capacity": capacity,
            "deposit_won": deposit,
            "status": status,
        }

    oneday, mug, wheel, weekend = (
        "도자기 원데이 클래스",
        "나만의 머그컵 만들기",
        "원데이 물레 체험",
        "주말 도자기 클래스",
    )
    saturday = datetime.combine(cal.saturday, time(10), SEOUL)
    return [
        row("today-morning", oneday, cal.at(0, 10), (90, 6, 20000), "completed"),
        row("today-afternoon", mug, cal.at(0, 14), (120, 6, 20000)),
        row("tomorrow-mug", mug, cal.at(1, 14), (120, 6, 20000)),
        row("wheel", wheel, cal.at(3, 11), (90, 4, 30000)),
        row("weekend", weekend, saturday, (120, 8, 25000)),
        row("next-oneday", oneday, cal.at(7, 10), (90, 6, 20000)),
        row("next-mug", mug, cal.at(9, 14), (120, 6, 20000)),
        row("past-oneday", oneday, cal.at(-3, 10), (90, 6, 20000), "completed"),
        row("past-mug", mug, cal.at(-1, 14), (120, 6, 20000), "completed"),
        row("last-month-a", oneday, cal.last_month_at(8, 10), (90, 6, 20000), "completed"),
        row("last-month-b", weekend, cal.last_month_at(15, 10), (120, 8, 25000), "completed"),
    ]


def bookings(cal: SeedCalendar) -> list[SeedRow]:
    """Build bookings; seat totals are computed from these rows."""

    def row(key: str, parties: tuple[str, str, int], deposit: int, due: datetime | None = None) -> SeedRow:
        session, customer, party = parties
        return {
            "id": f"booking-{key}",
            "session_id": f"session-{session}",
            "customer_id": f"customer-{customer}",
            "channel_id": BOOKING,
            "party_size": party,
            "deposit_won": deposit,
            "status": "deposit_pending" if due else "confirmed",
            "deposit_due_at": due,
            "deposit_confirmed_at": None if due else cal.at(-7, 12),
        }

    return [
        row("eunju", ("today-morning", "jung-eunju", 4), 20000),
        row("yuna", ("today-afternoon", "han-yuna", 2), 20000),
        row("junho", ("today-afternoon", "oh-junho", 2), 20000),
        row("jieun", ("tomorrow-mug", "park-jieun", 2), 20000, cal.at(0, 18)),
        row("minwoo", ("wheel", "choi-minwoo", 1), 30000, cal.at(1, 12)),
        row("sujin", ("weekend", "lee-sujin", 3), 25000),
        row("gayoung", ("weekend", "moon-gayoung", 2), 25000),
        row("dohyun", ("next-oneday", "lim-dohyun", 2), 20000),
        row("yeji", ("next-mug", "an-yeji", 3), 20000),
        row("past-haseo", ("past-oneday", "choi-haseo", 2), 20000),
        row("past-sua", ("past-mug", "yoon-sua", 4), 20000),
        row("last-taeu", ("last-month-a", "jung-taeu", 2), 20000),
        row("last-seoyeon", ("last-month-a", "kim-seoyeon", 2), 20000),
        row("last-eunju", ("last-month-b", "jung-eunju", 3), 25000),
    ]


def orders_and_shipments(cal: SeedCalendar) -> tuple[list[SeedRow], list[SeedRow]]:
    """Build orders with consistent fulfilment rows."""
    orders: list[SeedRow] = []
    shipments: list[SeedRow] = []

    def order(number: int, item: tuple[str, str, int, int], ordered: datetime, status: str) -> str:
        customer, product, quantity, amount = item
        order_id = f"order-{number}"
        orders.append(
            {
                "id": order_id,
                "order_number": number,
                "customer_id": f"customer-{customer}",
                "channel_id": STORE,
                "product_name": product,
                "quantity": quantity,
                "amount_won": amount,
                "status": status,
                "ordered_at": ordered,
                "confirmed_at": None if status == "paid" else ordered + timedelta(hours=2),
            },
        )
        return order_id

    def shipment(order_id: str, status: str, ship_by: datetime, note: str | None = None) -> None:
        moved = status in {"in_transit", "delivered"}
        delivered = status == "delivered"
        shipped = ship_by if moved else None
        shipments.append(
            {
                "id": f"shipment-{order_id}",
                "order_id": order_id,
                "status": status,
                "ship_by_at": ship_by,
                "handling_note": note,
                "carrier": "CJ대한통운" if moved else None,
                "tracking_number": f"6{order_id[-4:]}{ship_by:%m%d}2841" if moved else None,
                "packed_at": ship_by - timedelta(hours=3) if status != "packing" else None,
                "shipped_at": shipped,
                "expected_arrival_on": (ship_by + timedelta(days=2)).date() if moved else None,
                "delivered_at": ship_by + timedelta(days=2) if delivered else None,
            },
        )

    shipment(
        order(1031, ("yoon-sua", "핸드메이드 머그컵", 1, 24000), cal.at(-5, 11), "completed"),
        "delivered",
        cal.at(-3, 16),
    )
    shipment(
        order(1038, ("choi-haseo", "핸드메이드 커피잔", 1, 26000), cal.at(-2, 15), "processing"),
        "in_transit",
        cal.at(-1, 16),
    )
    shipment(
        order(1039, ("an-yeji", "도자기 찬기 3종 세트", 1, 48000), cal.at(-3, 9), "processing"),
        "in_transit",
        cal.at(-2, 16),
    )
    shipment(
        order(1040, ("kim-seoyeon", "머그컵 2종 세트", 1, 42000), cal.at(-1, 10), "processing"),
        "packing",
        cal.at(0, 16),
        "깨지지 않게 포장 필요",
    )
    shipment(
        order(1041, ("lee-sujin", "오롯 세라믹 플레이트", 2, 56000), cal.at(-1, 13), "processing"),
        "invoice_pending",
        cal.at(0, 16),
    )
    _ = order(1042, ("kim-seoyeon", "머그컵 2종 세트", 1, 42000), cal.at(0, 8, 12), "paid")
    _ = order(1043, ("jung-taeu", "핸드메이드 미니 화병", 1, 28000), cal.at(0, 8, 40), "paid")
    _ = order(1044, ("lee-sujin", "오롯 세라믹 플레이트", 2, 56000), cal.at(0, 9, 5), "paid")
    for index, item in enumerate(
        (
            ("park-jieun", "핸드메이드 커피잔", 2, 52000),
            ("lim-dohyun", "도자기 찬기 3종 세트", 1, 48000),
        ),
    ):
        number = 1021 + index
        placed = cal.last_month_at(6 + index * 7, 11)
        shipment(order(number, item, placed, "completed"), "delivered", placed + timedelta(days=1))
    return orders, shipments


def content_drafts() -> list[SeedRow]:
    """Build promotional drafts awaiting review."""
    return [
        {
            "id": "draft-weekend-class",
            "channel_id": INSTAGRAM,
            "title": "주말 클래스 모집 글",
            "summary": "주말 도자기 클래스의 남은 자리를 알리는 글이에요.",
            "status": "draft",
            "reviewed_at": None,
            "body": (
                "이번 주말, 흙을 만지며 천천히 쉬어 가요. 오롯 공방 주말 도자기 클래스에 아직 자리가 있어요. "
                "처음이어도 괜찮아요. 프로필 링크에서 예약해 주세요."
            ),
        },
        {
            "id": "draft-keyring-result",
            "channel_id": INSTAGRAM,
            "title": "거북이 키링 이벤트 결과 글",
            "summary": "당첨자 발표를 담은 글이에요.",
            "status": "draft",
            "reviewed_at": None,
            "body": (
                "행운의 거북이 도자기 키링 이벤트에 함께해 주셔서 고마워요. "
                "당첨되신 분께는 오늘 안에 개별로 연락드릴게요. 다음 이벤트도 기대해 주세요."
            ),
        },
    ]


def tasks(cal: SeedCalendar) -> list[SeedRow]:
    """Build owner tasks and material orders."""

    def row(
        key: str, kind: str, text: tuple[str, str, str | None], due: datetime, done: datetime | None = None,
    ) -> SeedRow:
        title, detail, vendor = text
        return {
            "id": f"task-{key}",
            "kind": kind,
            "title": title,
            "detail": detail,
            "vendor": vendor,
            "due_at": due,
            "status": "done" if done else "open",
            "completed_at": done,
        }

    return [
        row("clay", "material", ("도자기용 점토 50kg", "주문 필요", "도예사"), cal.at(0, 12)),
        row("glaze", "material", ("투명 유약 5kg", "입고 확인", "점토M"), cal.at(4, 12)),
        row("market", "general", ("플리마켓 모집 조건 확인", "순천그린광장 달빛야행", None), cal.at(0, 17)),
        row("kiln", "general", ("가마 온도 점검", "다음 소성 전 확인", None), cal.at(2, 9)),
        row(
            "keyring",
            "channel",
            ("행운의 거북이 도자기 키링 이벤트 결과 올리기", "키링 이벤트 결과 발표", None),
            cal.at(0, 20),
        ),
    ]


def recommendations() -> list[SeedRow]:
    """Build recommendations; counts are added from live rows when read."""

    def row(key: str, kind: str, text: tuple[str, str], links: tuple[str | None, str | None]) -> SeedRow:
        title, body = text
        source, draft = links
        return {
            "id": f"recommendation-{key}",
            "kind": kind,
            "title": title,
            "body": body,
            "source_name": source,
            "draft_id": draft,
            "status": "open",
            "acknowledged_at": None,
        }

    return [
        row(
            "deposit",
            "deposit_reminder",
            ("예약금 확인이 필요해요", "입금 기한이 가까운 예약부터 확인해 주세요."),
            (None, None),
        ),
        row(
            "weekend",
            "seat_promotion",
            ("주말 클래스의 빈자리를 알려요", "SNS에 올릴 모집 글을 준비해 두었어요."),
            (None, "draft-weekend-class"),
        ),
        row(
            "market",
            "opportunity",
            ("순천 달빛야행 플리마켓, 참여해볼까요?", "참가 조건을 확인하고 공방 작품을 소개해 보세요."),
            ("순천그린광장 달빛야행 플리마켓", None),
        ),
    ]


def settings_items() -> list[SeedRow]:
    """Build owner-editable text."""

    def row(key: str, label: tuple[str, str], body: str, order: int, *, editable: bool = True) -> SeedRow:
        title, symbol = label
        return {
            "key": key,
            "section": "공방" if editable else "지원",
            "title": title,
            "symbol": symbol,
            "body": body,
            "is_editable": editable,
            "sort_order": order,
        }

    return [
        row(
            "booking_policy",
            ("예약·환불 규정", "doc.text"),
            (
                "예약은 예약금 입금을 확인한 뒤 확정돼요. "
                "수업 2일 전까지 일정을 바꾸거나 전액 환불받을 수 있어요."
            ),
            1,
        ),
        row(
            "customer_guide",
            ("고객 안내 문구", "text.bubble"),
            "앞치마와 도구는 공방에서 준비해요. 작품은 건조와 소성을 거쳐 약 3주 뒤 수령하실 수 있어요.",
            2,
        ),
        row(
            "help",
            ("도움말", "questionmark.circle"),
            "오늘 탭에서 할 일을 확인하고 운영 탭에서 예약, 주문, 배송, 문의를 처리해 주세요.",
            3,
            editable=False,
        ),
    ]


def calendar_events(cal: SeedCalendar) -> list[SeedRow]:
    """Build owner schedule entries."""
    return [
        {
            "id": "event-firing",
            "kind": "todo",
            "title": "가마 소성",
            "detail": "이번 주 작품 초벌",
            "starts_at": cal.at(1, 9),
        },
        {
            "id": "event-clay-delivery",
            "kind": "order",
            "title": "점토 입고",
            "detail": "도예사 배송 예정",
            "starts_at": cal.at(5, 11),
        },
    ]


def inquiries() -> list[SeedRow]:
    """Build the three opening inquiries."""

    def row(key: str, person: tuple[str, str], text: tuple[str, str, str], facts: list[str]) -> SeedRow:
        customer_id, customer = person
        subject, question, draft = text
        return {
            "id": f"inquiry-{key}",
            "customer": customer,
            "subject": subject,
            "question": question,
            "facts": facts,
            "draft": draft,
            "status": "pending",
            "revision": 0,
            "customer_id": f"customer-{customer_id}",
            "channel_id": STORE,
        }

    return [
        row(
            "clay",
            ("kim-haneul", "김하늘"),
            (
                "도자기 체험 준비물",
                "처음 도자기를 만들어 봐요. 준비물이 있을까요? 완성품은 당일 가져갈 수 있나요?",
                (
                    "안녕하세요! 처음 오셔도 괜찮아요. 앞치마와 도구는 준비되어 있어요. "
                    "수업은 90분이며, 작품은 건조와 소성 후 약 3주 뒤 수령하실 수 있어요."
                ),
            ),
            [
                "공방 안내 · 앞치마와 도구는 공방에서 드려요.",
                "수업 안내 · 초보자도 참여할 수 있는 90분 수업이에요.",
                "제작 안내 · 건조와 소성에 약 3주가 걸려서 당일에는 받아 가실 수 없어요.",
            ],
        ),
        row(
            "group",
            ("lee-doyoon", "이도윤"),
            (
                "두 사람 함께 참여",
                "친구와 둘이 같은 시간에 참여하고 싶어요. 예약이 바로 확정되나요?",
                (
                    "두 분이 함께 참여하실 수 있어요. 원하시는 날짜와 회차를 알려 주시면 "
                    "잔여 자리를 확인해 드릴게요. 이 답변만으로 예약이 확정되지는 않아요."
                ),
            ),
            [
                "예약 규정 · 예약은 따로 확인한 뒤 확정해요.",
                "수업 정원 · 한 회차 최대 6명이에요.",
                "예약 안내 · 문의 답변을 승인해도 예약은 자동으로 만들어지지 않아요.",
            ],
        ),
        row(
            "change",
            ("park-seoyeon", "박서연"),
            (
                "수업 일정 변경 안내",
                "예약한 수업 날짜를 바꾸고 싶어요. 어떻게 하면 되나요?",
                (
                    "수업 2일 전까지 일정을 바꿀 수 있어요. 지금 예약일과 원하는 날짜를 "
                    "알려주시면 남은 자리를 확인해 드릴게요."
                ),
            ),
            [
                "변경 규정 · 수업 2일 전까지 일정을 바꿀 수 있어요.",
                "예약 규정 · 바꿀 회차에 남은 자리가 있는지 확인해야 해요.",
            ],
        ),
    ]


def build_seed(today: date) -> list[SeedTable]:
    """Return tables in foreign-key order."""
    cal = SeedCalendar(today)
    orders, shipments = orders_and_shipments(cal)
    workshop: SeedRow = {
        "id": 1,
        "name": "오롯 공방",
        "owner_title": "사장님",
        "phone": "061-745-0255",
        "address": "전라남도 순천시 중앙로 255",
        "description": "흙으로 일상의 그릇을 만드는 도자기 공방이에요.",
        "latitude": None,
        "longitude": None,
    }
    return [
        (WorkshopRow, [workshop]),
        (CustomerRow, customers()),
        (ChannelRow, channels()),
        (ClassSessionRow, sessions(cal)),
        (BookingRow, bookings(cal)),
        (OrderRow, orders),
        (ShipmentRow, shipments),
        (ContentDraftRow, content_drafts()),
        (TaskRow, tasks(cal)),
        (CalendarEventRow, calendar_events(cal)),
        (RecommendationRow, recommendations()),
        (SettingItemRow, settings_items()),
        (InquiryRow, inquiries()),
    ]
