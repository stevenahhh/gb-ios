import SwiftUI
import UIKit

struct Metric: Identifiable, Hashable {
    let value: String
    let label: String
    var id: String { label }
}

enum StatusTone: Hashable {
    case attention
    case done
    case progress
    case neutral

    var color: Color {
        switch self {
        case .attention: .orange
        case .done: .green
        case .progress, .neutral: .secondary
        }
    }

    var symbol: String {
        switch self {
        case .attention: "exclamationmark.circle.fill"
        case .done: "checkmark.circle.fill"
        case .progress: "arrow.triangle.2.circlepath"
        case .neutral: "circle"
        }
    }
}

struct Status: Hashable {
    let text: String
    let tone: StatusTone
}

enum CardAction: Hashable {
    case perform(String)
    case open
}

struct WorkItem: Identifiable, Hashable {
    let id = UUID()
    let title: String
    var status: Status?
    var lines: [String]
    var deadline: String?
    var tag: String?
    var action: CardAction?
}

struct TaskItem: Identifiable, Hashable {
    let id = UUID()
    var time: String?
    let title: String
    let detail: String
    var status: Status?
    var isDone: Bool?
}

struct TaskGroup: Identifiable, Hashable {
    let title: String
    let kind: EventKind
    var area: OperationArea?
    let items: [TaskItem]
    var id: String { title }
}

enum EventKind: String, CaseIterable, Identifiable {
    case booking = "예약"
    case order = "주문"
    case delivery = "배송"
    case todo = "할 일"

    var id: Self { self }

    var uiColor: UIColor {
        switch self {
        case .booking: .systemBlue
        case .order: .systemBrown
        case .delivery: .systemTeal
        case .todo: .systemPurple
        }
    }

    var color: Color { Color(uiColor: uiColor) }

    var symbol: String {
        switch self {
        case .booking: "calendar"
        case .order: "bag"
        case .delivery: "shippingbox"
        case .todo: "checklist"
        }
    }

    var area: OperationArea? {
        switch self {
        case .booking: .bookings
        case .order: .orders
        case .delivery: .deliveries
        case .todo: nil
        }
    }
}

struct DayEvent: Hashable {
    let kind: EventKind
    let count: Int
}

struct AgendaItem: Identifiable, Hashable {
    let id = UUID()
    let time: String
    let title: String
    let kind: EventKind
    let detail: String
}

enum SampleData {
    static let today = DateComponents(calendar: Calendar(identifier: .gregorian), year: 2026, month: 11, day: 4)
    static let fixedAttentionCount = 4

    static func attentionCount(pendingInquiries: Int) -> Int {
        fixedAttentionCount + pendingInquiries
    }

    static let todayTaskGroups: [TaskGroup] = [
        TaskGroup(title: "예약", kind: .booking, area: .bookings, items: [
            TaskItem(time: "10:00", title: "도자기 원데이 클래스", detail: "네이버 · 정은주 님 외 3명 · 90분", isDone: true),
            TaskItem(time: "14:00", title: "나만의 머그컵 만들기", detail: "4명 · 120분", isDone: false),
        ]),
        TaskGroup(title: "배송", kind: .delivery, area: .deliveries, items: [
            TaskItem(title: "머그컵 세트 발송", detail: "네이버 · 2건 · 포장 필요", status: Status(text: "포장 대기", tone: .attention)),
            TaskItem(title: "그릇·접시 세트 발송", detail: "인스타그램 · 2건 · 출고 완료", status: Status(text: "발송 완료", tone: .done)),
        ]),
        TaskGroup(title: "재료 주문", kind: .order, items: [
            TaskItem(title: "도자기용 점토 50kg", detail: "도예사", status: Status(text: "주문 필요", tone: .attention)),
            TaskItem(title: "도자기용 점토 50kg", detail: "점토M", status: Status(text: "주문 완료", tone: .done)),
        ]),
    ]

    static let channelCards: [WorkItem] = [
        WorkItem(title: "Instagram", status: Status(text: "연결됨", tone: .done),
                 lines: ["@orot.studio", "팔로워 1,284 · 이번 주 +24"], action: .open),
        WorkItem(title: "네이버 스마트스토어", status: Status(text: "연결됨", tone: .done),
                 lines: ["오늘 주문 3건 · 결제금액 126,000원"], deadline: "문의 3건이 답을 기다려요", action: .open),
    ]

