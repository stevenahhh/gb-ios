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
        }
        .accessibilityIdentifier("today.empty")
        .refreshable { await load() }
    }

    private func list(_ today: TodayScreenData) -> some View {
        List {
            CardSection {
                MetricStrip(metrics: metrics(today))
            }

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
            CardSection {
                if !store.hasLoadedInquiries {
                    Text("서버 문의를 불러오면 대기 목록이 보여요.")
                        .foregroundStyle(.secondary)
                } else if store.pendingInquiries.isEmpty {
                    Label("답변을 기다리는 문의가 없어요", systemImage: "checkmark.circle")
                        .foregroundStyle(.secondary)
                } else {
                    ForEach(store.pendingInquiries) { AssistantDraftRow(inquiry: $0) }
                }
            } header: {
                SectionHeader(title: "답변 대기 문의 \(store.pendingCount)건", area: .channels, filter: "inquiries")
            }
            ForEach(today.tasks.groups) { group in
                CardSection {
                    ForEach(group.items.overdueFirst()) { item in
                        TaskRow(item: item, kind: group.kind)
                    }
                } header: {
                    SectionHeader(title: group.title, area: group.area)
                }
            }
        case .channels:
            CardSection {
                ForEach(today.channels.cards) { WorkCard(item: $0) }
            } header: {
                SectionHeader(title: "채널 현황", area: .channels)
            }
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
                            .foregroundStyle(.secondary)
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
                .foregroundStyle(.secondary)
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
