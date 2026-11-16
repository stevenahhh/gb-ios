import SwiftUI

struct CalendarScreen: View {
    enum Mode: String, CaseIterable, Identifiable {
        case week = "주간"
        case month = "월간"
        var id: Self { self }
    }

    @SceneStorage("calendar.mode") private var mode: Mode = .week
    @State private var selectedDay = SampleData.today.day ?? 4
    @State private var state = ScreenState.launch
    @Environment(\.dynamicTypeSize) private var dynamicTypeSize

    var body: some View {
        NavigationStack {
            content
                .navigationTitle("캘린더")
                .navigationSubtitle(subtitle)
                .toolbar {
                    ToolbarItem(placement: .topBarTrailing) {
                        Button("오늘") {
                            selectedDay = SampleData.today.day ?? 4
                        }
                    }
                    ToolbarSpacer(.fixed, placement: .topBarTrailing)
                    ToolbarItem(placement: .topBarTrailing) {
                        NavigationLink {
                            PlaceholderScreen(title: "일정 추가", systemImage: "calendar.badge.plus")
                        } label: {
                            Label("일정 추가", systemImage: "plus")
                        }
                    }
                }
                .navigationDestination(for: AreaRoute.self) { route in
                    OperationAreaView(area: route.area, initialFilter: route.filter)
                }
                .navigationDestination(for: WorkItem.self) { item in
                    WorkDetailView(item: item)
                }
        }
    }

    @ViewBuilder
    private var content: some View {
        switch state {
        case .error:
            LoadErrorView { state = .loaded }
        case .empty:
            ContentUnavailableView {
                Label("아직 일정이 없어요", systemImage: "calendar")
            } description: {
                Text(keepingWords: "예약과 할 일을 추가하면\n날짜별로 여기에 모여요.")
            } actions: {
                NavigationLink {
                    PlaceholderScreen(title: "일정 추가", systemImage: "calendar.badge.plus")
                } label: {
                    Text("일정 추가하기")
                        .foregroundStyle(Color(.systemBackground))
                }
                .buttonStyle(.borderedProminent)
                .controlSize(.large)
            }
        case .loading, .loaded:
            list
                .redacted(reason: state == .loading ? .placeholder : [])
                .allowsHitTesting(state != .loading)
        }
    }

    private var list: some View {
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

            Section {
                switch mode {
                case .week:
                    WeekStrip(selectedDay: $selectedDay, events: SampleData.novemberEvents)
                        .dynamicTypeSize(...DynamicTypeSize.xxxLarge)
                case .month:
                    MonthCalendarView(selectedDay: $selectedDay, events: SampleData.novemberEvents)
                        .frame(maxWidth: 380)
                        .frame(maxWidth: .infinity)
                }
            } header: {
                if mode == .week {
                    Text("11월 2일 – 8일")
                }
            } footer: {
                EventLegend()
            }

            Section {
                agenda
            } header: {
                SectionHeader(title: dayTitle)
            }
        }
        .listStyle(.insetGrouped)
    }

    @ViewBuilder
    private var agenda: some View {
        if let items = SampleData.agenda[selectedDay] {
            ForEach(items) { AgendaRow(item: $0) }
        } else if let events = SampleData.novemberEvents[selectedDay] {
            ForEach(events, id: \.self) { event in
                if let area = event.kind.area {
                    NavigationLink(value: AreaRoute(area: area)) {
                        summaryRow(event)
                    }
                } else {
                    summaryRow(event)
                }
            }
        } else {
            ContentUnavailableView {
                Label("이 날은 일정이 없어요", systemImage: "calendar")
            } description: {
                Text(keepingWords: "필요하면 일정을 추가해\u{00A0}보세요.")
            } actions: {
                NavigationLink("일정 추가하기") {
                    PlaceholderScreen(title: "일정 추가", systemImage: "calendar.badge.plus")
                }
                .buttonStyle(.bordered)
                .controlSize(.large)
            }
        }
    }

    private func summaryRow(_ event: DayEvent) -> some View {
        Label {
            Text("\(event.kind.rawValue) \(event.count)건")
                .font(.body.weight(.semibold))
        } icon: {
            Image(systemName: event.kind.symbol)
                .foregroundStyle(event.kind.color)
        }
        .accessibilityElement(children: .combine)
    }

    private var subtitle: String {
        state == .loaded || state == .loading
            ? "오늘 일정 \(SampleData.eventCount(on: SampleData.today.day ?? 4))개"
            : ""
    }

    private var dayTitle: String {
        var components = SampleData.today
        components.day = selectedDay
        guard let date = components.date else { return "" }
        let label = date.formatted(.dateTime.month().day().weekday(.wide).locale(Locale(identifier: "ko_KR")))
        let count = SampleData.eventCount(on: selectedDay)
        guard count > 0 else { return label }
        return dynamicTypeSize.isAccessibilitySize ? "\(label)\n일정 \(count)개" : "\(label) · 일정 \(count)개"
    }
}

