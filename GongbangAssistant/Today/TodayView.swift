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
    @State private var visibility = AttentionVisibility.shared
    @Environment(InquiryStore.self) private var store
    @Environment(AppModel.self) private var app
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        NavigationStack {
            LoadableContent(loader: loader, retry: load) { today in
                list(today)
                    .todayGreeting(
                        pendingCount: AttentionCount.value(today: today, inquiries: store.inquiries),
                        updated: subtitle, now: now
                    )
            }
            // Until the first load there is no count to greet with, and "0건" would be a guess.
            .background {
                if loader.value == nil { Color.clear.navigationTitle("오늘") }
            }
            // The greeting is recomputed every minute and whenever the data reloads. A TimelineView
            // around the list looped with the collapsing large title, so a minute timer drives `now`.
            .onReceive(Timer.publish(every: 60, on: .main, in: .common).autoconnect()) { now = $0 }
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    Image(.brandMark)
                        .resizable()
                        .scaledToFit()
                        .frame(width: 28, height: 28)
                        .accessibilityLabel("공도리")
                        .accessibilityIdentifier("today.brand")
                }
                .sharedBackgroundVisibility(.hidden)
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
        .bk06NotificationSheet()
        .task(id: app.dataVersion) { await load() }
    }

    private func load() async {
        // The greeting counts K06 rows, so they load here rather than when a lazy row appears.
        async let k06: Void = BK06Inbox.shared.load()
        await loader.load { try await RoundupAPI.today() }
        now = .now
        if let count = loader.value?.attentionCount { app.updateAttention(count) }
        await BK25JudgmentInbox.shared.load()
        await k06
    }

    private func list(_ today: TodayScreenData) -> some View {
        let isEmpty = today.hasNoWork && store.inquiries.isEmpty
        return List {
            if isEmpty {
                emptyState
            } else {
                metricSection(today)
            }

            AttentionSection(today: today)
            BK25JudgmentSection()

            if !isEmpty {
                segmentContent(today)
            }
        }
        .cardList()
        // Rows pass under the pinned segments; the hard edge keeps their text from reading through.
        .scrollEdgeEffectStyle(.hard, for: .top)
        .safeAreaBar(edge: .top, spacing: 0) {
            if !isEmpty {
                TodaySegmentBar(selection: $segment)
                    .padding(.horizontal, 16)
                    .padding(.bottom, 4)
            }
        }
        .refreshable {
            await load()
            await store.loadInquiries()
        }
    }

    private var emptyState: some View {
        Section {
            ContentUnavailableView {
                Label("오늘 등록된 일이 없어요", systemImage: "checkmark.circle")
            } description: {
                Text(verbatim: "예약과 주문이 생기면\n오늘 할 일이 여기에 모여요.")
                    .foregroundStyle(Color.secondaryText)
            }
            .accessibilityIdentifier("today.empty")
            .listRowBackground(Color.clear)
        }
        .listSectionSeparator(.hidden)
    }

    private func metricSection(_ today: TodayScreenData) -> some View {
        CardSection {
            if visibility.isHidden(AttentionHidden.metricsID) {
                Button("숫자 다시 보기", systemImage: "eye", action: showMetrics)
                    .accessibilityIdentifier("today.metrics.restore")
            } else {
                MetricStrip(metrics: metrics(today))
                    .accessibilityElement(children: .contain)
                    .accessibilityIdentifier("today.metrics")
                    .listRowInsets(.vertical, 8)
                    .swipeActions(edge: .trailing, allowsFullSwipe: true) {
                        Button("숨기기", systemImage: "eye.slash", action: hideMetrics)
                            .tint(.gray)
                    }
            }
        }
    }

    private func hideMetrics() {
        withAnimation(reduceMotion ? nil : .snappy(duration: 0.25)) { visibility.hide(AttentionHidden.metricsID) }
        app.showToast("숫자 칸을 숨겼어요") { showMetrics() }
    }

    private func showMetrics() {
        withAnimation(reduceMotion ? nil : .snappy(duration: 0.25)) { visibility.restore(AttentionHidden.metricsID) }
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
            // 확인해 주실 일 above asks about earlier days' work and holds the waiting replies, so neither repeats here.
            let asked = Set(CarryOverQuestion.collect(today.tasks.groups, now: .now).flatMap(\.entries).map(\.id))
            let groups = today.tasks.groups.filter { group in group.items.contains { !asked.contains($0.id) } }
            if groups.isEmpty {
                CardSection {
                    Text("오늘 할 일이 없어요")
                        .foregroundStyle(Color.secondaryText)
                }
            }
            // Bookings keep the timeline rail: one node per class, joined by a line, with no separators.
            ForEach(groups) { group in
                let rows = group.items.filter { !asked.contains($0.id) }
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
                        Text(verbatim: today.delivery.transitDetail)
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

    private var subtitle: String {
        let date = Date.now.koreanDay()
        guard let loadedAt = loader.loadedAt else { return date }
        let style = Date.FormatStyle(date: .omitted, time: .shortened, locale: Locale(identifier: "ko_KR"),
                                     timeZone: Calendar.workshop.timeZone)
        return "\(date) · \(loadedAt.formatted(style)) 기준"
    }
}
