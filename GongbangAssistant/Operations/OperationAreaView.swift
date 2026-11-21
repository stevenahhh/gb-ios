import SwiftUI
import RoundupCore

struct AreaFilter: Hashable {
    let key: String
    let label: String

    init(_ key: String, _ label: String) {
        self.key = key
        self.label = label
    }
}

enum OperationArea: String, Decodable, CaseIterable, Identifiable, Hashable {
    case bookings
    case orders
    case deliveries
    case channels

    var id: Self { self }

    var title: String {
        switch self {
        case .bookings: "예약 관리"
        case .orders: "주문 관리"
        case .deliveries: "배송 관리"
        case .channels: "SNS·스토어 관리"
        }
    }

    var summary: String {
        switch self {
        case .bookings: "예약금·일정 변경·출석을 관리해요"
        case .orders: "주문 확인부터 처리 상태까지"
        case .deliveries: "포장·송장·배송 현황을 확인해요"
        case .channels: "채널과 문의, 콘텐츠를 관리해요"
        }
    }

    var systemImage: String {
        switch self {
        case .bookings: "calendar"
        case .orders: "bag"
        case .deliveries: "shippingbox"
        case .channels: "bubble.left.and.bubble.right"
        }
    }

    var path: String {
        switch self {
        case .bookings: "bookings"
        case .orders: "orders"
        case .deliveries: "shipments"
        case .channels: "channels"
        }
    }

    var filterParameter: String { self == .channels ? "section" : "status" }

    var filters: [AreaFilter] {
        switch self {
        case .bookings:
            [AreaFilter("all", "전체"), AreaFilter("confirmed", "확정"), AreaFilter("deposit_pending", "예약금 대기")]
        case .orders:
            [AreaFilter("all", "전체"), AreaFilter("paid", "결제 완료"), AreaFilter("processing", "처리 중")]
        case .deliveries:
            [AreaFilter("all", "전체"), AreaFilter("scheduled", "발송 예정"),
             AreaFilter("in_transit", "배송 중"), AreaFilter("delivered", "완료")]
        case .channels:
            [AreaFilter("all", "전체"), AreaFilter("channels", "채널"),
             AreaFilter("inquiries", "문의"), AreaFilter("content", "콘텐츠")]
        }
    }

    var searchPrompt: String {
        switch self {
        case .bookings: "예약자명 또는 클래스 검색"
        case .orders: "주문번호 또는 고객명 검색"
        case .deliveries: "주문번호 또는 운송장 검색"
        case .channels: "채널 또는 콘텐츠 검색"
        }
    }

    var listTitle: String {
        switch self {
        case .bookings: "예약 목록"
        case .orders: "주문 목록"
        case .deliveries: "발송·배송 목록"
        case .channels: "채널과 할 일"
        }
    }

    var emptyTitle: String {
        switch self {
        case .bookings: "해당하는 예약이 없어요"
        case .orders: "해당하는 주문이 없어요"
        case .deliveries: "해당하는 배송이 없어요"
        case .channels: "해당하는 항목이 없어요"
        }
    }

    var noDataTitle: String {
        switch self {
        case .bookings: "아직 예약이 없어요"
        case .orders: "아직 주문이 없어요"
        case .deliveries: "발송할 물건이 없어요"
        case .channels: "연결된 채널이 없어요"
        }
    }

    var noDataMessage: String {
        switch self {
        case .bookings: "예약을 직접 등록해\u{00A0}보세요."
        case .orders: "주문이 등록되면\n여기에 모여요."
        case .deliveries: "주문이 들어오면\n발송할 물건이 여기에 생겨요."
        case .channels: "등록된 채널이 생기면\n여기에 모여요."
        }
    }

    /// Orders and parcels move through the same steps, so several can take one step together.
    var allowsBatch: Bool { self == .orders || self == .deliveries }

    var sortOptions: [AreaFilter] {
        switch self {
        case .orders: [AreaFilter("newest", "최근 주문순"), AreaFilter("oldest", "오래된 주문순")]
        case .deliveries: [AreaFilter("soonest", "마감 임박순"), AreaFilter("latest", "늦은 마감순")]
        case .bookings, .channels: []
        }
    }
}

/// A row while several are being chosen: the whole row toggles, and rows with no step left stay dimmed.
private struct SelectableWorkRow: View {
    let item: WorkItem
    let isSelected: Bool
    let toggle: () -> Void

