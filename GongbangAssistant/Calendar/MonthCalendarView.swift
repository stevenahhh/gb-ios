import SwiftUI
import UIKit

struct MonthCalendarView: UIViewRepresentable {
    @Binding var selectedDay: Int
    let events: [Int: [DayEvent]]

    func makeCoordinator() -> Coordinator {
        Coordinator(parent: self)
    }

    func makeUIView(context: Context) -> UICalendarView {
        let view = UICalendarView()
        let locale = Locale(identifier: "ko_KR")
        var calendar = Calendar(identifier: .gregorian)
        calendar.locale = locale
        view.calendar = calendar
        view.locale = locale
        view.visibleDateComponents = DateComponents(calendar: calendar, year: 2026, month: 11, day: 1)
        view.delegate = context.coordinator
        view.wantsDateDecorations = true

        let selection = UICalendarSelectionSingleDate(delegate: context.coordinator)
        selection.selectedDate = DateComponents(calendar: calendar, year: 2026, month: 11, day: selectedDay)
        view.selectionBehavior = selection
        return view
    }

    func updateUIView(_ uiView: UICalendarView, context: Context) {
        context.coordinator.parent = self
        guard let selection = uiView.selectionBehavior as? UICalendarSelectionSingleDate,
              selection.selectedDate?.day != selectedDay else { return }
        selection.setSelected(
            DateComponents(calendar: uiView.calendar, year: 2026, month: 11, day: selectedDay),
            animated: !context.environment.accessibilityReduceMotion
        )
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
            guard dateComponents.year == 2026, dateComponents.month == 11,
                  let day = dateComponents.day, let dayEvents = parent.events[day] else { return nil }
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
            let label = dayEvents.map { "\($0.kind.rawValue) \($0.count)건" }.joined(separator: ", ")
            return .customView {
                let view = UIImageView(image: image)
                view.isAccessibilityElement = true
                view.accessibilityLabel = label
                return view
            }
        }

        func dateSelection(_ selection: UICalendarSelectionSingleDate, didSelectDate dateComponents: DateComponents?) {
            if let day = dateComponents?.day {
                parent.selectedDay = day
            }
        }
    }
}
