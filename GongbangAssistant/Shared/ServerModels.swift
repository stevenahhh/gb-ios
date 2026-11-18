import SwiftUI
import UIKit
import RoundupCore

struct Metric: Decodable, Identifiable, Hashable {
    let key: String
    let label: String
    let display: String
    var id: String { key }
}

enum StatusTone: String, Decodable, Hashable {
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

struct Status: Decodable, Hashable {
    let text: String
    let tone: StatusTone
}

enum ActionCode: String, Decodable, Hashable {
    case confirmDeposit
    case confirmOrder
    case pack
    case registerInvoice
    case markDelivered
    case reviewContent
    case completeTask
    case acknowledgeRecommendation
}

struct CardAction: Decodable, Hashable {
    let code: ActionCode
    let label: String
}

struct WorkItem: Decodable, Identifiable, Hashable {
    let id: String
    let title: String
    let status: Status?
    let lines: [String]
    let deadline: String?
    let tag: String?
    let revision: Int
    let action: CardAction?
}

enum TaskTarget: String, Decodable, Hashable {
    case session
    case task
    case shipment
}

struct TaskItem: Decodable, Identifiable, Hashable {
    let id: String
    let target: TaskTarget
    let time: String?
    let title: String
    let detail: String
    let status: Status?
    let isDone: Bool?
    let revision: Int
}

struct TaskGroup: Decodable, Identifiable, Hashable {
    let title: String
    let kind: EventKind
    let area: OperationArea?
    let items: [TaskItem]
    var id: String { title }
}

enum EventKind: String, Decodable, CaseIterable, Identifiable, Hashable {
    case booking
    case order
    case delivery
    case todo

    var id: Self { self }

    var label: String {
        switch self {
        case .booking: "예약"
        case .order: "주문"
        case .delivery: "배송"
        case .todo: "할 일"
        }
    }

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
}

struct DayEvent: Decodable, Hashable {
    let kind: EventKind
    let count: Int
    let display: String
}

struct AgendaItem: Decodable, Identifiable, Hashable {
    let id: String
    let time: String
    let title: String
    let kind: EventKind
    let detail: String
}

struct CalendarDay: Decodable, Hashable {
    let date: String
    let events: [DayEvent]
    let items: [AgendaItem]
}

struct CalendarRange: Decodable {
    let days: [CalendarDay]
}

struct TodayScreenData: Decodable {
    struct Tasks: Decodable {
        let metrics: [Metric]
        let groups: [TaskGroup]
    }

    struct Channels: Decodable {
        let metrics: [Metric]
        let cards: [WorkItem]
        let todos: [WorkItem]
    }

    struct Delivery: Decodable {
        let metrics: [Metric]
        let shipToday: [WorkItem]
        let inTransit: [WorkItem]
        let transitSummary: String
        let transitDetail: String
    }

    struct Suggestions: Decodable {
        let metrics: [Metric]
        let items: [WorkItem]
    }

    let date: String
    let attentionCount: Int
    let tasks: Tasks
    let channels: Channels
    let delivery: Delivery
    let suggestions: Suggestions

    var hasNoWork: Bool {
        tasks.groups.isEmpty && channels.cards.isEmpty && channels.todos.isEmpty
            && delivery.shipToday.isEmpty && delivery.inTransit.isEmpty && suggestions.items.isEmpty
    }
}

struct AreaPage: Decodable {
    let metrics: [Metric]
    let items: [WorkItem]
    let inquiries: [Inquiry]?
    let total: Int
    let hasMore: Bool
}

struct MonthOption: Decodable, Identifiable, Hashable {
    let key: String
    let title: String
    let range: String
    var id: String { key }
}

struct OperationsData: Decodable {
    struct Comparison: Decodable, Identifiable {
        let label: String
        let display: String
        var id: String { label }
    }

    struct Period: Decodable {
        let month: MonthOption
        let handled: Int
        let total: Int
        let ratePercent: Int?
        let rateDisplay: String
        let metrics: [Metric]
        let comparisons: [Comparison]
    }

    struct AreaSummary: Decodable {
        let area: OperationArea
        let display: String
    }

    let attentionCount: Int
    let attention: [Metric]
    let period: Period
    let months: [MonthOption]
    let areas: [AreaSummary]
}

struct WorkshopProfile: Decodable, Hashable {
    let name: String
    let ownerTitle: String
    let phone: String
    let address: String
    let description: String
    let latitude: Double?
    let longitude: Double?
    let revision: Int
}

struct SettingItem: Decodable, Identifiable, Hashable {
    let key: String
    let section: String
    let title: String
    let symbol: String
    let body: String
    let isEditable: Bool
    let revision: Int
    var id: String { key }
}

struct SettingsData: Decodable {
    let workshop: WorkshopProfile?
    let items: [SettingItem]
    let channels: [WorkItem]
}

struct SessionOption: Decodable, Identifiable, Hashable {
    let id: String
    let title: String
    let schedule: String
    let remainingSeats: Int
    let deposit: String
}

struct ContentDetail: Decodable {
    let id: String
    let title: String
    let channel: String
    let body: String
    let isReviewed: Bool
    let revision: Int
}

extension Calendar {
    /// Business days follow the workshop's time zone, like the server.
    static let workshop: Calendar = {
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = TimeZone(identifier: "Asia/Seoul") ?? .gmt
        calendar.locale = Locale(identifier: "ko_KR")
        calendar.firstWeekday = 2
        return calendar
    }()
}

extension Date {
    /// `yyyy-MM-dd` in the workshop time zone, the key the server uses.
    var dayKey: String {
        let parts = Calendar.workshop.dateComponents([.year, .month, .day], from: self)
        return String(format: "%04d-%02d-%02d", parts.year ?? 0, parts.month ?? 0, parts.day ?? 0)
    }

    func koreanDay(weekday: Bool = true) -> String {
        var style = Date.FormatStyle(locale: Locale(identifier: "ko_KR"), timeZone: Calendar.workshop.timeZone)
            .month().day()
        if weekday { style = style.weekday(.wide) }
        return formatted(style)
    }
}