    var body: some View {
        let isChoosable = item.batchCode != nil
        Button(action: toggle) {
            HStack(spacing: 12) {
                Image(systemName: isSelected ? "checkmark.circle.fill" : "circle")
                    .font(.title2)
                    .foregroundStyle(isSelected ? Color.primary : Color.secondaryText)
                    .frame(minWidth: 44, minHeight: 44)
                    .accessibilityHidden(true)
                WorkCardContent(item: item)
            }
            .contentShape(.rect)
        }
        .buttonStyle(.plain)
        .disabled(!isChoosable)
        .opacity(isChoosable ? 1 : 0.4)
        .accessibilityAddTraits(isSelected ? .isSelected : [])
        .accessibilityHint(isChoosable ? "" : "남은 단계가 없어요.")
        .accessibilityIdentifier("select.\(item.id)")
    }
}

/// The control bar for chosen rows: the earliest step among them is the one prominent button, and any later
/// steps share one row beneath it, so the bar stays short and the chosen rows stay visible.
private struct BatchActionBar: View {
    let choosable: [WorkItem]
    @Binding var selection: Set<WorkItem.ID>
    let isRunning: Bool
    let run: (ActionCode, [WorkItem]) -> Void

    private var groups: [(code: ActionCode, items: [WorkItem])] {
        let chosen = choosable.filter { selection.contains($0.id) }
        return ActionCode.fulfilment.compactMap { code in
            let matching = chosen.filter { $0.batchCode == code }
            return matching.isEmpty ? nil : (code, matching)
        }
    }

    private var isAllSelected: Bool { !choosable.isEmpty && choosable.allSatisfy { selection.contains($0.id) } }

    var body: some View {
        VStack(spacing: 8) {
            if let first = groups.first {
                stepButton(first, isProminent: true)
            }
            let rest = groups.dropFirst()
            if !rest.isEmpty {
                ViewThatFits(in: .horizontal) {
                    HStack(spacing: 8) { ForEach(rest, id: \.code) { stepButton($0, isProminent: false) } }
                    VStack(spacing: 8) { ForEach(rest, id: \.code) { stepButton($0, isProminent: false) } }
                }
            }
            HStack {
                Text(groups.isEmpty ? "처리할 항목을 골라 주세요" : "\(groups.map(\.items.count).reduce(0, +))건 골랐어요")
                    .font(.subheadline)
                    .foregroundStyle(Color.secondaryText)
                Spacer(minLength: 8)
                Button(isAllSelected ? "선택 해제" : "모두 선택") {
                    selection = isAllSelected ? [] : Set(choosable.map(\.id))
                }
                .frame(minHeight: 44)
                .disabled(choosable.isEmpty)
                .accessibilityIdentifier("batch.selectAll")
            }
        }
        .padding(.horizontal, 16)
        .padding(.top, 12)
        .padding(.bottom, 4)
        .background(.bar)
    }

    @ViewBuilder
    private func stepButton(_ group: (code: ActionCode, items: [WorkItem]), isProminent: Bool) -> some View {
        let button = Button {
            run(group.code, group.items)
        } label: {
            BusyLabel(title: "\(group.code.batchLabel) \(group.items.count)건", isBusy: isRunning, isProminent: isProminent)
                .font(isProminent ? .body.weight(.semibold) : .subheadline.weight(.semibold))
                .lineLimit(1)
                .fixedSize()
                .frame(maxWidth: .infinity, minHeight: isProminent ? 30 : 22)
        }
        .controlSize(isProminent ? .large : .regular)
        .disabled(isRunning)
        .accessibilityIdentifier("batch.\(group.code.rawValue)")
        if isProminent {
            button.buttonStyle(.borderedProminent)
        } else {
            button.buttonStyle(.bordered)
        }
    }
}

struct OperationAreaView: View {
    private struct LoadKey: Hashable {
        let filter: String
        let query: String
        let sort: String?
        let version: Int
    }

    let area: OperationArea
    @State private var filter: String
    @State private var query = ""
    @State private var sort: String?
    @State private var loader = Loader<AreaPage>()
    @State private var extraItems: [WorkItem] = []
    @State private var extraInquiries: [Inquiry] = []
    @State private var hasMore = false
    @State private var nextOffset = 0
    @State private var isLoadingMore = false
    @State private var isAddingBooking = false
    /// The chosen rows while the owner works on several at once; nil outside that mode.
    @State private var selection: Set<WorkItem.ID>?
    @State private var invoiceItems: [WorkItem] = []
    @Environment(AppModel.self) private var app

