import SwiftUI

struct OperationsView: View {
    @State private var period: OperationPeriod?
    @State private var isPickingPeriod = false
    @State private var loader = Loader<OperationsData>()
    @Environment(AppModel.self) private var app

    private var loadKey: String { "\(period?.rangeText ?? "current")|\(app.dataVersion)" }

    var body: some View {
        NavigationStack {
            LoadableContent(loader: loader, retry: load) { data in
                list(data)
            }
            .navigationTitle("운영")
            .navigationSubtitle(loader.value.map { "먼저 확인할 일 \($0.attentionCount)건" } ?? "")
            .appDestinations()
            .sheet(isPresented: $isPickingPeriod) {
                PeriodPickerSheet(period: period ?? .currentMonth) { period = $0 }
            }
        }
        .task(id: loadKey) { await load() }
    }

    private func load() async {
        let period = period
        await loader.load { try await RoundupAPI.operations(period: period) }
        if let count = loader.value?.attentionCount { app.updateAttention(count) }
    }

    private func list(_ data: OperationsData) -> some View {
        List {
            CardSection {
                ForEach(data.attention) { metric in
                    attentionRow(metric)
                }
            } header: {
                HStack {
                    SectionHeader(title: "먼저 확인해주세요")
                    Spacer()
                    Text("\(data.attentionCount)건")
                        .font(.subheadline.weight(.semibold))
                        .monospacedDigit()
                        .foregroundStyle(.primary)
                }
            }

            periodSection(data)

            CardSection("전체 업무 관리") {
                ForEach(data.areas, id: \.area) { summary in
                    NavigationLink(value: AreaRoute(area: summary.area)) {
                        LabeledContent {
                            Text(summary.display)
                                .monospacedDigit()
                        } label: {
                            Label {
                                Text(summary.area.title)
                                Text(summary.area.summary)
                            } icon: {
                                MenuIcon(systemName: summary.area.systemImage)
                            }
                        }
                    }
                    .accessibilityIdentifier("operations.\(summary.area.rawValue)")
                }
            }

            CardSection("공방 성장") {
                NavigationLink {
                    OpportunitiesView()
                } label: {
                    Label {
                        Text("기회")
                        Text("저장해 둔 마켓·공모·지원사업")
                    } icon: {
                        MenuIcon(systemName: "chart.line.uptrend.xyaxis")
                    }
                }
                .accessibilityIdentifier("operations.opportunities")
            }
        }
        .cardList(separators: .hidden)
        .refreshable { await load() }
    }

    private func periodSection(_ data: OperationsData) -> some View {
        let period = data.period
        return CardSection {
            HStack(spacing: 16) {
                gauge(period)
                VStack(alignment: .leading, spacing: 2) {
                    Text(period.month.key == "custom" ? "선택 기간 처리율" : "\(period.month.title) 처리율")
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                    Text("\(period.total)건 중 \(period.handled)건 처리")
                        .font(.title3.weight(.semibold))
                        .monospacedDigit()
                }
                .accessibilityElement(children: .combine)
                Spacer(minLength: 0)
            }
            .padding(.vertical, 4)
            summaryGrid(period)
                .padding(.vertical, 4)
        } header: {
            ViewThatFits(in: .horizontal) {
                HStack {
                    periodTitle(period)
                    Spacer()
                    periodButton(period)
                }
                VStack(alignment: .leading, spacing: 8) {
                    periodTitle(period)
                    periodButton(period)
                }
            }
        } footer: {
            Text("처리율은 이 기간의 예약·주문·배송·문의 \(period.total)건 중 처리를 마친 \(period.handled)건의 비율이에요.")
        }
    }

    private func periodTitle(_ period: OperationsData.Period) -> some View {
        Text("운영 현황")
            .tracking(0.6)
            .accessibilityAddTraits(.isHeader)
            .accessibilityIdentifier("operations.periodTitle")
    }

    private func periodButton(_ period: OperationsData.Period) -> some View {
        Button {
            isPickingPeriod = true
        } label: {
            HStack(spacing: 4) {
                Text(period.month.key == "custom" ? period.month.range : period.month.title).monospacedDigit()
                Image(systemName: "chevron.down").imageScale(.small)
            }
            .font(.footnote.weight(.semibold))
            .padding(.horizontal, 10)
            .frame(minHeight: 32)
            .background(.fill.tertiary, in: .capsule)
        }
        .textCase(nil)
        .accessibilityLabel("기간 선택, \(period.month.range)")
        .accessibilityIdentifier("operations.period")
    }

    private func attentionRow(_ metric: Metric) -> some View {
        NavigationLink(value: route(for: metric)) {
            LabeledContent {
                Text(metric.display)
                    .font(.body.weight(.semibold))
                    .monospacedDigit()
            } label: {
                Text(metric.label)
                if let due = metric.due {
                    DueLabel(due: due)
                } else if let detail = metric.detail {
                    Text(detail)
                }
            }
        }
    }

    private func route(for metric: Metric) -> AreaRoute {
        switch metric.key {
        case "depositPending": AreaRoute(area: .bookings, filter: "deposit_pending")
        case "pendingInquiries": AreaRoute(area: .channels, filter: "inquiries")
        default: AreaRoute(area: .deliveries, filter: "scheduled")
        }
    }

    private func gauge(_ period: OperationsData.Period) -> some View {
        VStack(spacing: 4) {
            Gauge(value: Double(period.ratePercent ?? 0), in: 0...100) {
                Text("처리율")
            } currentValueLabel: {
                Text(period.rateDisplay)
            }
            .gaugeStyle(.accessoryCircularCapacity)
            .tint(.accentColor)
        }
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("\(period.month.title) 처리율")
        .accessibilityValue(period.rateDisplay)
    }

    private func summaryGrid(_ period: OperationsData.Period) -> some View {
        let columns = stride(from: 0, to: period.metrics.count, by: 2).map {
            Array(period.metrics[$0..<min($0 + 2, period.metrics.count)])
        }
        return Grid(alignment: .leading, horizontalSpacing: 40, verticalSpacing: 14) {
            ForEach(columns, id: \.first?.id) { row in
                GridRow {
                    ForEach(row) { summary($0) }
                }
            }
        }
    }

    private func summary(_ metric: Metric) -> some View {
        VStack(alignment: .leading, spacing: 3) {
            Text(metric.label)
                .font(.subheadline)
                .foregroundStyle(.secondary)
            Text(metric.display)
                .font(.title3.weight(.semibold))
                .monospacedDigit()
            if let detail = metric.detail {
                Text(detail)
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .accessibilityElement(children: .combine)
    }
}

struct OpportunitiesView: View {
    @State private var loader = Loader<[WorkItem]>()
    @Environment(AppModel.self) private var app

    var body: some View {
        LoadableContent(loader: loader, retry: load) { items in
            if items.isEmpty {
                ContentUnavailableView("저장된 기회가 없어요", systemImage: "flag")
            } else {
                List {
                    CardSection {
                        ForEach(items) { WorkCard(item: $0) }
                    }
                }
                .cardList(separators: .hidden)
                .refreshable { await load() }
            }
        }
        .navigationTitle("기회")
        .navigationBarTitleDisplayMode(.inline)
        .task(id: app.dataVersion) { await load() }
    }

    private func load() async {
        await loader.load { try await RoundupAPI.opportunities() }
    }
}
