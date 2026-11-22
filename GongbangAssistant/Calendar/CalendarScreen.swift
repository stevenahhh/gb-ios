import Combine
import SwiftUI

struct CalendarData {
    let days: [String: CalendarDay]
    let overdueShipments: [AgendaItem]
    /// Day keys the last load covered. A day outside it is still loading, not empty.
    let loaded: ClosedRange<String>
}

struct CalendarScreen: View {
    @SceneStorage("calendar.mode") private var mode: CalendarMode = .week
    @State private var selectedDay = Calendar.workshop.startOfDay(for: Self.clockOverride ?? .now)
    @State private var loader = Loader<CalendarData>()
    @State private var isAddingEvent = false
    @State private var now = Date.now
    @Environment(AppModel.self) private var app

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

    private var subtitle: String {
        guard let data = loader.value else { return "" }
        return "오늘 일정 \(data.days[(Self.clockOverride ?? .now).dayKey]?.items.count ?? 0)건"
    }

    var body: some View {
        NavigationStack {
            LoadableContent(loader: loader, retry: load) { data in
                CalendarContent(
                    days: data.days, overdueShipments: data.overdueShipments,
                    selectedDay: $selectedDay, mode: $mode, now: Self.clockOverride ?? now,
                    add: { isAddingEvent = true }, check: check,
                    isDayLoaded: data.loaded.contains(selectedDay.dayKey)
                )
                .refreshable { await load() }
            }
            // A minute timer, not a TimelineView around the scroll view, so the collapsing title cannot loop.
            .onReceive(Timer.publish(every: 60, on: .main, in: .common).autoconnect()) { now = $0 }
            .background(CalendarTokens.background)
            .navigationTitle("캘린더")
            .navigationBarTitleDisplayMode(.large)
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

    #if DEBUG
    /// Debug builds can pin the clock (`ROUNDUP_CALENDAR_NOW`, ISO 8601) to check the next row and time line.
    private static let clockOverride = ProcessInfo.processInfo.environment["ROUNDUP_CALENDAR_NOW"]
        .flatMap { try? Date($0, strategy: .iso8601) }
    #else
    private static let clockOverride: Date? = nil
    #endif

    private func load() async {
        let range = loadRange
        await loader.load {
            let response = try await RoundupAPI.calendar(start: range.start, end: range.end)
            return CalendarData(days: Dictionary(uniqueKeysWithValues: response.days.map { ($0.date, $0) }),
                                overdueShipments: response.overdueShipments ?? [],
                                loaded: range.start.dayKey...range.end.dayKey)
        }
    }

    /// Checking or unchecking shows an undo toast, because a quick tap on a busy screen is easy to get wrong.
    private func check(_ entry: TimelineEntry, done: Bool) async -> Bool {
        guard let item = entry.ownerItem else { return false }
        var revision: Int?
        let saved = await app.run(id: entry.id) {
            revision = try await RoundupAPI.setDone(item, done: done)
        }
        guard saved, let revision else { return saved }
        app.showToast("‘\(entry.title)’ \(done ? "완료했어요" : "완료를 취소했어요")") { [app] in
            await app.run(id: entry.id) {
                _ = try await RoundupAPI.setDone(item.with(revision: revision), done: !done)
            }
        }
        return true
    }
}

/// The calendar on one white sheet; it takes `now` so previews and the minute timer share one path.
struct CalendarContent: View {
    let days: [String: CalendarDay]
    let overdueShipments: [AgendaItem]
    @Binding var selectedDay: Date
    @Binding var mode: CalendarMode
    let now: Date
    let add: () -> Void
    let check: (TimelineEntry, Bool) async -> Bool
    var isDayLoaded = true
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    private var calendar: Calendar { .workshop }
    private var animation: Animation { reduceMotion ? .easeInOut(duration: 0.2) : .spring(duration: 0.25) }

    var body: some View {
        let items = days[selectedDay.dayKey]?.items ?? []
        let schedule = DaySchedule(items: items)
        ScrollView {
            VStack(alignment: .leading, spacing: 0) {
                // Seven fixed columns cannot grow with accessibility sizes, so the date controls stop at xxxLarge.
                ModeSegment(mode: $mode)
                    .dynamicTypeSize(...DynamicTypeSize.xxxLarge)
                PeriodNavigator(
                    title: periodTitle, isShowingToday: calendar.isDate(selectedDay, inSameDayAs: now),
                    today: { withAnimation(animation) { selectedDay = calendar.startOfDay(for: now) } },
                    move: move
                )
                .dynamicTypeSize(...DynamicTypeSize.xxxLarge)
                .padding(.top, 14)
                Group {
                    switch mode {
                    case .week: WeekStrip(selectedDay: $selectedDay, days: days, today: now, move: move)
                    case .month: MonthGrid(selectedDay: $selectedDay, days: days, today: now, move: move)
                    }
                }
                .dynamicTypeSize(...DynamicTypeSize.xxxLarge)
                .padding(.top, 8)
                Rectangle()
                    .fill(CalendarTokens.separator)
                    .frame(height: 1)
                    .padding(.top, 12)
                DaySection(date: selectedDay, itemCount: items.count, schedule: schedule,
                           overdueShipments: overdueShipments, now: now, add: add, check: check,
                           isLoading: !isDayLoaded)
                    .padding(.top, 24)
                    .id(selectedDay.dayKey)
                    .transition(.opacity)
            }
            .padding(.horizontal, 20)
            .padding(.top, 8)
        }
        .contentMargins(.bottom, 32, for: .scrollContent)
        .background(CalendarTokens.background)
        // A day with a timeline keeps 일정 추가 in reach without scrolling. A day without one already shows the
        // same button under its message.
        .safeAreaInset(edge: .bottom, spacing: 0) {
            if isDayLoaded && !schedule.entries.isEmpty {
                DayAddBar(add: add)
                    .transition(.opacity)
            }
        }
        .animation(animation, value: selectedDay)
        .animation(animation, value: mode)
    }

    private var periodTitle: String {
        switch mode {
        case .month:
            let parts = calendar.dateComponents([.year, .month], from: selectedDay)
            return "\(parts.year ?? 0)년 \(parts.month ?? 0)월"
        case .week:
            let week = CalendarGrid.week(of: selectedDay)
            guard let first = week.first, let last = week.last else { return "" }
            let start = calendar.dateComponents([.month, .day], from: first)
            let end = calendar.dateComponents([.month, .day], from: last)
            let endText = start.month == end.month ? "\(end.day ?? 0)일" : "\(end.month ?? 0)월 \(end.day ?? 0)일"
            return "\(start.month ?? 0)월 \(start.day ?? 0)일 – \(endText)"
        }
    }

    private func move(_ step: Int) {
        let component: Calendar.Component = mode == .week ? .weekOfYear : .month
        withAnimation(animation) {
            selectedDay = calendar.date(byAdding: component, value: step, to: selectedDay) ?? selectedDay
        }
    }
}
