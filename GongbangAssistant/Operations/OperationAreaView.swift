import SwiftUI

enum OperationArea: String, CaseIterable, Identifiable, Hashable {
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

    var count: String {
        switch self {
        case .bookings: "32건"
        case .orders: "38건"
        case .deliveries: "5건"
        case .channels: "2개"
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

    var metrics: [Metric] {
        switch self {
        case .bookings:
            [Metric(value: "32건", label: "전체"), Metric(value: "24건", label: "확정"), Metric(value: "2건", label: "예약금 대기")]
        case .orders:
            [Metric(value: "38건", label: "전체 주문"), Metric(value: "8건", label: "처리 대기"), Metric(value: "126만원", label: "이번 달 매출")]
        case .deliveries:
            [Metric(value: "2건", label: "발송 예정"), Metric(value: "2건", label: "배송 중"), Metric(value: "1건", label: "배송 완료")]
        case .channels:
            [Metric(value: "2개", label: "연결 채널"), Metric(value: "3건", label: "미답변 문의"), Metric(value: "2건", label: "홍보 초안")]
        }
    }

    var filters: [String] {
        switch self {
        case .bookings: ["전체", "확정", "예약금 대기"]
        case .orders: ["전체", "결제 완료", "처리 중"]
        case .deliveries: ["전체", "발송 예정", "배송 중", "완료"]
        case .channels: ["전체", "채널", "문의", "콘텐츠"]
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
        case .bookings: "네이버 예약을 연결하거나\n직접 등록해\u{00A0}보세요."
        case .orders: "스마트스토어를 연결하면\n주문이 여기에 모여요."
        case .deliveries: "주문이 들어오면\n발송할 물건이 여기에 생겨요."
        case .channels: "인스타그램과 네이버 스마트스토어를\n연결해\u{00A0}보세요."
        }
    }

    var noDataAction: String? {
        switch self {
        case .bookings: "예약 등록하기"
        case .orders, .channels: "채널 연결하기"
        case .deliveries: nil
        }
    }

    var sortOptions: [String] {
        switch self {
        case .orders: ["최근 주문순", "오래된 주문순"]
        case .deliveries: ["마감 임박순", "늦은 마감순"]
        case .bookings, .channels: []
        }
    }

    var items: [WorkItem] {
        Self.catalog[self] ?? []
    }

    private static let catalog: [OperationArea: [WorkItem]] = Dictionary(uniqueKeysWithValues: allCases.map { ($0, $0.makeItems()) })

    private func makeItems() -> [WorkItem] {
        switch self {
        case .bookings:
            [
                WorkItem(title: "도자기 원데이 클래스", status: Status(text: "확정", tone: .done),
                         lines: ["11월 4일 수 · 10:00–11:30", "김*연 외 3명 · 예약금 확인 완료"], tag: "확정", action: .open),
                WorkItem(title: "나만의 머그컵 만들기", status: Status(text: "예약금 대기", tone: .attention),
                         lines: ["11월 5일 목 · 14:00–16:00", "박*은 · 2명"], deadline: "입금 기한 오늘 18:00",
                         tag: "예약금 대기", action: .perform("입금 확인하기")),
                WorkItem(title: "원데이 물레 체험", status: Status(text: "예약금 대기", tone: .attention),
                         lines: ["11월 8일 일 · 11:00–12:30", "최*우 · 1명"], deadline: "입금 기한 내일 12:00",
                         tag: "예약금 대기", action: .perform("입금 확인하기")),
                WorkItem(title: "주말 도자기 클래스", status: Status(text: "확정", tone: .done),
                         lines: ["11월 7일 토 · 10:00–12:00", "이*진 외 5명 · 남은 자리 3개"], tag: "확정", action: .open),
            ]
        case .orders:
            [
                WorkItem(title: "머그컵 2종 세트", status: Status(text: "결제 완료", tone: .done),
                         lines: ["#1042 · 11월 4일 주문 · 네이버 스토어", "김*연 · 1개 · 42,000원"], tag: "결제 완료",
                         action: .perform("주문 확인하기")),
                WorkItem(title: "오롯 세라믹 플레이트", status: Status(text: "처리 중", tone: .progress),
                         lines: ["#1043 · 11월 4일 주문 · 네이버 스토어", "이*진 · 2개 · 56,000원"], tag: "처리 중", action: .open),
                WorkItem(title: "핸드메이드 미니 화병", status: Status(text: "결제 완료", tone: .done),
                         lines: ["#1044 · 11월 4일 주문 · 네이버 스토어", "정*우 · 1개 · 28,000원"], tag: "결제 완료",
                         action: .perform("주문 확인하기")),
            ]
        case .deliveries:
            [
                WorkItem(title: "머그컵 2종 세트", status: Status(text: "포장 대기", tone: .attention),
                         lines: ["#1042 · 김*연 · 1개", "깨지지 않게 포장 필요"], deadline: "오늘 16:00 택배 수거",
                         tag: "발송 예정", action: .perform("포장 완료하기")),
                WorkItem(title: "오롯 세라믹 플레이트", status: Status(text: "송장 대기", tone: .attention),
                         lines: ["#1043 · 이*진 · 2개", "포장 완료 · 오늘 발송 예정"], tag: "발송 예정",
                         action: .perform("송장 등록하기")),
                WorkItem(title: "핸드메이드 커피잔", status: Status(text: "배송 중", tone: .progress),
                         lines: ["#1038 · 최*서 · 1개", "택배사 인계 완료 · 내일 도착 예정"], tag: "배송 중", action: .open),
                WorkItem(title: "도자기 찬기 3종 세트", status: Status(text: "배송 중", tone: .progress),
                         lines: ["#1044 · 안*지 · 1개", "오늘 도착 예정"], tag: "배송 중", action: .open),
                WorkItem(title: "핸드메이드 머그컵", status: Status(text: "배송 완료", tone: .done),
                         lines: ["#1031 · 윤*아 · 1개", "11월 3일 도착"], tag: "완료", action: .open),
            ]
        case .channels:
            [
                WorkItem(title: "Instagram", status: Status(text: "연결됨", tone: .done),
                         lines: ["@orot.studio · 팔로워 1,284", "이번 주 +24 · 게시물 초안 2건"], tag: "채널", action: .open),
                WorkItem(title: "네이버 스마트스토어", status: Status(text: "연결됨", tone: .done),
                         lines: ["오롯 공방 · 이번 달 주문 38건", "상품 문의 3건 · 리뷰 답글 대기 2건"], tag: "채널", action: .open),
                WorkItem(title: "선물 포장이 되나요?", status: Status(text: "답변 대기", tone: .attention),
                         lines: ["네이버 스마트스토어 · 머그컵 2종 세트", "김*연 · 오늘 09:12"], tag: "문의",
                         action: .perform("답변 쓰기")),
                WorkItem(title: "주말 클래스에 주차할 수 있나요?", status: Status(text: "답변 대기", tone: .attention),
                         lines: ["Instagram DM · 주말 도자기 클래스", "박*은 · 오늘 08:40"], tag: "문의",
                         action: .perform("답변 쓰기")),
                WorkItem(title: "플레이트 다른 색도 있나요?", status: Status(text: "답변 대기", tone: .attention),
                         lines: ["네이버 스마트스토어 · 오롯 세라믹 플레이트", "정*우 · 어제 21:05"], tag: "문의",
                         action: .perform("답변 쓰기")),
                WorkItem(title: "주말 클래스 모집 글", status: Status(text: "초안 준비", tone: .progress),
                         lines: ["Instagram 게시물 · 비서가 작성", "남은 3자리를 알릴 홍보 글이에요."], tag: "콘텐츠",
                         action: .perform("홍보 글 검토하기")),
                WorkItem(title: "거북이 키링 이벤트 결과 글", status: Status(text: "초안 준비", tone: .progress),
                         lines: ["Instagram 게시물 · 비서가 작성", "당첨자 발표를 담은 글이에요."], tag: "콘텐츠",
                         action: .perform("홍보 글 검토하기")),
            ]
        }
    }
}

struct OperationAreaView: View {
    let area: OperationArea
    @State private var filter: String
    @State private var query = ""
    @State private var sort: String
    @State private var state = ScreenState.launch

    init(area: OperationArea, initialFilter: String? = nil) {
        self.area = area
        _filter = State(initialValue: initialFilter ?? area.filters[0])
        _sort = State(initialValue: area.sortOptions.first ?? "")
    }

    private var visibleItems: [WorkItem] {
        let filtered = area.items.filter { item in
            let matchesFilter = filter == area.filters[0] || item.tag == filter
            let matchesQuery = query.isEmpty
                || item.title.localizedStandardContains(query)
                || item.lines.contains { $0.localizedStandardContains(query) }
            return matchesFilter && matchesQuery
        }
        let isReversed = area.sortOptions.count > 1 && sort == area.sortOptions[1]
        return isReversed ? Array(filtered.reversed()) : filtered
    }

    private var primaryID: WorkItem.ID? {
        visibleItems.first { item in
            if case .perform = item.action { true } else { false }
        }?.id
    }

    var body: some View {
        Group {
            if state == .error {
                LoadErrorView { state = .loaded }
            } else if state == .empty {
                noDataView
            } else {
                list
                    .redacted(reason: state == .loading ? .placeholder : [])
                    .allowsHitTesting(state != .loading)
            }
        }
        .navigationTitle(area.title)
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .primaryAction) {
                toolbarAction
            }
        }
    }

