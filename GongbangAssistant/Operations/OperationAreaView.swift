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
        case .bookings: "calendar.badge.checkmark"
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

    var sortOptions: [AreaFilter] {
        switch self {
        case .orders: [AreaFilter("newest", "최근 주문순"), AreaFilter("oldest", "오래된 주문순")]
        case .deliveries: [AreaFilter("soonest", "마감 임박순"), AreaFilter("latest", "늦은 마감순")]
        case .bookings, .channels: []
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
        }
        .sheet(isPresented: $isAddingBooking) {
            BookingFormSheet()
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
        let items = page.items + extraItems
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
                    ForEach(inquiries) { AssistantDraftRow(inquiry: $0) }
                    ForEach(items) { item in
                        WorkCard(item: item, isPrimary: item.id == primaryID)
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
                if isLoadingMore { ProgressView() } else { Text("더 보기") }
            }
            .disabled(isLoadingMore)
            .accessibilityIdentifier("area.more")
        }
    }

    private var listHeader: some View {
        HStack {
            Text(area.listTitle)
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
