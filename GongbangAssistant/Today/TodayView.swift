import SwiftUI

enum TodaySegment: String, CaseIterable, Identifiable {
    case tasks = "할 일"
    case channels = "채널"
    case delivery = "배송"
    case suggestions = "비서 추천"

    var id: Self { self }

    var metrics: [Metric] {
        switch self {
        case .tasks:
            [Metric(value: "8명", label: "예약"), Metric(value: "3건", label: "새 주문"), Metric(value: "2건", label: "발송 예정")]
        case .channels:
            [Metric(value: "1,284", label: "SNS 팔로워"), Metric(value: "3건", label: "새 주문"), Metric(value: "3건", label: "미답변 문의")]
        case .delivery:
            [Metric(value: "2건", label: "발송 예정"), Metric(value: "2건", label: "배송 중"), Metric(value: "1건", label: "배송 완료")]
        case .suggestions:
            [Metric(value: "3개", label: "오늘의 추천"), Metric(value: "2건", label: "준비된 초안"), Metric(value: "1건", label: "확인 필요")]
        }
    }
}

struct TodayView: View {
    @SceneStorage("today.segment") private var segment: TodaySegment = .tasks
    @State private var state = ScreenState.launch
    @State private var updatedAt = Date.now

    var body: some View {
        NavigationStack {
            content
                .navigationTitle(greeting)
                .navigationSubtitle(subtitle)
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
        case .empty:
            ContentUnavailableView {
                Label("아직 연결된 채널이 없어요", systemImage: "link")
            } description: {
                Text(keepingWords: "네이버 예약과 인스타그램을 연결하면\n오늘 할 일이 여기에 모여요.")
            } actions: {
                NavigationLink {
                    PlaceholderScreen(title: "채널 연결", systemImage: "link")
                } label: {
                    Text("채널 연결하기")
                        .foregroundStyle(Color(.systemBackground))
                }
                .buttonStyle(.borderedProminent)
                .controlSize(.large)
            }
        case .error:
            LoadErrorView { state = .loaded }
        case .loading, .loaded:
            list
                .redacted(reason: state == .loading ? .placeholder : [])
                .allowsHitTesting(state != .loading)
        }
    }

    private var list: some View {
        List {
            Section {
                MetricStrip(metrics: segment.metrics)
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

            segmentContent
        }
        .listStyle(.insetGrouped)
        .refreshable {
            updatedAt = .now
        }
    }

    @ViewBuilder
    private var segmentContent: some View {
        switch segment {
        case .tasks:
            ForEach(SampleData.todayTaskGroups) { group in
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
                ForEach(SampleData.channelCards) { WorkCardRow(item: $0) }
            } header: {
                SectionHeader(title: "채널 현황", area: .channels)
            }
            Section {
                cards(SampleData.channelTodos)
            } header: {
                SectionHeader(title: "오늘 챙길 일 \(SampleData.channelTodos.count)건")
            }
        case .delivery:
            Section {
                cards(SampleData.shipToday)
            } header: {
                SectionHeader(title: "오늘 발송할 물건 \(SampleData.shipToday.count)건", area: .deliveries)
            }
            Section {
                NavigationLink(value: AreaRoute(area: .deliveries, filter: "배송 중")) {
                    VStack(alignment: .leading, spacing: 4) {
                        PhraseText(text: "배송 중 2건 · 오늘 도착 1건")
                            .font(.headline)
                        Text(keepingWords: "배송 지연 없이 잘 이동하고 있어요.")
                            .font(.subheadline)
                            .foregroundStyle(.secondary)
                    }
                    .padding(.vertical, 4)
                }
                ForEach(SampleData.inTransit) { WorkCardRow(item: $0) }
            } header: {
                SectionHeader(title: "이동 중인 배송")
            }
        case .suggestions:
            Section {
                cards(SampleData.suggestions)
            } header: {
                SectionHeader(title: "오늘의 추천")
            } footer: {
                Text("비서가 공방 현황을 보고 골랐어요. 틀릴 수 있으니 내용을 확인해 주세요.")
            }
        }
    }

    private func cards(_ items: [WorkItem]) -> some View {
        let primaryID = items.first { item in
            if case .perform = item.action { true } else { false }
        }?.id
        return ForEach(items) { item in
            WorkCardRow(item: item, isPrimary: item.id == primaryID)
        }
    }

    private var greeting: String {
        switch Calendar.current.component(.hour, from: .now) {
        case 5..<11: "사장님, 좋은 아침이에요"
        case 11..<17: "사장님, 좋은 오후예요"
        case 17..<22: "사장님, 좋은 저녁이에요"
        default: "사장님, 오늘도 수고했어요"
        }
    }

    private var subtitle: String {
        let time = updatedAt.formatted(Date.FormatStyle(date: .omitted, time: .shortened).locale(Locale(identifier: "ko_KR")))
        return "11월 4일 수요일 · \(time) 기준"
    }
}

#Preview {
    TodayView()
}
