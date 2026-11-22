import SwiftUI

struct OperationsView: View {
    @State private var path = NavigationPath()
    @State private var period: OperationPeriod?
    @State private var isPickingPeriod = false
    @State private var loader = Loader<OperationsData>()
    @Environment(AppModel.self) private var app
    @Environment(\.dynamicTypeSize) private var dynamicTypeSize

    private var loadKey: String { "\(period?.rangeText ?? "current")|\(app.dataVersion)" }

    var body: some View {
        NavigationStack(path: $path) {
            LoadableContent(loader: loader, retry: load) { data in
                list(data)
            }
            .navigationTitle("운영")
            .navigationSubtitle(loader.value.map { "먼저 확인할 일 \($0.attentionCount)건" } ?? "")
            .appDestinations()
            .navigationDestination(for: RemainingWorkRoute.self) { _ in RemainingWorkView() }
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
                if dynamicTypeSize.isAccessibilitySize {
                    ForEach(data.attention) { metric in
                        attentionRow(metric)
                    }
                } else {
                    attentionStrip(data.attention)
                }
            } header: {
                HStack {
                    SectionHeader(title: "먼저 확인해주세요")
                    Spacer()
                    Text("\(data.attentionCount)건")
                        .font(.subheadline.weight(.semibold))
                        .monospacedDigit()
                        .contentTransition(.numericText())
                        .animation(.default, value: data.attentionCount)
                        // `Color.primary` is the label color; `.primary` alone would be the header's gray.
                        .foregroundStyle(Color.primary)
                }
            }

            CollectionStatusSection()

            periodSection(data)

            CardSection("전체 업무 관리") {
                ForEach(data.areas, id: \.area) { summary in
                    NavigationLink(value: AreaRoute(area: summary.area)) {
                        LabeledContent {
                            Text(summary.display)
                                .monospacedDigit()
                                .foregroundStyle(Color.secondaryText)
                        } label: {
                            Label {
                                Text(summary.area.title)
                                Text(summary.area.summary)
                                    .foregroundStyle(Color.secondaryText)
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
                            .foregroundStyle(Color.secondaryText)
                    } icon: {
                        MenuIcon(systemName: "chart.line.uptrend.xyaxis")
                    }
                }
                .accessibilityIdentifier("operations.opportunities")
                #if BUILD_B
                OutreachQuoteLink()
                #endif
            }
        }
        .cardList(separators: .hidden)
        .refreshable { await load() }
    }

    private func periodSection(_ data: OperationsData) -> some View {
        let period = data.period
        return CardSection {
            summaryGrid(period)
                .padding(.vertical, 4)
            if period.total > period.handled {
                NavigationLink(value: RemainingWorkRoute()) {
                    LabeledContent("남은 일") {
                        Text("\(period.total - period.handled)건")
                            .monospacedDigit()
                            .foregroundStyle(Color.secondaryText)
                    }
                }
                .accessibilityIdentifier("operations.remaining")
            }
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
            .font(.subheadline.weight(.semibold))
            .padding(.horizontal, 12)
            .frame(minHeight: 32)
            .background(.fill.tertiary, in: .capsule)
            .frame(minHeight: 44)
            .contentShape(.rect)
        }
        .textCase(nil)
        .accessibilityLabel("기간 선택, \(period.month.range)")
        .accessibilityIdentifier("operations.period")
    }

    /// Three tappable tiles laid out like the today numbers; each opens its filtered list.
    /// Buttons push the route themselves, because a List row with several links fires only one of them.
    private func attentionStrip(_ metrics: [Metric]) -> some View {
        // Tiles share the tallest one's height, so every 보기 sits on the same line whatever the detail's length.
        HStack(alignment: .top, spacing: 0) {
            ForEach(Array(metrics.enumerated()), id: \.element.id) { index, metric in
                if index > 0 {
                    Divider().padding(.vertical, 14)
                }
                Button {
                    path.append(route(for: metric))
                } label: {
                    attentionTile(metric)
                }
                .buttonStyle(AttentionTileStyle())
                .accessibilityElement(children: .ignore)
                .accessibilityLabel("\(metric.due?.isOverdue(at: .now) == true ? "기한 지남, " : "")\(metric.label) \(metric.display)\(metric.detail.map { ", \($0)" } ?? "")")
                .accessibilityHint("목록을 열어요")
                .accessibilityAddTraits(.isButton)
                .accessibilityIdentifier("operations.attention.\(metric.key)")
            }
        }
        .fixedSize(horizontal: false, vertical: true)
        .listRowInsets(EdgeInsets(top: 4, leading: 4, bottom: 4, trailing: 4))
    }

    private func attentionTile(_ metric: Metric) -> some View {
        VStack(spacing: 4) {
            Text(metric.display)
                .font(.title3.bold())
                .monospacedDigit()
            // A label such as "답변 기다리는 문의" takes two lines; every tile reserves both, so the 보기 buttons line up.
            let chevron = Text(Image(systemName: "chevron.forward")).font(.caption2.weight(.bold)).foregroundStyle(.tertiary)
            Text("\(Text(verbatim: metric.label))\u{00A0}\(chevron)")
                .font(.subheadline.weight(.semibold))
                .multilineTextAlignment(.center)
                .lineLimit(2, reservesSpace: true)
                .minimumScaleFactor(0.8)
            Group {
                if let due = metric.due {
                    DueLabel(due: due)
                } else if let detail = metric.detail {
                    // A name keeps its 님 on the same line; alone on the next line it reads as a stray word.
                    Text(detail.replacingOccurrences(of: " 님", with: "\u{00A0}님"))
                }
            }
            .font(.subheadline)
            .foregroundStyle(Color.secondaryText)
            .lineLimit(3)
            .multilineTextAlignment(.center)
            Spacer(minLength: 0)
            Text("보기")
                .font(.subheadline.weight(.semibold))
                .foregroundStyle(.tint)
                .padding(.horizontal, 14)
                .padding(.vertical, 4)
                .background(.tint.opacity(0.12), in: .capsule)
        }
        .frame(maxWidth: .infinity, minHeight: 44, maxHeight: .infinity)
        .padding(.vertical, 10)
        .padding(.horizontal, 4)
        // The corner keeps the mark out of the centered column, so the number stays put when a deadline passes.
        .overlay(alignment: .topLeading) {
            DueMark(due: metric.due)
                .font(.subheadline)
                .padding(6)
        }
        .contentShape(.rect)
    }

    private func attentionRow(_ metric: Metric) -> some View {
        NavigationLink(value: route(for: metric)) {
            LabeledContent {
                Text(metric.display)
                    .font(.body.weight(.semibold))
                    .monospacedDigit()
                    .foregroundStyle(Color.secondaryText)
            } label: {
                Text(metric.label)
                    .overdueMark(for: metric.due)
                if let due = metric.due {
                    DueLabel(due: due)
                } else if let detail = metric.detail {
                    Text(detail)
                        .foregroundStyle(Color.secondaryText)
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
                .foregroundStyle(Color.secondaryText)
            Text(metric.display)
                .font(.title3.weight(.semibold))
                .monospacedDigit()
            if let detail = metric.detail {
                Text(detail)
                    .font(.subheadline)
                    .foregroundStyle(Color.secondaryText)
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
                    // No detail screen exists yet, so the cards show no chevron and only their own action.
                    CardSection {
                        ForEach(items) { item in
                            VStack(alignment: .leading, spacing: 8) {
                                WorkCardContent(item: item)
                                if let action = item.action {
                                    CardActionButton(item: item, action: action)
                                }
                            }
                        }
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

/// The period card's "남은 일" row. It goes through the stack's path like the tiles and the area rows it opens,
/// so back always returns one level.
private struct RemainingWorkRoute: Hashable {}

/// Where the period's unprocessed work lives: each row opens that area already filtered.
struct RemainingWorkView: View {
    private let rows: [(OperationArea, String, String)] = [
        (.bookings, "deposit_pending", "예약금을 기다리는 예약"),
        (.orders, "paid", "확인할 주문"),
        (.deliveries, "scheduled", "보낼 택배"),
        (.channels, "inquiries", "답변 기다리는 문의"),
    ]

    var body: some View {
        List {
            CardSection {
                ForEach(rows, id: \.0) { area, filter, title in
                    NavigationLink(value: AreaRoute(area: area, filter: filter)) {
                        Label {
                            Text(title)
                        } icon: {
                            MenuIcon(systemName: area.systemImage)
                        }
                    }
                }
            }
        }
        .cardList(separators: .hidden)
        .navigationTitle("남은 일")
        .navigationBarTitleDisplayMode(.inline)
    }
}

/// Darkens a tile while it is pressed, so the owner sees it reacts like a button.
private struct AttentionTileStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .background(configuration.isPressed ? AnyShapeStyle(.fill.secondary) : AnyShapeStyle(.clear),
                        in: .inner)
            .animation(.easeOut(duration: 0.12), value: configuration.isPressed)
    }
}
