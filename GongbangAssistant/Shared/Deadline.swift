import SwiftUI
import UIKit

extension Color {
    /// The app's only red. It colors `OverdueMark`, the clock on an item past its deadline, and nothing else.
    static let overdueRed = Color(uiColor: UIColor { @Sendable traits in
        traits.userInterfaceStyle == .dark
            ? UIColor(red: 1, green: 0x6B / 255, blue: 0x60 / 255, alpha: 1)
            : UIColor(red: 0xC6 / 255, green: 0x28 / 255, blue: 0x28 / 255, alpha: 1)
    })
}

/// A deadline the server sends as a moment; 오늘·어제 and 기한 지남 are worked out when drawn.
struct CardDue: Decodable, Hashable {
    let at: String
    let prefix: String?
    let suffix: String
    let missed: String?

    var date: Date? { try? Date(at, strategy: .iso8601) }

    func isOverdue(at now: Date) -> Bool { date.map { $0 < now } ?? false }
}

/// The one place that turns a date into 오늘, 어제, N일 뒤, or a month-day, and a past moment into N초 전.
enum RelativeDayFormatter {
    static func day(_ date: Date, now: Date, calendar: Calendar = .workshop) -> String {
        let days = calendar.dateComponents([.day], from: calendar.startOfDay(for: now),
                                           to: calendar.startOfDay(for: date)).day ?? 0
        switch days {
        case 0: return "오늘"
        case 1: return "내일"
        case -1: return "어제"
        case 2...6: return "\(days)일 뒤"
        case -6 ... -2: return "\(-days)일 전"
        default:
            let parts = calendar.dateComponents([.month, .day, .weekday], from: date)
            let weekday = ["일", "월", "화", "수", "목", "금", "토"][(parts.weekday ?? 1) - 1]
            return "\(parts.month ?? 0)월 \(parts.day ?? 0)일 (\(weekday))"
        }
    }

    /// "방금", "12초 전", "3분 전", "2시간 전", then the day.
    static func elapsed(since date: Date, now: Date, calendar: Calendar = .workshop) -> String {
        let seconds = Int(now.timeIntervalSince(date))
        switch seconds {
        case ..<1: return "방금"
        case ..<60: return "\(seconds)초 전"
        case ..<3600: return "\(seconds / 60)분 전"
        case ..<86_400: return "\(seconds / 3600)시간 전"
        default: return day(date, now: now, calendar: calendar)
        }
    }

    /// "어제 16:00"
    static func moment(_ date: Date, now: Date, calendar: Calendar = .workshop) -> String {
        let parts = calendar.dateComponents([.hour, .minute, .second], from: date)
        if parts.hour == 23, parts.minute == 59, parts.second == 59 { return day(date, now: now, calendar: calendar) }
        return "\(day(date, now: now, calendar: calendar)) \(String(format: "%02d:%02d", parts.hour ?? 0, parts.minute ?? 0))"
    }
}

/// The one overdue marker: a red clock with no words, at the top-left of the item. VoiceOver reads 기한 지남.
struct OverdueMark: View {
    var body: some View {
        Image(systemName: "clock.fill")
            .foregroundStyle(Color.overdueRed)
            .accessibilityLabel("기한 지남")
    }
}

/// `OverdueMark` for a deadline: nothing until it passes, then the mark. It checks again every minute.
struct DueMark: View {
    let due: CardDue?
    /// Space after the mark. It belongs to the mark, so a title it leads stays put while the mark is absent.
    var gap: CGFloat = 0

    var body: some View {
        TimelineView(.everyMinute) { context in
            if due?.isOverdue(at: context.date) == true {
                OverdueMark()
                    .padding(.trailing, gap)
            }
        }
    }
}

extension View {
    /// Leads an item's title with the overdue mark once `due` has passed. Set the font after this call, so the mark
    /// takes the title's size and grows with Dynamic Type.
    func overdueMark(for due: CardDue?) -> some View {
        HStack(alignment: .firstTextBaseline, spacing: 0) {
            DueMark(due: due, gap: 5)
            self
        }
    }
}

/// A deadline line: a plain clock and the moment before it is due. Once it passes the line turns gray and loses its
/// clock, because the item's `OverdueMark` says so.
struct DueLabel: View {
    let due: CardDue
    var font: Font = .subheadline

    var body: some View {
        TimelineView(.everyMinute) { context in
            content(now: context.date)
        }
    }

    @ViewBuilder
    private func content(now: Date) -> some View {
        if let date = due.date {
            let lead = "\(due.prefix.map { "\($0) " } ?? "")\(RelativeDayFormatter.moment(date, now: now))"
            if due.isOverdue(at: now) {
                Text("\(lead)\(due.missed.map { " \($0)" } ?? due.suffix)")
                    .font(font)
                    .foregroundStyle(Color.secondaryText)
            } else {
                // An HStack, not a Label: List would move a Label's icon into its leading icon column.
                HStack(alignment: .firstTextBaseline, spacing: 5) {
                    Image(systemName: "clock")
                        .foregroundStyle(Color.secondaryText)
                        .accessibilityHidden(true)
                    Text("\(lead)\(due.suffix)")
                        .foregroundStyle(.primary)
                }
                .font(font)
                .accessibilityElement(children: .combine)
            }
        }
    }
}

protocol HasDue {
    var due: CardDue? { get }
}

extension Array where Element: HasDue {
    /// Overdue rows first, keeping the server's order inside each part.
    func overdueFirst(now: Date = .now) -> [Element] {
        filter { $0.due?.isOverdue(at: now) == true } + filter { $0.due?.isOverdue(at: now) != true }
    }
}

/// Menu icons share one weight and color. The list's label style sizes the symbol (body text style, large
/// symbol scale) and reserves its column, so every row's text starts at the same place.
/// A label icon inside a list never sets a point size; if it must be smaller, use `.imageScale(.medium)`.
struct MenuIcon: View {
    let systemName: String

    var body: some View {
        Image(systemName: systemName.replacingOccurrences(of: ".fill", with: ""))
            .symbolRenderingMode(.monochrome)
            .foregroundStyle(.primary)
            .accessibilityHidden(true)
    }
}

#Preview("메뉴 아이콘") {
    List {
        ForEach(["storefront", "link", "clock.arrow.circlepath", "bubble.left.and.bubble.right"], id: \.self) { symbol in
            Label { Text(symbol) } icon: { MenuIcon(systemName: symbol) }
        }
    }
}
