import SwiftUI

struct CalendarScreen: View {
    enum Mode: String, CaseIterable, Identifiable {
        case week = "주간"
        case month = "월간"
        var id: Self { self }
    }

    @SceneStorage("calendar.mode") private var mode: Mode = .week
    @State private var selectedDay = Calendar.workshop.startOfDay(for: .now)
    @State private var loader = Loader<[String: CalendarDay]>()
    @State private var isAddingEvent = false
    @Environment(AppModel.self) private var app
    @Environment(\.dynamicTypeSize) private var dynamicTypeSize

    private let calendar = Calendar.workshop

    /// One request covers the visible month plus the weeks that overlap it.
    private var loadRange: (start: Date, end: Date) {
        let interval = calendar.dateInterval(of: .month, for: selectedDay)
        let first = interval?.start ?? selectedDay
        let last = calendar.date(byAdding: .day, value: -1, to: interval?.end ?? selectedDay) ?? selectedDay
        return (calendar.date(byAdding: .day, value: -7, to: first) ?? first,
                calendar.date(byAdding: .day, value: 7, to: last) ?? last)
    }

    private var loadKey: String { "\(loadRange.start.dayKey)|\(app.dataVersion)" }

    var body: some View {
        NavigationStack {
            LoadableContent(loader: loader, retry: load) { days in
                list(days)
            }
            .navigationTitle("캘린더")
            .navigationSubtitle(subtitle)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button("일정 추가", systemImage: "plus") {
                        isAddingEvent = true
                    }
                    .accessibilityIdentifier("calendar.add")
                }
            }
            .sheet(isPresented: $isAddingEvent) {
                EventFormSheet(day: selectedDay)
            }
            .appDestinations()
        }
        .task(id: loadKey) { await load() }
    }

    private func load() async {
        let range = loadRange
        await loader.load {
            let days = try await RoundupAPI.calendar(start: range.start, end: range.end).days
            return Dictionary(uniqueKeysWithValues: days.map { ($0.date, $0) })
        }
    }

    private func list(_ days: [String: CalendarDay]) -> some View {
        List {
            Section {
                Picker("보기", selection: $mode) {
                    ForEach(Mode.allCases) { Text($0.rawValue).tag($0) }
                }
                .adaptivePickerStyle()
                .accessibilityIdentifier("calendar.mode")
                .listRowInsets(EdgeInsets())
                .listRowBackground(Color.clear)
            }
            .listSectionSeparator(.hidden)

            CardSection {
                switch mode {
                case .week:
                    WeekStrip(selectedDay: $selectedDay, days: days)
                        .dynamicTypeSize(...DynamicTypeSize.xxxLarge)
                case .month:
                    MonthCalendarView(selectedDay: $selectedDay, days: days)
                        .frame(maxWidth: 380)
                        .frame(maxWidth: .infinity)
                }
            } header: {
                if mode == .week {
                    weekHeader
                }
            }

            CardSection {
                agenda(days[selectedDay.dayKey])
            } header: {
                HStack(alignment: .firstTextBaseline) {
                    SectionHeader(title: dayTitle(days[selectedDay.dayKey]))
                    if !calendar.isDateInToday(selectedDay) {
                        Spacer(minLength: 8)
                        Button("오늘로") {
                            selectedDay = calendar.startOfDay(for: .now)
                        }
                        .font(.subheadline)
                        .textCase(nil)
                        .frame(minHeight: 44)
                        .accessibilityIdentifier("calendar.today")
                    }
                }
            }
        }
        .cardList(separators: .hidden)
        .refreshable { await load() }
    }

    private var weekHeader: some View {
        let week = calendar.dateInterval(of: .weekOfYear, for: selectedDay)
        let start = week?.start ?? selectedDay
        let end = calendar.date(byAdding: .day, value: 6, to: start) ?? start
        return HStack {
            Button("이전 주", systemImage: "chevron.left") { moveWeek(-1) }
                .labelStyle(.iconOnly)
                .frame(minWidth: 44, minHeight: 44)
            Spacer()
            Text("\(start.koreanDay(weekday: false)) – \(end.koreanDay(weekday: false))")
            Spacer()
            Button("다음 주", systemImage: "chevron.right") { moveWeek(1) }
                .labelStyle(.iconOnly)
                .frame(minWidth: 44, minHeight: 44)
        }
        .textCase(nil)
    }

    private func moveWeek(_ weeks: Int) {
        selectedDay = calendar.date(byAdding: .weekOfYear, value: weeks, to: selectedDay) ?? selectedDay
    }

    @ViewBuilder
    private func agenda(_ day: CalendarDay?) -> some View {
        if let day {
            ForEach(day.items) { item in
                if let route = item.route {
                    NavigationLink(value: route) { AgendaRow(item: item) }
                } else {
                    AgendaRow(item: item)
                }
            }
        } else {
            ContentUnavailableView {
                Label("이 날은 일정이 없어요", systemImage: "calendar")
            } description: {
                Text(keepingWords: "필요하면 일정을 추가해\u{00A0}보세요.")
            } actions: {
                Button("일정 추가하기") {
                    isAddingEvent = true
                }
                .buttonStyle(.bordered)
                .controlSize(.large)
            }
        }
    }

    private var subtitle: String {
        guard let days = loader.value else { return "" }
        return "오늘 일정 \(days[Date.now.dayKey]?.items.count ?? 0)개"
    }

    private func dayTitle(_ day: CalendarDay?) -> String {
        let label = selectedDay.koreanDay()
        guard let count = day?.items.count, count > 0 else { return label }
        return dynamicTypeSize.isAccessibilitySize ? "\(label)\n일정 \(count)개" : "\(label) · 일정 \(count)개"
    }
}

