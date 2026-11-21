import SwiftUI

enum CalendarMode: String, CaseIterable, Identifiable {
    case week = "주간"
    case month = "월간"
    var id: Self { self }
}

struct ModeSegment: View {
    @Binding var mode: CalendarMode
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @Namespace private var pill

    var body: some View {
        HStack(spacing: 0) {
            ForEach(CalendarMode.allCases) { option in
                let isSelected = option == mode
                Button {
                    withAnimation(reduceMotion ? .easeInOut(duration: 0.2) : .spring(duration: 0.25)) { mode = option }
                } label: {
                    Text(option.rawValue)
                        .font(.subheadline.weight(isSelected ? .semibold : .regular))
                        .foregroundStyle(isSelected ? CalendarTokens.label : CalendarTokens.secondary)
                        .frame(maxWidth: .infinity, minHeight: 32)
                        .background {
                            if isSelected {
                                Capsule()
                                    .fill(CalendarTokens.background)
                                    .shadow(color: .black.opacity(0.08), radius: 3, y: 1)
                                    .matchedGeometryEffect(id: "pill", in: pill)
                            }
                        }
                        .contentShape(.capsule)
                }
                .buttonStyle(.plain)
                .accessibilityAddTraits(isSelected ? .isSelected : [])
                .accessibilityIdentifier(option == .week ? "calendar.mode.week" : "calendar.mode.month")
            }
        }
        .padding(3)
        .frame(height: 38)
        .background(CalendarTokens.fill, in: .capsule)
    }
}

/// The period label with today and previous/next controls, shared by the week and month views.
struct PeriodNavigator: View {
    let title: String
    let isShowingToday: Bool
    let today: () -> Void
    let move: (Int) -> Void

    var body: some View {
        HStack(spacing: 4) {
            Text(title)
                .font(.headline)
                .foregroundStyle(CalendarTokens.label)
                .accessibilityAddTraits(.isHeader)
            Spacer(minLength: 8)
            // While today is showing the word turns gray and regular instead of fading: at 40% it measured 2.4:1.
            Button(action: today) {
                Text("오늘")
                    .font(.subheadline.weight(isShowingToday ? .regular : .semibold))
                    .foregroundStyle(isShowingToday ? CalendarTokens.secondary : CalendarTokens.label)
                    .padding(.horizontal, 12)
                    .frame(height: 32)
                    .background(CalendarTokens.fill, in: .capsule)
                    .frame(minHeight: 44)
                    .contentShape(.rect)
            }
            .buttonStyle(PressDimStyle())
            .disabled(isShowingToday)
            .accessibilityIdentifier("calendar.today")
            arrow("chevron.left", label: "이전") { move(-1) }
            arrow("chevron.right", label: "다음") { move(1) }
        }
    }

    private func arrow(_ symbol: String, label: String, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Image(systemName: symbol)
                .font(.body.weight(.semibold))
                .foregroundStyle(CalendarTokens.label)
                .frame(width: 40, height: 44)
                .contentShape(.rect)
        }
        .buttonStyle(.plain)
        .accessibilityLabel(label)
    }
}

/// One date in the week strip or month grid; dots show the amount of schedule, never its kind.
struct DayCell: View {
    let date: Date
    let weekday: String?
    let isSelected: Bool
    let isToday: Bool
    let count: Int
    let diameter: CGFloat
    let select: () -> Void

    private var dots: Int {
        switch count {
        case 0: 0
        case 1...2: 1
        case 3...5: 2
        default: 3
        }
    }

    var body: some View {
        Button(action: select) {
            VStack(spacing: 6) {
                if let weekday {
                    Text(weekday)
                        .font(.subheadline.weight(isSelected ? .bold : .regular))
                        .foregroundStyle(isSelected ? CalendarTokens.label : CalendarTokens.secondary)
                }
                Text("\(Calendar.workshop.component(.day, from: date))")
                    .font(.body.weight(isSelected ? .bold : isToday ? .semibold : .medium))
                    .monospacedDigit()
                    .foregroundStyle(isSelected ? CalendarTokens.background : CalendarTokens.label)
                    .frame(width: diameter, height: diameter)
                    .background {
                        if isSelected {
                            Circle().fill(CalendarTokens.label)
                        } else if isToday {
                            Circle().strokeBorder(CalendarTokens.label, lineWidth: 1.5)
                        }
                    }
                HStack(spacing: 3) {
                    ForEach(0..<dots, id: \.self) { _ in
                        Circle()
                            .fill(isSelected ? CalendarTokens.label : CalendarTokens.tertiary)
                            .frame(width: 4, height: 4)
                    }
                }
                .frame(height: 4)
            }
            .frame(maxWidth: .infinity, minHeight: 44)
            .contentShape(.rect)
        }
        .buttonStyle(.plain)
        .accessibilityLabel(accessibilityText)
        .accessibilityAddTraits(isSelected ? .isSelected : [])
    }

