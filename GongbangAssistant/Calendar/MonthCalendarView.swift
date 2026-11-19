import SwiftUI
import UIKit

struct MonthCalendarView: UIViewRepresentable {
    @Binding var selectedDay: Date

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
        view.wantsDateDecorations = false

        let selection = UICalendarSelectionSingleDate(delegate: context.coordinator)
        selection.selectedDate = components(selectedDay)
        view.selectionBehavior = selection
        return view
    }

    func updateUIView(_ uiView: UICalendarView, context: Context) {
        context.coordinator.parent = self
        let target = components(selectedDay)
        if let selection = uiView.selectionBehavior as? UICalendarSelectionSingleDate,
           selection.selectedDate?.date != target.date {
            selection.setSelected(target, animated: !context.environment.accessibilityReduceMotion)
            uiView.setVisibleDateComponents(target, animated: !context.environment.accessibilityReduceMotion)
        }
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