struct WeekStrip: View {
    @Binding var selectedDay: Date
    let days: [String: CalendarDay]
    @ScaledMetric(relativeTo: .body) private var circleSize = 36

    private let calendar = Calendar.workshop
    private let weekdays = ["월", "화", "수", "목", "금", "토", "일"]

    private var weekDates: [Date] {
        let start = calendar.dateInterval(of: .weekOfYear, for: selectedDay)?.start ?? selectedDay
        return (0..<7).compactMap { calendar.date(byAdding: .day, value: $0, to: start) }
    }

    var body: some View {
        HStack(spacing: 0) {
            ForEach(Array(weekDates.enumerated()), id: \.element) { index, date in
                let isSelected = calendar.isDate(date, inSameDayAs: selectedDay)
                let events = days[date.dayKey]?.events ?? []
                Button {
                    selectedDay = date
                } label: {
                    VStack(spacing: 6) {
                        Text(weekdays[index])
                            .font(.subheadline)
                            .foregroundStyle(.secondary)
                        Text("\(calendar.component(.day, from: date))")
                            .font(.body.weight(isSelected ? .bold : .regular))
                            .monospacedDigit()
                            .foregroundStyle(isSelected ? Color(.systemBackground) : .primary)
                            .frame(width: circleSize, height: circleSize)
                            .background {
                                if isSelected {
                                    Circle().fill(.tint)
                                }
                            }
                        Circle()
                            .fill(events.isEmpty ? Color.clear : Color.secondary)
                            .frame(width: 6, height: 6)
                    }
                    .frame(maxWidth: .infinity, minHeight: 44)
                    .contentShape(.rect)
                }
                .buttonStyle(.plain)
                .accessibilityLabel(accessibilityLabel(date: date, events: events))
                .accessibilityAddTraits(isSelected ? .isSelected : [])
            }
        }
        .padding(.vertical, 6)
    }

    private func accessibilityLabel(date: Date, events: [DayEvent]) -> String {
        let summary = events.isEmpty ? "일정 없음" : events.map { "\($0.kind.label) \($0.display)" }.joined(separator: ", ")
        return "\(date.koreanDay()), \(summary)"
    }
}
