import SwiftUI
import UIKit

struct MonthCalendarView: UIViewRepresentable {
    @Binding var selectedDay: Int
    let events: [Int: [EventKind]]

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
            animated: true
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
                  let day = dateComponents.day, let kinds = parent.events[day] else { return nil }
            if kinds.count == 1 {
                return .default(color: kinds[0].uiColor, size: .small)
            }
            let dot: CGFloat = 5
            let gap: CGFloat = 2
            let size = CGSize(width: CGFloat(kinds.count) * (dot + gap) - gap, height: dot)
            let image = UIGraphicsImageRenderer(size: size).image { _ in
                for (index, kind) in kinds.enumerated() {
                    kind.uiColor.setFill()
                    UIBezierPath(ovalIn: CGRect(x: CGFloat(index) * (dot + gap), y: 0, width: dot, height: dot)).fill()
                }
            }
            return .customView { UIImageView(image: image) }
        }

        func dateSelection(_ selection: UICalendarSelectionSingleDate, didSelectDate dateComponents: DateComponents?) {
            if let day = dateComponents?.day {
                parent.selectedDay = day
            }
        }
    }
}
