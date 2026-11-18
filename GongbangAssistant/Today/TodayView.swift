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
            .navigationTitle(greeting)
            .navigationSubtitle(subtitle)
            .navigationDestination(for: AreaRoute.self) { route in
                OperationAreaView(area: route.area, initialFilter: route.filter)
            }
            .inquiryDestination()
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
            Section {
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

            segmentContent(today)
        }
        .listStyle(.insetGrouped)
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
            Section {
                if !store.hasLoadedInquiries {
                    Text("서버 문의를 불러오면 대기 목록이 보여요.")
                        .foregroundStyle(.secondary)
                } else if store.pendingInquiries.isEmpty {
                    Label("답변을 기다리는 문의가 없어요", systemImage: "checkmark.circle")
                        .foregroundStyle(.secondary)
                } else {
                    ForEach(store.pendingInquiries) { InquiryRow(inquiry: $0) }
                }
            } header: {
                SectionHeader(title: "답변 대기 문의 \(store.pendingCount)건", area: .channels, filter: "inquiries")
            }
            ForEach(today.tasks.groups) { group in
                Section {
                    ForEach(group.items) { item in
                        TaskRow(item: item, kind: group.kind)
                    }
                } header: {
                    SectionHeader(title: group.title, area: group.area)
                }
            }
        case .channels:
            Section {
                ForEach(today.channels.cards) { WorkCard(item: $0) }
            } header: {
                SectionHeader(title: "채널 현황", area: .channels)
            }
            Section {
                cards(today.channels.todos, empty: "오늘 챙길 채널 일이 없어요")
            } header: {
                SectionHeader(title: "오늘 챙길 일 \(today.channels.todos.count)건")
            }
        case .delivery:
            Section {
                cards(today.delivery.shipToday, empty: "오늘 발송할 물건이 없어요")
            } header: {
                SectionHeader(title: "오늘 발송할 물건 \(today.delivery.shipToday.count)건", area: .deliveries)
            }
            Section {
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
            Section {
                cards(today.suggestions.items, empty: "지금은 새로운 추천이 없어요")
            } header: {
                SectionHeader(title: "오늘의 추천")
            } footer: {
                Text("공방의 예약과 초안을 바탕으로 골랐어요. 내용을 확인해 주세요.")
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
            ForEach(items) { item in
                WorkCard(item: item, isPrimary: item.id == primaryID)
            }
        }
    }

    private var greeting: String {
        switch Calendar.workshop.component(.hour, from: .now) {
        case 5..<11: "사장님, 좋은 아침이에요"
        case 11..<17: "사장님, 좋은 오후예요"
        case 17..<22: "사장님, 좋은 저녁이에요"
        default: "사장님, 오늘도 수고했어요"
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