    static let channelTodos: [WorkItem] = [
        WorkItem(title: "행운의 거북이 도자기 키링 이벤트", lines: ["오늘 결과 발표일이에요."], action: .perform("이벤트 결과 올리기")),
        WorkItem(title: "SNS 콘텐츠 미리보기", lines: ["오늘 올릴 게시물을 확인해 주세요."], action: .open),
    ]

    static let shipToday: [WorkItem] = [
        WorkItem(title: "머그컵 2종 세트", status: Status(text: "포장 대기", tone: .attention),
                 lines: ["김*연 · 주문 #1042 · 1개"], action: .perform("포장 완료하기")),
        WorkItem(title: "오롯 세라믹 플레이트", status: Status(text: "송장 대기", tone: .attention),
                 lines: ["이*진 · 주문 #1043 · 2개"], action: .perform("송장 등록하기")),
    ]

    static let inTransit: [WorkItem] = [
        WorkItem(title: "도자기 찬기 3종 세트", status: Status(text: "배송 중", tone: .progress),
                 lines: ["안*지 · 주문 #1044 · 1개", "오늘 도착 예정"], action: .open),
        WorkItem(title: "핸드메이드 커피잔", status: Status(text: "배송 중", tone: .progress),
                 lines: ["최*서 · 주문 #1038 · 1개", "내일 도착 예정"], action: .open),
    ]

    static let suggestions: [WorkItem] = [
        WorkItem(title: "작품 수령을 기다리는 손님이 있어요",
                 lines: ["소성이 끝난 작품 2건이 수령 대기 중이에요.", "손님께 보낼 수령 안내를 준비할까요?"],
                 action: .perform("수령 안내 준비하기")),
        WorkItem(title: "주말 클래스의 빈자리를 알려요",
                 lines: ["토요일 클래스에 3자리가 남아 있어요.", "SNS에 올릴 모집 글을 준비해 두었어요."],
                 action: .open),
        WorkItem(title: "순천 달빛야행 플리마켓, 참여해볼까요?",
                 lines: ["순천시청 · 순천그린광장 달빛야행 플리마켓 모집 공고", "참가 조건을 확인하고 공방 작품을 소개해보세요."],
                 action: .open),
    ]

    static let novemberEvents: [Int: [DayEvent]] = [
        2: [DayEvent(kind: .booking, count: 2)],
        3: [DayEvent(kind: .order, count: 1)],
        4: [DayEvent(kind: .booking, count: 1), DayEvent(kind: .order, count: 1), DayEvent(kind: .delivery, count: 1), DayEvent(kind: .todo, count: 1)],
        5: [DayEvent(kind: .delivery, count: 2)],
        6: [DayEvent(kind: .todo, count: 1)],
        7: [DayEvent(kind: .booking, count: 3)],
        10: [DayEvent(kind: .booking, count: 2)],
        12: [DayEvent(kind: .delivery, count: 2)],
        14: [DayEvent(kind: .booking, count: 4)],
        17: [DayEvent(kind: .order, count: 1)],
        19: [DayEvent(kind: .delivery, count: 2)],
        21: [DayEvent(kind: .booking, count: 3)],
        24: [DayEvent(kind: .todo, count: 1)],
        27: [DayEvent(kind: .order, count: 2)],
        28: [DayEvent(kind: .booking, count: 4)],
    ]

    static let agenda: [Int: [AgendaItem]] = [
        4: [
            AgendaItem(time: "10:00", title: "도자기 원데이 클래스", kind: .booking, detail: "예약 4명 · 90분"),
            AgendaItem(time: "13:00", title: "온라인 주문 확인", kind: .order, detail: "머그컵 세트 · 신규 주문 3건"),
            AgendaItem(time: "16:00", title: "택배 발송 마감", kind: .delivery, detail: "포장 완료 2건 · 택배 수거 예정"),
            AgendaItem(time: "17:00", title: "플리마켓 모집 조건 확인", kind: .todo, detail: "순천그린광장 달빛야행"),
        ],
    ]

    static func eventCount(on day: Int) -> Int {
        (novemberEvents[day] ?? []).reduce(0) { $0 + $1.count }
    }
}
