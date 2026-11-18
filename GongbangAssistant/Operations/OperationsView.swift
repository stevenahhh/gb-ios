import SwiftUI
import RoundupCore

struct AreaRoute: Hashable {
    let area: OperationArea
    var filter: String?
}

struct OperationsView: View {
    enum Period: String, CaseIterable, Identifiable {
        case november = "11월"
        case october = "10월"

        var id: Self { self }

        var range: String {
            switch self {
            case .november: "11.01 – 11.30"
            case .october: "10.01 – 10.31"
            }
        }
    }

    @State private var period = Period.november
    @Environment(DemoStore.self) private var store

    private var attentionCount: Int {
        SampleData.attentionCount(pendingInquiries: store.pendingCount)
    }

    var body: some View {
        NavigationStack {
            List {
                Section {
                    attentionRow("예약금 미확인", count: 2, systemImage: "wonsign.circle", route: AreaRoute(area: .bookings, filter: "예약금 대기"))
                    attentionRow("미답변 문의", count: store.pendingCount, systemImage: "bubble.left", route: AreaRoute(area: .channels, filter: "문의"))
                    attentionRow("발송 마감", count: 2, systemImage: "shippingbox", route: AreaRoute(area: .deliveries, filter: "발송 예정"))
                } header: {
                    HStack {
                        SectionHeader(title: "먼저 확인해주세요")
                        StatusBadge(Status(text: "\(attentionCount)건", tone: .attention))
                    }
                }

                Section {
                    ViewThatFits(in: .horizontal) {
                        HStack(spacing: 20) {
                            gauge
                            summaryGrid
                        }
                        VStack(alignment: .leading, spacing: 12) {
                            gauge
                            summaryGrid
                        }
                    }
                    .padding(.vertical, 4)
                    HStack(spacing: 0) {
                        comparison("+12%")
                        Divider().frame(height: 36)
                        comparison("+5%")
                    }
                } header: {
                    ViewThatFits(in: .horizontal) {
                        HStack {
                            periodTitle
                            Spacer()
                            periodMenu
                        }
                        VStack(alignment: .leading, spacing: 8) {
                            periodTitle
                            periodMenu
                        }
                    }
                }

                Section("전체 업무 관리") {
                    ForEach(OperationArea.allCases) { area in
                        NavigationLink(value: AreaRoute(area: area)) {
                            LabeledContent {
                                Text(area.count)
                                    .monospacedDigit()
                            } label: {
                                Label {
                                    Text(area.title)
                                    Text(area.summary)
                                } icon: {
                                    Image(systemName: area.systemImage)
                                }
                            }
                        }
                        .accessibilityIdentifier("operations.\(area.rawValue)")
                    }
                }

                Section("공방 성장") {
                    NavigationLink {
                        PlaceholderScreen(title: "기회", systemImage: "sparkles")
                    } label: {
                        Label {
                            Text("기회")
                            Text("마켓·공모·지원사업 모집 공고")
                        } icon: {
                            Image(systemName: "sparkles")
                        }
                    }
                    NavigationLink {
                        PlaceholderScreen(title: "리포트", systemImage: "chart.bar.xaxis")
                    } label: {
                        Label {
                            Text("리포트")
                            Text("주간·월간 숫자")
                        } icon: {
                            Image(systemName: "chart.bar.xaxis")
                        }
                    }
                }
            }
            .listStyle(.insetGrouped)
            .navigationTitle("운영")
            .navigationSubtitle("먼저 확인할 일 \(attentionCount)건")
            .navigationDestination(for: AreaRoute.self) { route in
                OperationAreaView(area: route.area, initialFilter: route.filter)
            }
            .navigationDestination(for: WorkItem.self) { item in
                WorkDetailView(item: item)
            }
            .inquiryDestination()
        }
    }

    private var periodTitle: some View {
        Text("\(period.rawValue) 운영 현황")
            .accessibilityAddTraits(.isHeader)
    }

    private var periodMenu: some View {
        Menu {
            Picker("기간", selection: $period) {
                ForEach(Period.allCases) { Text($0.rawValue).tag($0) }
            }
            .pickerStyle(.inline)
        } label: {
            Label(period.range, systemImage: "chevron.down")
                .labelStyle(.titleAndIcon)
                .font(.footnote.weight(.semibold))
                .padding(.horizontal, 10)
                .frame(minHeight: 32)
                .background(.fill.tertiary, in: .capsule)
        }
        .textCase(nil)
        .accessibilityLabel("기간 선택, \(period.rawValue)")
    }

    private func attentionRow(_ title: String, count: Int, systemImage: String, route: AreaRoute) -> some View {
        NavigationLink(value: route) {
            LabeledContent {
                Text("\(count)건")
                    .font(.body.weight(.semibold))
                    .monospacedDigit()
            } label: {
                Label(title, systemImage: systemImage)
            }
        }
    }

    private var gauge: some View {
        VStack(spacing: 4) {
            Gauge(value: 24, in: 0...32) {
                Text("처리율")
            } currentValueLabel: {
                Text("75%")
            }
            .gaugeStyle(.accessoryCircularCapacity)
            .tint(.accentColor)
            Text("처리율")
                .font(.subheadline)
                .foregroundStyle(.secondary)
        }
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("\(period.rawValue) 처리율")
        .accessibilityValue("75퍼센트")
    }

    private var summaryGrid: some View {
        Grid(alignment: .leading, horizontalSpacing: 24, verticalSpacing: 8) {
            GridRow {
                summary("예약", "24건")
                summary("주문", "8건")
            }
            GridRow {
                summary("배송", "5건")
                summary("SNS", "2개")
            }
        }
    }

    private func comparison(_ change: String) -> some View {
        VStack(alignment: .leading, spacing: 0) {
            Text("전월 대비")
                .font(.subheadline)
                .foregroundStyle(.secondary)
            Text(change)
                .font(.title2.bold())
                .monospacedDigit()
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(.leading, 4)
        .accessibilityElement(children: .combine)
    }

    private func summary(_ label: String, _ value: String) -> some View {
        VStack(alignment: .leading, spacing: 0) {
            Text(label)
                .font(.subheadline)
                .foregroundStyle(.secondary)
            Text(value)
                .font(.headline)
                .monospacedDigit()
        }
        .accessibilityElement(children: .combine)
    }
}

#Preview {
    OperationsView()
        .environment(DemoStore())
}
