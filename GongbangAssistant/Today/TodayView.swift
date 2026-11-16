import SwiftUI

enum TodaySegment: String, CaseIterable, Identifiable {
    case tasks = "오늘 할 일"
    case channels = "SNS·스토어"
    case delivery = "배송"
    case suggestions = "AI 추천"

    var id: Self { self }

    var metrics: [Metric] {
        switch self {
        case .tasks:
            [Metric(value: "8명", label: "예약"), Metric(value: "3건", label: "새 주문"), Metric(value: "2건", label: "발송 예정")]
        case .channels:
            [Metric(value: "1,284", label: "SNS 팔로워"), Metric(value: "3건", label: "새 주문"), Metric(value: "2건", label: "답변 대기")]
        case .delivery:
            [Metric(value: "2건", label: "발송 예정"), Metric(value: "5건", label: "배송 중"), Metric(value: "3건", label: "배송 완료")]
        case .suggestions:
            [Metric(value: "3개", label: "오늘의 추천"), Metric(value: "2건", label: "준비된 초안"), Metric(value: "1건", label: "확인 필요")]
        }
    }
}

struct TodayView: View {
    @State private var segment: TodaySegment = .tasks
    @State private var deliveryFilter = "오늘 발송 3"

    var body: some View {
        NavigationStack {
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
                    .pickerStyle(.segmented)
                    .listRowInsets(EdgeInsets())
                    .listRowBackground(Color.clear)
                }

                segmentContent
            }
            .listStyle(.insetGrouped)
            .navigationTitle("사장님, 좋은 아침이에요")
            .navigationSubtitle("11월 4일 수요일")
        }
    }

    @ViewBuilder
    private var segmentContent: some View {
        switch segment {
        case .tasks:
            ForEach(SampleData.todayTaskGroups) { group in
                Section {
                    ForEach(group.items) { item in
                        TaskRow(item: item)
                    }
                } header: {
                    HStack {
                        Text(group.title)
                        Spacer()
                        Menu("\(group.title) 더보기", systemImage: "ellipsis") {
                            Button("전체 보기") {}
                        }
                        .labelStyle(.iconOnly)
                    }
                }
            }
        case .channels:
            Section {
                ForEach(SampleData.channelCards) { WorkCard(item: $0) }
            } header: {
                Text("채널 현황")
            }
            Section {
                ForEach(SampleData.channelTodos) { WorkCard(item: $0) }
            } header: {
                HStack {
                    Text("오늘 챙길 일")
                    Spacer()
                    Text("2건")
                }
            }
        case .delivery:
            Section {
                Picker("배송 상태", selection: $deliveryFilter) {
                    ForEach(["오늘 발송 3", "배송 중 6", "전체"], id: \.self) { Text($0).tag($0) }
                }
                .pickerStyle(.segmented)
                ForEach(SampleData.deliveryCards) { WorkCard(item: $0) }
            } header: {
                HStack {
                    Text("배송 물품")
                    Spacer()
                    Text("총 2건")
                }
            }
        case .suggestions:
            Section {
                ForEach(SampleData.suggestions) { WorkCard(item: $0) }
            } header: {
                HStack {
                    Text("오늘을 위한 제안")
                    Spacer()
                    Text("공방 현황을 바탕으로")
                }
            }
        }
    }
}

#Preview {
    TodayView()
}