    init(area: OperationArea, initialFilter: String? = nil) {
        self.area = area
        _filter = State(initialValue: initialFilter ?? area.filters[0].key)
        _sort = State(initialValue: area.sortOptions.first?.key)
    }

    private var isUnfiltered: Bool { filter == area.filters[0].key && query.isEmpty }
    private var loadKey: LoadKey { LoadKey(filter: filter, query: query, sort: sort, version: app.dataVersion) }

    var body: some View {
        LoadableContent(loader: loader, retry: load) { page in
            if page.total == 0 && isUnfiltered {
                noDataView
            } else {
                list(page)
            }
        }
        .navigationTitle(area.title)
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            if area == .bookings {
                ToolbarItem(placement: .primaryAction) {
                    Button("예약 등록", systemImage: "plus") {
                        isAddingBooking = true
                    }
                    .accessibilityIdentifier("booking.add")
                }
            }
            if area.allowsBatch, loader.value.map({ $0.total > 0 }) == true {
                ToolbarItem(placement: .primaryAction) {
                    Button(selection == nil ? "선택" : "완료") {
                        withAnimation { selection = selection == nil ? [] : nil }
                    }
                    .accessibilityIdentifier("area.select")
                }
            }
        }
        .sheet(isPresented: $isAddingBooking) {
            BookingFormSheet()
        }
        .sheet(isPresented: Binding(get: { !invoiceItems.isEmpty }, set: { if !$0 { invoiceItems = [] } })) {
            InvoiceSheet(items: invoiceItems)
        }
        .task(id: loadKey) {
            // Typing replaces this task, so only the settled query reaches the server.
            if !query.isEmpty {
                try? await Task.sleep(for: .milliseconds(250))
                guard !Task.isCancelled else { return }
            }
            await load()
        }
    }

    private func currentQuery(offset: Int = 0) -> AreaQuery {
        AreaQuery(filter: filter, text: query.trimmingCharacters(in: .whitespaces), sort: sort, offset: offset)
    }

    private func load() async {
        let (area, request) = (area, currentQuery())
        await loader.load { try await RoundupAPI.area(area, query: request) }
        extraItems = []
        extraInquiries = []
        hasMore = loader.value?.hasMore ?? false
        nextOffset = request.limit
    }

    private func loadMore() async {
        isLoadingMore = true
        defer { isLoadingMore = false }
        let request = currentQuery(offset: nextOffset)
        do {
            let next = try await RoundupAPI.area(area, query: request)
            extraItems += next.items
            extraInquiries += next.inquiries ?? []
            hasMore = next.hasMore
            nextOffset += request.limit
        } catch is CancellationError {
            return
        } catch {
            app.failureMessage = error.localizedDescription
        }
    }

    private func list(_ page: AreaPage) -> some View {
        let items = (page.items + extraItems).overdueFirst()
        let inquiries = (page.inquiries ?? []) + extraInquiries
        let primaryID = items.primaryActionID
        return List {
            CardSection {
                MetricStrip(metrics: page.metrics)
            }

            Section {
                Picker("상태", selection: $filter) {
                    ForEach(area.filters, id: \.key) { Text($0.label).tag($0.key) }
                }
                .adaptivePickerStyle()
                .accessibilityIdentifier("area.filter")
                .listRowInsets(EdgeInsets())
                .listRowBackground(Color.clear)
            }
            .listSectionSeparator(.hidden)

            if items.isEmpty && inquiries.isEmpty {
                CardSection(area.listTitle) { emptyView }
            } else if area == .bookings {
                ForEach(bookingDays(items), id: \.day) { group in
                    CardSection("\(group.title) · \(group.items.count)건") {
                        ForEach(group.items) { item in
                            if let summary = item.booking {
                                BookingListRow(item: item, summary: summary)
                            }
                        }
                    }
                }
                moreSection
            } else {
                CardSection {
                    // Overdue rows lead the whole list, above the inquiries too.
                    let overdue = items.filter { $0.due?.isOverdue(at: .now) == true }
                    ForEach(overdue) { item in
                        row(item, isPrimary: item.id == primaryID)
                    }
                    ForEach(inquiries) { AssistantDraftRow(inquiry: $0) }
                    ForEach(items.filter { $0.due?.isOverdue(at: .now) != true }) { item in
                        row(item, isPrimary: item.id == primaryID)
                    }
                    moreButton
                } header: {
                    listHeader
                }
            }
        }
        .cardList(separators: .hidden)
        .searchable(text: $query, placement: .navigationBarDrawer(displayMode: .always), prompt: area.searchPrompt)
        .refreshable { await load() }
        .safeAreaInset(edge: .bottom) {
            if let selection {
                BatchActionBar(
                    choosable: items.filter { $0.batchCode != nil },
                    selection: Binding(get: { selection }, set: { self.selection = $0 }),
                    isRunning: app.isRunning(batchRunID), run: runBatch
                )
            }
        }
    }

    @ViewBuilder
    private func row(_ item: WorkItem, isPrimary: Bool) -> some View {
        if let selection {
            SelectableWorkRow(item: item, isSelected: selection.contains(item.id)) {
                self.selection = selection.symmetricDifference([item.id])
            }
        } else {
            WorkCard(item: item, isPrimary: isPrimary)
        }
    }

    private let batchRunID = "area.batch"

    /// Chosen rows stay chosen after a step, so the bar offers their next step at once.
    private func runBatch(_ code: ActionCode, _ items: [WorkItem]) {
        guard code != .registerInvoice else {
            invoiceItems = items
            return
        }
        Task {
            var changed: [WorkItem] = []
            let saved = await app.run(id: batchRunID) { changed = try await RoundupAPI.perform(code, on: items) }
            if saved { app.showStepToast(code, title: items[0].title, changed: changed) }
        }
    }

    private func bookingDays(_ items: [WorkItem]) -> [(day: String, title: String, items: [WorkItem])] {
        var groups: [(day: String, title: String, items: [WorkItem])] = []
        for item in items {
            guard let summary = item.booking else { continue }
            if let index = groups.firstIndex(where: { $0.day == summary.day }) {
                groups[index].items.append(item)
            } else {
                groups.append((summary.day, summary.dayTitle, [item]))
            }
        }
        return groups
    }

    @ViewBuilder
    private var moreSection: some View {
        if hasMore {
            CardSection { moreButton }
        }
    }

    @ViewBuilder
    private var moreButton: some View {
        if hasMore {
            Button {
                Task { await loadMore() }
            } label: {
                BusyLabel(title: "더 보기", isBusy: isLoadingMore)
            }
            .disabled(isLoadingMore)
            .accessibilityIdentifier("area.more")
        }
    }

    /// SNS·스토어 관리 names the section after the chosen filter.
    private var listTitle: String {
        guard area == .channels else { return area.listTitle }
        switch filter {
        case "channels": return "채널"
        case "inquiries": return "답변 기다리는 문의"
        case "content": return "홍보 글 초안"
        default: return area.listTitle
        }
    }

    private var listHeader: some View {
        HStack {
            Text(listTitle)
            if !area.sortOptions.isEmpty {
                Spacer()
                Menu {
                    Picker("정렬", selection: $sort) {
                        ForEach(area.sortOptions, id: \.key) { Text($0.label).tag(Optional($0.key)) }
                    }
                    .pickerStyle(.inline)
                } label: {
                    Text(area.sortOptions.first { $0.key == sort }?.label ?? "정렬")
                        .font(.subheadline)
                        .frame(minHeight: 44)
                }
                .textCase(nil)
                .accessibilityIdentifier("area.sort")
            }
        }
    }

    private var noDataView: some View {
        ContentUnavailableView {
            Label(area.noDataTitle, systemImage: area.systemImage)
        } description: {
            Text(keepingWords: area.noDataMessage)
        } actions: {
            if area == .bookings {
                Button {
                    isAddingBooking = true
                } label: {
                    Text("예약 등록하기")
                        .foregroundStyle(Color(.systemBackground))
                }
                .buttonStyle(.borderedProminent)
                .controlSize(.large)
            }
        }
        .accessibilityIdentifier("area.empty")
    }

    @ViewBuilder
    private var emptyView: some View {
        if !query.isEmpty {
            ContentUnavailableView.search(text: query)
        } else {
            ContentUnavailableView {
                Label(area.emptyTitle, systemImage: "tray")
            } description: {
                Text(keepingWords: "지금 고른 상태에는 항목이 없어요.")
            } actions: {
                if filter != area.filters[0].key {
                    Button("전체 보기") {
                        filter = area.filters[0].key
                    }
                    .buttonStyle(.bordered)
                    .controlSize(.large)
                }
            }
        }
    }
}
