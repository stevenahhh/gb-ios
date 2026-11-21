import SwiftUI
import UIKit

extension Color {
    /// The app's only red. It marks "기한 지남", its clock, and the calendar's missed node, nothing else.
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

/// The one place that turns a date into 오늘, 어제, N일 뒤, or a month-day.
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

    /// "어제 16:00"
    static func moment(_ date: Date, now: Date, calendar: Calendar = .workshop) -> String {
        let parts = calendar.dateComponents([.hour, .minute], from: date)
        return "\(day(date, now: now, calendar: calendar)) \(String(format: "%02d:%02d", parts.hour ?? 0, parts.minute ?? 0))"
    }
}

/// A deadline line: a plain clock before it is due, "기한 지남" in red once it passes.
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
            let moment = RelativeDayFormatter.moment(date, now: now)
            // An HStack, not a Label: List would move a Label's icon into its leading icon column.
            HStack(alignment: .firstTextBaseline, spacing: 5) {
                if due.isOverdue(at: now) {
                    Image(systemName: "clock")
                        .foregroundStyle(Color.overdueRed)
                        .accessibilityHidden(true)
                    let rest = [moment, due.missed].compactMap { $0 }.joined(separator: " ")
                    Text("\(Text("기한 지남").foregroundStyle(Color.overdueRed).fontWeight(.semibold)) · \(rest)")
                        .foregroundStyle(.secondary)
                } else {
                    Image(systemName: "clock")
                        .foregroundStyle(.secondary)
                        .accessibilityHidden(true)
                    Text("\(due.prefix.map { "\($0) " } ?? "")\(moment)\(due.suffix)")
                        .foregroundStyle(.primary)
                }
            }
            .font(font)
            .accessibilityElement(children: .combine)
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

/// Menu icons share one weight, color, and column so every row's text starts at the same place.
struct MenuIcon: View {
    let systemName: String

    var body: some View {
        Image(systemName: systemName.replacingOccurrences(of: ".fill", with: ""))
            .font(.system(size: 22, weight: .regular))
            .symbolRenderingMode(.monochrome)
            .foregroundStyle(.primary)
            .frame(width: 28)
            .accessibilityHidden(true)
    }
}
