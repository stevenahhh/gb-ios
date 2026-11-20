import SwiftUI
import UIKit

struct OperationPeriod: Equatable {
    static let maximumDays = 366
    private static let calendar = Calendar.workshop

    var start: Date
    var end: Date

    static var currentMonth: OperationPeriod {
        let interval = calendar.dateInterval(of: .month, for: .now)
        let first = interval?.start ?? .now
        let last = calendar.date(byAdding: .day, value: -1, to: interval?.end ?? .now) ?? .now
        return OperationPeriod(start: first, end: last)
    }

    private var monthKey: String? {
        guard let interval = Self.calendar.dateInterval(of: .month, for: start),
              Self.calendar.isDate(start, inSameDayAs: interval.start),
              let last = Self.calendar.date(byAdding: .day, value: -1, to: interval.end),
              Self.calendar.isDate(end, inSameDayAs: last) else { return nil }
        return String(start.dayKey.prefix(7))
    }

    var query: [String: String] {
        monthKey.map { ["month": $0] } ?? ["start": start.dayKey, "end": end.dayKey]
    }

    var dayCount: Int {
        (Self.calendar.dateComponents([.day], from: start, to: end).day ?? 0) + 1
    }

    var rangeText: String {
        "\(Self.shortText(start)) – \(Self.shortText(end))"
    }

    private static func shortText(_ date: Date) -> String {
        let parts = calendar.dateComponents([.month, .day], from: date)
        return String(format: "%02d.%02d", parts.month ?? 0, parts.day ?? 0)
    }
}

struct PeriodPickerSheet: View {
    let period: OperationPeriod
    let apply: (OperationPeriod) -> Void
    @Environment(\.dismiss) private var dismiss
    @State private var start: Date?
    @State private var end: Date?

    private var selection: OperationPeriod? {
        guard let start, let end else { return nil }
        let period = OperationPeriod(start: start, end: end)
        return period.dayCount <= OperationPeriod.maximumDays ? period : nil
    }

    private var summary: String {
        if let selection { return selection.rangeText }
        return end == nil ? "끝나는 날짜를 골라 주세요" : "1년 안의 기간을 골라 주세요"
    }

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 12) {
                    Text(keepingWords: summary)
                        .font(.headline)
                        .monospacedDigit()
                        .accessibilityIdentifier("period.summary")
                    RangeCalendarView(start: $start, end: $end)
                }
                .padding()
            }
            .navigationTitle("기간 선택")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("취소") { dismiss() }
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button("적용") {
                        if let selection { apply(selection) }
                        dismiss()
                    }
                    .disabled(selection == nil)
                    .accessibilityIdentifier("period.apply")
                }
            }
        }
        .presentationDetents([.large])
        .onAppear {
            start = period.start
            end = period.end
        }
    }
}

private struct RangeCalendarView: UIViewRepresentable {
    @Binding var start: Date?
    @Binding var end: Date?

    func makeCoordinator() -> Coordinator {
        Coordinator(parent: self)
    }

    func makeUIView(context: Context) -> UICalendarView {
        let view = UICalendarView()
        let calendar = Calendar.workshop
        view.calendar = calendar
        view.locale = calendar.locale ?? Locale(identifier: "ko_KR")
        view.timeZone = calendar.timeZone
        view.visibleDateComponents = calendar.dateComponents([.year, .month], from: start ?? .now)
        let selection = UICalendarSelectionMultiDate(delegate: context.coordinator)
        view.selectionBehavior = selection
        context.coordinator.select(in: selection, animated: false)
        return view
    }

    func updateUIView(_ uiView: UICalendarView, context: Context) {
        context.coordinator.parent = self
        if let selection = uiView.selectionBehavior as? UICalendarSelectionMultiDate {
            context.coordinator.select(in: selection, animated: false)
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

    @MainActor
    final class Coordinator: NSObject, UICalendarSelectionMultiDateDelegate {
        var parent: RangeCalendarView
        private let calendar = Calendar.workshop

        init(parent: RangeCalendarView) {
            self.parent = parent
        }

        func multiDateSelection(_ selection: UICalendarSelectionMultiDate, didSelectDate dateComponents: DateComponents) {
            tap(dateComponents, in: selection)
        }

        func multiDateSelection(_ selection: UICalendarSelectionMultiDate, didDeselectDate dateComponents: DateComponents) {
            tap(dateComponents, in: selection)
        }

        private func tap(_ components: DateComponents, in selection: UICalendarSelectionMultiDate) {
            guard let date = calendar.date(from: components) else { return }
            if let start = parent.start, parent.end == nil, date >= start {
                parent.end = date
            } else {
                parent.start = date
                parent.end = nil
            }
            select(in: selection, animated: true)
        }

        func select(in selection: UICalendarSelectionMultiDate, animated: Bool) {
            guard let start = parent.start else { return }
            var dates: [DateComponents] = []
            var day = start
            let last = parent.end ?? start
            while day <= last {
                dates.append(calendar.dateComponents([.calendar, .era, .year, .month, .day], from: day))
                guard let next = calendar.date(byAdding: .day, value: 1, to: day) else { break }
                day = next
            }
            if selection.selectedDates != dates {
                selection.setSelectedDates(dates, animated: animated)
            }
        }
    }
}