struct WeekStrip: View {
    @Binding var selectedDay: Int
    let events: [Int: [DayEvent]]
    @ScaledMetric(relativeTo: .body) private var circleSize = 36
    @ScaledMetric(relativeTo: .caption2) private var symbolSize = 8

    private let days = Array(2...8)
    private let weekdays = ["월", "화", "수", "목", "금", "토", "일"]

    var body: some View {
        HStack(spacing: 0) {
            ForEach(days, id: \.self) { day in
                let isSelected = day == selectedDay
                let dayEvents = events[day] ?? []
                Button {
                    selectedDay = day
                } label: {
                    VStack(spacing: 6) {
                        Text(weekdays[day - days[0]])
                            .font(.subheadline)
                            .foregroundStyle(.secondary)
                        Text("\(day)")
                            .font(.body.weight(isSelected ? .bold : .regular))
                            .monospacedDigit()
                            .foregroundStyle(isSelected ? Color(.systemBackground) : .primary)
                            .frame(width: circleSize, height: circleSize)
                            .background {
                                if isSelected {
                                    Circle().fill(.tint)
                                }
                            }
                        HStack(spacing: 1) {
                            ForEach(dayEvents, id: \.self) { event in
                                Image(systemName: event.kind.symbol)
                                    .font(.system(size: symbolSize, weight: .semibold))
                                    .foregroundStyle(event.kind.color)
                            }
                        }
                        .frame(minHeight: symbolSize + 2)
                    }
                    .frame(maxWidth: .infinity, minHeight: 44)
                    .contentShape(.rect)
                }
                .buttonStyle(.plain)
                .accessibilityLabel(accessibilityLabel(day: day, events: dayEvents))
                .accessibilityAddTraits(isSelected ? .isSelected : [])
            }
        }
        .padding(.vertical, 6)
    }

    private func accessibilityLabel(day: Int, events: [DayEvent]) -> String {
        let weekday = weekdays[day - days[0]]
        let summary = events.isEmpty ? "일정 없음" : events.map { "\($0.kind.rawValue) \($0.count)건" }.joined(separator: ", ")
        return "11월 \(day)일 \(weekday)요일, \(summary)"
    }
}

struct EventLegend: View {
    var body: some View {
        ViewThatFits(in: .horizontal) {
            HStack(spacing: 14) { items }
            Grid(alignment: .leading, horizontalSpacing: 16, verticalSpacing: 6) {
                GridRow {
                    item(.booking)
                    item(.order)
                }
                GridRow {
                    item(.delivery)
                    item(.todo)
                }
            }
        }
        .font(.subheadline)
    }

    private var items: some View {
        ForEach(EventKind.allCases) { item($0) }
    }

    private func item(_ kind: EventKind) -> some View {
        Label {
            Text(kind.rawValue)
        } icon: {
            Image(systemName: kind.symbol)
                .foregroundStyle(kind.color)
        }
    }
}

#Preview {
    CalendarScreen()
}