    private var accessibilityText: String {
        var parts = [date.koreanDay()]
        if isToday { parts.append("오늘") }
        parts.append(count == 0 ? "일정 없음" : "일정 \(count)건")
        return parts.joined(separator: ", ")
    }
}

enum CalendarGrid {
    static let weekdays = ["월", "화", "수", "목", "금", "토", "일"]

    /// Monday-first week containing the date.
    static func week(of date: Date) -> [Date] {
        let calendar = Calendar.workshop
        let start = calendar.dateInterval(of: .weekOfYear, for: date)?.start ?? date
        return (0..<7).compactMap { calendar.date(byAdding: .day, value: $0, to: start) }
    }

    /// Month rows with `nil` for days outside the month.
    static func month(of date: Date) -> [[Date?]] {
        let calendar = Calendar.workshop
        guard let interval = calendar.dateInterval(of: .month, for: date),
              let days = calendar.range(of: .day, in: .month, for: date) else { return [] }
        let leading = (calendar.component(.weekday, from: interval.start) + 5) % 7
        var cells: [Date?] = Array(repeating: nil, count: leading)
        cells += days.compactMap { calendar.date(byAdding: .day, value: $0 - 1, to: interval.start) }
        cells += Array(repeating: nil, count: (7 - cells.count % 7) % 7)
        return stride(from: 0, to: cells.count, by: 7).map { Array(cells[$0..<$0 + 7]) }
    }
}

struct WeekStrip: View {
    @Binding var selectedDay: Date
    let days: [String: CalendarDay]
    let today: Date
    let move: (Int) -> Void
    @ScaledMetric(relativeTo: .body) private var diameter = 36

    var body: some View {
        HStack(spacing: 0) {
            ForEach(Array(CalendarGrid.week(of: selectedDay).enumerated()), id: \.element) { index, date in
                DayCell(
                    date: date, weekday: CalendarGrid.weekdays[index],
                    isSelected: Calendar.workshop.isDate(date, inSameDayAs: selectedDay),
                    isToday: Calendar.workshop.isDate(date, inSameDayAs: today),
                    count: days[date.dayKey]?.items.count ?? 0, diameter: diameter
                ) { selectedDay = date }
            }
        }
        .swipeToMove(move)
    }
}

struct MonthGrid: View {
    @Binding var selectedDay: Date
    let days: [String: CalendarDay]
    let today: Date
    let move: (Int) -> Void
    @ScaledMetric(relativeTo: .body) private var diameter = 34

    var body: some View {
        VStack(spacing: 4) {
            HStack(spacing: 0) {
                ForEach(CalendarGrid.weekdays, id: \.self) { weekday in
                    Text(weekday)
                        .font(.subheadline)
                        .foregroundStyle(CalendarTokens.secondary)
                        .frame(maxWidth: .infinity)
                }
            }
            .accessibilityHidden(true)
            ForEach(Array(CalendarGrid.month(of: selectedDay).enumerated()), id: \.offset) { _, row in
                HStack(spacing: 0) {
                    ForEach(Array(row.enumerated()), id: \.offset) { _, date in
                        if let date {
                            DayCell(
                                date: date, weekday: nil,
                                isSelected: Calendar.workshop.isDate(date, inSameDayAs: selectedDay),
                                isToday: Calendar.workshop.isDate(date, inSameDayAs: today),
                                count: days[date.dayKey]?.items.count ?? 0, diameter: diameter
                            ) { selectedDay = date }
                            .frame(minHeight: 52)
                        } else {
                            Color.clear.frame(maxWidth: .infinity, minHeight: 52)
                        }
                    }
                }
            }
        }
        .swipeToMove(move)
    }
}

private extension View {
    /// Horizontal swipes page the period; vertical scrolling keeps working.
    func swipeToMove(_ move: @escaping (Int) -> Void) -> some View {
        simultaneousGesture(
            DragGesture(minimumDistance: 24).onEnded { value in
                let width = value.translation.width
                guard abs(width) > 50, abs(width) > abs(value.translation.height) * 1.5 else { return }
                move(width < 0 ? 1 : -1)
            }
        )
    }
}
