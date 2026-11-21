import Combine
import SwiftUI
import RoundupCore

enum TodaySegment: String, CaseIterable, Identifiable {
    case tasks = "할 일"
    case channels = "채널"
    case delivery = "배송"
    case suggestions = "비서 추천"

    var id: Self { self }
}

struct TodayView: View {
    @SceneStorage("today.segment") private var segment: TodaySegment = .tasks
    @State private var loader = Loader<TodayScreenData>()
    @State private var now = Date.now
    @Environment(InquiryStore.self) private var store
    @Environment(AppModel.self) private var app

    var body: some View {
        NavigationStack {
            LoadableContent(loader: loader, retry: load) { today in
                if today.hasNoWork && store.inquiries.isEmpty {
                    emptyState
                } else {
                    list(today)
                }
            }
            // The headline is recomputed every minute and whenever the data reloads. A TimelineView
            // around the list looped with the collapsing large title, so a minute timer drives `now`.
            .navigationTitle(headline(now: now))
            .onReceive(Timer.publish(every: 60, on: .main, in: .common).autoconnect()) { now = $0 }
            .navigationSubtitle(subtitle)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    NavigationLink {
                        AssistantActivityView()
                    } label: {
                        Image(systemName: "clock.arrow.circlepath")
                    }
                    .accessibilityLabel("\(AssistantIdentity.name)가 한 일")
                    .accessibilityIdentifier("today.activities")
                }
            }
            .appDestinations()
        }
        .task(id: app.dataVersion) { await load() }
    }

    private func load() async {
        await loader.load { try await RoundupAPI.today() }
        if let count = loader.value?.attentionCount { app.updateAttention(count) }
    }

    private var emptyState: some View {
        ContentUnavailableView {
            Label("오늘 등록된 일이 없어요", systemImage: "checkmark.circle")
        } description: {
            Text(keepingWords: "예약과 주문이 생기면\n오늘 할 일이 여기에 모여요.")
                .foregroundStyle(Color.secondaryText)
        }
        .accessibilityIdentifier("today.empty")
        .refreshable { await load() }
    }

    private func list(_ today: TodayScreenData) -> some View {
        List {
            CardSection {
                MetricStrip(metrics: metrics(today))
            }

            ApprovalSection(items: ApprovalItem.collect(inquiries: store.inquiries, today: today))

            Section {
                Picker("보기", selection: $segment) {
                    ForEach(TodaySegment.allCases) { segment in
                        Text(segment.rawValue).tag(segment)
                    }
                }
                .adaptivePickerStyle()
                .accessibilityIdentifier("today.segment")
                .listRowInsets(EdgeInsets())
                .listRowBackground(Color.clear)
            }
            .listSectionSeparator(.hidden)

            segmentContent(today)
        }
        .cardList()
        .refreshable {
            await load()
            await store.loadInquiries()
        }
    }

    private func metrics(_ today: TodayScreenData) -> [Metric] {
        switch segment {
        case .tasks: today.tasks.metrics
        case .channels: today.channels.metrics
        case .delivery: today.delivery.metrics
        case .suggestions: today.suggestions.metrics
        }
    }

    @ViewBuilder
    private func segmentContent(_ today: TodayScreenData) -> some View {
        switch segment {
        case .tasks:
            // Overdue rows move into one group at the top with a single red title; their own sections drop them.
            let overdue = OverdueEntry.collect(today.tasks.groups, now: .now)
            if !overdue.isEmpty {
                CardSection {
                    ForEach(overdue.prefix(3)) { entry in
                        TaskRow(item: entry.item, kind: entry.kind, isInOverdueGroup: true)
                    }
                    if overdue.count > 3 {
                        NavigationLink("모두 보기") { OverdueListView() }
                            .accessibilityIdentifier("today.overdue.all")
                    }
                } header: {
                    OverdueHeader(count: overdue.count)
                }
            }
            // Waiting inquiry replies live in 확인해 주실 일 above, so this tab does not repeat them.
            // Bookings keep the timeline rail: one node per class, joined by a line, with no separators.
            ForEach(today.tasks.groups) { group in
                let rows = group.items.filter { item in !overdue.contains { $0.item.id == item.id } }
                if !rows.isEmpty {
                    CardSection {
                        ForEach(Array(rows.enumerated()), id: \.element.id) { index, item in
                            TaskRow(item: item, kind: group.kind,
                                    timeline: group.kind == .booking
                                        ? TimelinePosition(index: index, count: rows.count) : nil)
                        }
                    } header: {
                        SectionHeader(title: group.title, area: group.area)
                    }
                    .environment(\.cardSeparators, group.kind == .booking ? .hidden : .automatic)
                }
            }
        case .channels:
            CardSection {
                if today.channels.cards.allChannelsUnconnected {
                    UnconnectedChannelsNote()
                }
                ForEach(today.channels.cards) { WorkCard(item: $0) }
            } header: {
                SectionHeader(title: "채널 현황", area: .channels)
            }
            .environment(\.hidesCardStatus, today.channels.cards.allChannelsUnconnected)
            CardSection {
                cards(today.channels.todos, empty: "오늘 챙길 채널 일이 없어요")
            } header: {
                SectionHeader(title: "오늘 챙길 일 \(today.channels.todos.count)건")
            }
        case .delivery:
            CardSection {
                cards(today.delivery.shipToday, empty: "오늘 발송할 물건이 없어요")
            } header: {
                SectionHeader(title: "오늘 발송할 물건 \(today.delivery.shipToday.count)건", area: .deliveries)
            }
            CardSection {
                NavigationLink(value: AreaRoute(area: .deliveries, filter: "in_transit")) {
                    VStack(alignment: .leading, spacing: 4) {
                        PhraseText(text: today.delivery.transitSummary)
                            .font(.headline)
                        Text(keepingWords: today.delivery.transitDetail)
                            .font(.subheadline)
                            .foregroundStyle(Color.secondaryText)
                    }
                    .padding(.vertical, 4)
                }
                ForEach(today.delivery.inTransit) { WorkCard(item: $0) }
            } header: {
                SectionHeader(title: "이동 중인 배송")
            }
        case .suggestions:
            CardSection {
                cards(today.suggestions.items, empty: "지금은 새로운 추천이 없어요")
            } header: {
                SectionHeader(title: "오늘의 추천")
            } footer: {
                Text("비서가 공방의 예약과 초안을 보고 골랐어요. 틀릴 수 있으니 내용을 확인해 주세요.")
            }
        }
    }

    @ViewBuilder
    private func cards(_ items: [WorkItem], empty: String) -> some View {
        if items.isEmpty {
            Text(empty)
                .foregroundStyle(Color.secondaryText)
        } else {
            let primaryID = items.primaryActionID
            ForEach(items.overdueFirst()) { item in
                WorkCard(item: item, isPrimary: item.id == primaryID)
            }
        }
    }

    private func headline(now: Date) -> String {
        guard let facts = loader.value?.headline else { return "오늘" }
        var core = TodayHeadlineFacts()
        core.overdueShipments = facts.overdueShipments
        core.overdueTasks = facts.overdueTasks
        core.sessions = facts.sessions.compactMap { session in
            (try? Date(session.startsAt, strategy: .iso8601)).map {
                TodayHeadlineFacts.Session(title: session.title, start: $0, minutes: session.minutes,
                                           isDone: session.isDone)
            }
        }
        core.pendingInquiries = facts.pendingInquiries
        core.depositPending = facts.depositPending
        core.pendingDrafts = facts.pendingDrafts
        core.openTasksToday = facts.openTasksToday
        core.tasksToday = facts.tasksToday
        core.openShipmentsToday = facts.openShipmentsToday
        core.shipmentsToday = facts.shipmentsToday
        core.tomorrowClasses = facts.tomorrowClasses
        core.weekClassesLeft = facts.weekClassesLeft
        return TodayHeadline.make(core, now: now)
    }

    private var subtitle: String {
        let date = Date.now.koreanDay()
        guard let loadedAt = loader.loadedAt else { return date }
        let style = Date.FormatStyle(date: .omitted, time: .shortened, locale: Locale(identifier: "ko_KR"),
                                     timeZone: Calendar.workshop.timeZone)
        return "\(date) · \(loadedAt.formatted(style)) 기준"
    }
}

