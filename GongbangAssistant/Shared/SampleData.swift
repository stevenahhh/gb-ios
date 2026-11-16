import SwiftUI
import UIKit

struct Metric: Identifiable, Hashable {
    let value: String
    let label: String
    var id: String { label }
}

struct TaskItem: Identifiable, Hashable {
    let id = UUID()
    let leading: String
    let title: String
    let detail: String
    var badge: String?
    var isDone: Bool?
}

struct TaskGroup: Identifiable, Hashable {
    let title: String
    let items: [TaskItem]
    var id: String { title }
}

struct WorkItem: Identifiable, Hashable {
    let id = UUID()
    let title: String
    var status: String?
    let lines: [String]
    var action: String?
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
        case .order: .systemOrange
        case .delivery: .systemGreen
        case .todo: .systemPurple
        }
    }

    var color: Color { Color(uiColor: uiColor) }
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

    static let todayTaskGroups: [TaskGroup] = [
        TaskGroup(title: "예약", items: [
            TaskItem(leading: "10:00", title: "도자기 원데이 클래스", detail: "정은주 님 | 4명 · 90분", isDone: true),
            TaskItem(leading: "14:00", title: "나만의 머그컵 만들기", detail: "예약 4명 · 120분", isDone: false),
        ]),
        TaskGroup(title: "배송", items: [
            TaskItem(leading: "네이버", title: "온라인 주문 발송", detail: "머그컵 세트 외 1건 · 포장 필요", badge: "배송 전"),
            TaskItem(leading: "인스타", title: "온라인 주문 출고 완료", detail: "그릇·접시 세트 외 1건 · 출고 완료", badge: "출고"),
        ]),
        TaskGroup(title: "주문", items: [
            TaskItem(leading: "도예사", title: "재료 주문 입고", detail: "도자기용 점토 50kg", badge: "주문 하기"),
            TaskItem(leading: "점토M", title: "재료 주문 완료", detail: "도자기용 점토 50kg", badge: "주문 완료"),
        ]),
    ]

    static let channelCards: [WorkItem] = [
        WorkItem(title: "Instagram", status: "연결됨", lines: ["@orot.studio", "팔로워 1,284 · 이번 주 +24"]),
        WorkItem(title: "네이버 스마트스토어", status: "연결됨",
                 lines: ["오늘 주문 3건 · 결제금액 126,000원", "상품 문의 2건이 기다리고 있어요"], action: "확인하기"),
    ]

    static let channelTodos: [WorkItem] = [
        WorkItem(title: "행운의 거북이 도자기 키링 이벤트", lines: ["오늘 발표날이니 준비해주세요 !"], action: "이벤트 결과 올리기"),
        WorkItem(title: "SNS 콘텐츠 미리보기 확인", lines: ["오늘 업로드할 포스팅 내용을 확인해 주세요."], action: "미리보기 확인하기"),
    ]

    static let deliveryCards: [WorkItem] = [
        WorkItem(title: "머그컵 2종 세트", status: "포장 대기", lines: ["김*연 · 주문 #1042 · 1개"], action: "포장 완료로 변경"),
        WorkItem(title: "오롯 세라믹 플레이트", status: "송장 대기", lines: ["이*진 · 주문 #1043 · 2개"], action: "송장 등록하기"),
        WorkItem(title: "도자기 찬기 3종 세트", status: "송장 대기", lines: ["안*지 · 주문 #1044 · 1개"], action: "배송 조회"),
    ]

    static let suggestions: [WorkItem] = [
        WorkItem(title: "순천 달빛야행 플리마켓, 참여해볼까요?",
                 lines: ["순천시청 · 순천그린광장 달빛야행 플리마켓 모집 공고", "참가 조건을 확인하고 공방 작품을 소개해보세요."],
                 action: "모집 공고 확인하기"),
        WorkItem(title: "주말 클래스의 빈자리를 알려요",
                 lines: ["토요일 클래스에 3자리가 남아 있어요.", "SNS에 올릴 모집 글을 준비해 두었어요."],
                 action: "홍보 글 초안 보기"),
        WorkItem(title: "작품 수령을 기다리는 손님이 있어요",
                 lines: ["소성이 끝난 작품 2건이 수령 대기 중이에요.", "손님께 보낼 수령 안내를 준비할까요?"],
                 action: "수령 안내 준비하기"),
    ]

    static let novemberEvents: [Int: [EventKind]] = [
        2: [.booking], 3: [.order], 4: [.booking, .order, .delivery, .todo], 5: [.delivery], 6: [.todo], 7: [.booking],
        10: [.booking], 12: [.delivery], 14: [.booking],
        17: [.order], 19: [.delivery], 21: [.booking],
        24: [.todo], 27: [.order], 28: [.booking],
    ]

    static let agenda: [Int: [AgendaItem]] = [
        4: [
            AgendaItem(time: "10:00", title: "도자기 원데이 클래스", kind: .booking, detail: "예약 4명 · 90분"),
            AgendaItem(time: "13:00", title: "온라인 주문 확인", kind: .order, detail: "머그컵 세트 · 신규 주문 3건"),
            AgendaItem(time: "16:00", title: "택배 발송 마감", kind: .delivery, detail: "포장 완료 2건 · 집하 예정"),
            AgendaItem(time: "17:00", title: "플리마켓 모집 조건 확인", kind: .todo, detail: "순천그린광장 달빛야행"),
        ],
    ]
}
