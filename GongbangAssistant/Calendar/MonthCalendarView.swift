import SwiftUI
import UIKit

struct MonthCalendarView: UIViewRepresentable {
    @Binding var selectedDay: Date
    let days: [String: CalendarDay]

    func makeCoordinator() -> Coordinator {
        Coordinator(parent: self)
    }

    private func components(_ date: Date) -> DateComponents {
        Calendar.workshop.dateComponents([.calendar, .era, .year, .month, .day], from: date)
    }

    func makeUIView(context: Context) -> UICalendarView {
        let view = UICalendarView()
        view.calendar = Calendar.workshop
        view.locale = Locale(identifier: "ko_KR")
        view.timeZone = Calendar.workshop.timeZone
        view.visibleDateComponents = components(selectedDay)
        view.delegate = context.coordinator
        view.wantsDateDecorations = true

        let selection = UICalendarSelectionSingleDate(delegate: context.coordinator)
        selection.selectedDate = components(selectedDay)
        view.selectionBehavior = selection
        return view
    }

    func updateUIView(_ uiView: UICalendarView, context: Context) {
        let daysChanged = context.coordinator.parent.days != days
        context.coordinator.parent = self
        let target = components(selectedDay)
        if let selection = uiView.selectionBehavior as? UICalendarSelectionSingleDate,
           selection.selectedDate?.date != target.date {
            selection.setSelected(target, animated: !context.environment.accessibilityReduceMotion)
            uiView.setVisibleDateComponents(target, animated: !context.environment.accessibilityReduceMotion)
        }
        if daysChanged {
            let loaded = days.keys.compactMap(Self.components(fromKey:))
            uiView.reloadDecorations(forDateComponents: loaded, animated: false)
        }
    }

    private static func components(fromKey key: String) -> DateComponents? {
        let parts = key.split(separator: "-").compactMap { Int($0) }
        guard parts.count == 3 else { return nil }
        return DateComponents(calendar: Calendar.workshop, year: parts[0], month: parts[1], day: parts[2])
    }

    func sizeThatFits(_ proposal: ProposedViewSize, uiView: UICalendarView, context: Context) -> CGSize? {
        let width = proposal.width ?? 360
        let fitted = uiView.systemLayoutSizeFitting(
            CGSize(width: width, height: UIView.layoutFittingCompressedSize.height),
            withHorizontalFittingPriority: .required,
            verticalFittingPriority: .fittingSizeLevel
        )
        return CGSize(width: width, height: fitted.height)
    }

    final class Coordinator: NSObject, UICalendarViewDelegate, UICalendarSelectionSingleDateDelegate {
        var parent: MonthCalendarView

        init(parent: MonthCalendarView) {
            self.parent = parent
        }

        func calendarView(_ calendarView: UICalendarView, decorationFor dateComponents: DateComponents) -> UICalendarView.Decoration? {
            guard let date = dateComponents.date, let dayEvents = parent.days[date.dayKey]?.events else { return nil }
            let kinds = dayEvents.map(\.kind)
            if kinds.count == 1 {
                return .image(UIImage(systemName: kinds[0].symbol), color: kinds[0].uiColor, size: .small)
            }
            let pointSize = min(UIFontMetrics(forTextStyle: .caption2).scaledValue(for: 7), 10)
            let configuration = UIImage.SymbolConfiguration(pointSize: pointSize, weight: .semibold)
            let symbols = kinds.compactMap { kind in
                UIImage(systemName: kind.symbol, withConfiguration: configuration)?
                    .withTintColor(kind.uiColor, renderingMode: .alwaysOriginal)
            }
            let gap: CGFloat = 2
            let width = symbols.reduce(0) { $0 + $1.size.width } + gap * CGFloat(max(symbols.count - 1, 0))
            let height = symbols.map(\.size.height).max() ?? 0
            let image = UIGraphicsImageRenderer(size: CGSize(width: width, height: height)).image { _ in
                var x: CGFloat = 0
                for symbol in symbols {
                    symbol.draw(at: CGPoint(x: x, y: (height - symbol.size.height) / 2))
                    x += symbol.size.width + gap
                }
            }
            let label = dayEvents.map { "\($0.kind.label) \($0.display)" }.joined(separator: ", ")
            return .customView {
                let view = UIImageView(image: image)
                view.isAccessibilityElement = true
                view.accessibilityLabel = label
                return view
            }
        }

        func dateSelection(_ selection: UICalendarSelectionSingleDate, didSelectDate dateComponents: DateComponents?) {
            if let date = dateComponents?.date {
                parent.selectedDay = Calendar.workshop.startOfDay(for: date)
            }
        }

        func calendarView(_ calendarView: UICalendarView, didChangeVisibleDateComponentsFrom previous: DateComponents) {
            // Paging months moves the selection so the screen loads that month's rows.
            guard let visible = calendarView.visibleDateComponents.date else { return }
            let calendar = Calendar.workshop
            if !calendar.isDate(visible, equalTo: parent.selectedDay, toGranularity: .month),
               let first = calendar.dateInterval(of: .month, for: visible)?.start {
                parent.selectedDay = first
            }
        }
    }
}