    private var list: some View {
        List {
            Section {
                MetricStrip(metrics: area.metrics)
            }

            Section {
                Picker("상태", selection: $filter) {
                    ForEach(area.filters, id: \.self) { Text($0).tag($0) }
                }
                .adaptivePickerStyle()
                .accessibilityIdentifier("area.filter")
                .listRowInsets(EdgeInsets())
                .listRowBackground(Color.clear)
            }

            Section(area.listTitle) {
                if visibleItems.isEmpty {
                    emptyView
                } else {
                    ForEach(visibleItems) { item in
                        WorkCardRow(item: item, isPrimary: item.id == primaryID)
                    }
                }
            }
        }
        .listStyle(.insetGrouped)
        .searchable(text: $query, placement: .navigationBarDrawer(displayMode: .always), prompt: area.searchPrompt)
    }

    private var noDataView: some View {
        ContentUnavailableView {
            Label(area.noDataTitle, systemImage: area.systemImage)
        } description: {
            Text(keepingWords: area.noDataMessage)
        } actions: {
            if let action = area.noDataAction {
                NavigationLink {
                    PlaceholderScreen(title: action, systemImage: area.systemImage)
                } label: {
                    Text(action)
                        .foregroundStyle(Color(.systemBackground))
                }
                .buttonStyle(.borderedProminent)
                .controlSize(.large)
            }
        }
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
                if filter != area.filters[0] {
                    Button("전체 보기") {
                        filter = area.filters[0]
                    }
                    .buttonStyle(.bordered)
                    .controlSize(.large)
                }
            }
        }
    }

    @ViewBuilder
    private var toolbarAction: some View {
        switch area {
        case .bookings:
            NavigationLink {
                PlaceholderScreen(title: "예약 등록", systemImage: "calendar.badge.plus")
            } label: {
                Label("예약 등록", systemImage: "plus")
            }
        case .orders, .deliveries:
            Menu {
                Picker("정렬", selection: $sort) {
                    ForEach(area.sortOptions, id: \.self) { Text($0).tag($0) }
                }
                .pickerStyle(.inline)
            } label: {
                Label("정렬", systemImage: "arrow.up.arrow.down")
            }
        case .channels:
            NavigationLink("연결 관리") {
                PlaceholderScreen(title: "연결 관리", systemImage: "link")
            }
        }
    }
}

#Preview {
    NavigationStack {
        OperationAreaView(area: .bookings)
    }
}