struct OverdueEntry: Identifiable {
    let kind: EventKind
    let item: TaskItem
    var id: String { item.id }

    static func collect(_ groups: [TaskGroup], now: Date) -> [OverdueEntry] {
        groups.flatMap { group in
            group.items.filter { $0.isDone != true && $0.due?.isOverdue(at: now) == true }
                .map { OverdueEntry(kind: group.kind, item: $0) }
        }
        .sorted { ($0.item.due?.date ?? .distantPast) < ($1.item.due?.date ?? .distantPast) }
    }
}

struct OverdueHeader: View {
    let count: Int

    var body: some View {
        HStack(spacing: 6) {
            Image(systemName: "clock")
                .accessibilityHidden(true)
            Text("기한 지난 일 \(count)건")
                .fontWeight(.semibold)
        }
        .foregroundStyle(Color.overdueRed)
        .textCase(nil)
        .accessibilityAddTraits(.isHeader)
        .accessibilityIdentifier("today.overdue")
    }
}

/// Loads its own copy of the today screen, so checks made here show up without leaving the list.
/// Rows it has shown stay put once finished (the server drops a finished task's deadline), so a check can be undone in place.
struct OverdueListView: View {
    @State private var loader = Loader<TodayScreenData>()
    @State private var shownIDs: [String] = []
    @Environment(AppModel.self) private var app

    var body: some View {
        LoadableContent(loader: loader, retry: load) { today in
            let rows = Dictionary(today.tasks.groups.flatMap { group in
                group.items.map { ($0.id, OverdueEntry(kind: group.kind, item: $0)) }
            }, uniquingKeysWith: { first, _ in first })
            let entries = shownIDs.compactMap { rows[$0] }
            List {
                CardSection {
                    ForEach(entries) { TaskRow(item: $0.item, kind: $0.kind, isInOverdueGroup: true) }
                } header: {
                    OverdueHeader(count: entries.filter { $0.item.isDone != true }.count)
                }
            }
            .cardList()
        }
        .navigationTitle("기한 지난 일")
        .navigationBarTitleDisplayMode(.inline)
        .task(id: app.dataVersion) { await load() }
    }

    private func load() async {
        await loader.load { try await RoundupAPI.today() }
        guard let groups = loader.value?.tasks.groups else { return }
        let added = OverdueEntry.collect(groups, now: .now).map(\.id).filter { !shownIDs.contains($0) }
        shownIDs.append(contentsOf: added)
    }
}
