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
        case .bookings: "24건"
        case .orders: "8건"
        case .deliveries: "5건"
        case .channels: "2개"
        }
    }

    var systemImage: String {
        switch self {
        case .bookings: "calendar.badge.checkmark"
        case .orders: "bag"
        case .deliveries: "shippingbox"
        case .channels: "bubble.left.and.text.bubble.right"
        }
    }

    var metrics: [Metric] {
        switch self {
        case .bookings:
            [Metric(value: "32건", label: "전체"), Metric(value: "24건", label: "확정"), Metric(value: "2건", label: "예약금 대기")]
        case .orders:
            [Metric(value: "38건", label: "전체 주문"), Metric(value: "8건", label: "처리 대기"), Metric(value: "126만원", label: "이번 달 매출")]
        case .deliveries:
            [Metric(value: "5건", label: "발송 예정"), Metric(value: "12건", label: "배송 중"), Metric(value: "21건", label: "배송 완료")]
        case .channels:
            [Metric(value: "2개", label: "연결 채널"), Metric(value: "3건", label: "미답변 문의"), Metric(value: "2건", label: "홍보 초안")]
        }
    }

    var filters: [String] {
        switch self {
        case .bookings: ["전체 32", "확정 24", "예약금 대기 2"]
        case .orders: ["전체 38", "결제 완료 8", "처리 중 5"]
        case .deliveries: ["발송 예정 5", "배송 중 12", "완료 21"]
        case .channels: ["전체", "채널 현황", "문의·콘텐츠"]
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

    var items: [WorkItem] {
        switch self {
        case .bookings:
            [
                WorkItem(title: "도자기 원데이 클래스", status: "확정",
                         lines: ["11.04 수 · 10:00–11:30", "김*연 외 3명 · 예약금 확인 완료"], action: "예약 상세 보기"),
                WorkItem(title: "나만의 머그컵 만들기", status: "예약금 대기",
                         lines: ["11.05 목 · 14:00–16:00", "박*은 · 2명 · 입금 기한 오늘 18:00"], action: "입금 내역 확인"),
                WorkItem(title: "주말 도자기 클래스", status: "확정",
                         lines: ["11.07 토 · 10:00–12:00", "이*진 외 5명 · 잔여석 3자리"], action: "회차 관리하기"),
            ]
        case .orders:
            [
                WorkItem(title: "머그컵 2종 세트", status: "결제 완료",
                         lines: ["#1042 · 11.04 주문 · 네이버 스토어", "김*연 · 1개 · 42,000원"], action: "주문 확인하기"),
                WorkItem(title: "오롯 세라믹 플레이트", status: "처리 중",
                         lines: ["#1043 · 11.04 주문 · 네이버 스토어", "이*진 · 2개 · 56,000원"], action: "주문 상세 보기"),
                WorkItem(title: "핸드메이드 미니 화병", status: "결제 완료",
                         lines: ["#1044 · 11.04 주문 · 네이버 스토어", "정*우 · 1개 · 28,000원"], action: "주문 확인하기"),
            ]
        case .deliveries:
            [
                WorkItem(title: "머그컵 2종 세트", status: "포장 대기",
                         lines: ["#1042 · 김*연 · 1개", "오늘 16:00 집하 · 완충 포장 필요"], action: "포장 완료로 변경"),
                WorkItem(title: "오롯 세라믹 플레이트", status: "송장 대기",
                         lines: ["#1043 · 이*진 · 2개", "포장 완료 · 오늘 발송 예정"], action: "송장 등록하기"),
                WorkItem(title: "핸드메이드 커피잔", status: "배송 중",
                         lines: ["#1038 · 최*서 · 1개", "택배사 인계 완료 · 내일 도착 예정"], action: "배송 상세 보기"),
            ]
        case .channels:
            [
                WorkItem(title: "Instagram", status: "연결됨",
                         lines: ["@orot.studio · 팔로워 1,284", "이번 주 +24 · 게시물 초안 2건"], action: "콘텐츠 관리하기"),
                WorkItem(title: "네이버 스마트스토어", status: "연결됨",
                         lines: ["오롯 공방 · 이번 달 주문 38건", "상품 문의 3건 · 리뷰 답글 대기 2건"], action: "문의·리뷰 확인"),
                WorkItem(title: "주말 클래스 모집 글", status: "초안 준비",
                         lines: ["Instagram 게시물 · 비서가 작성", "남은 3자리를 알릴 홍보 글이에요."], action: "홍보 초안 검토"),
            ]
        }
    }
}

struct OperationAreaView: View {
    let area: OperationArea
    @State private var filter: String
    @State private var query = ""

    init(area: OperationArea) {
        self.area = area
        _filter = State(initialValue: area.filters[0])
    }

    var body: some View {
        List {
            Section {
                MetricStrip(metrics: area.metrics)
            }

            Section {
                Picker("상태", selection: $filter) {
                    ForEach(area.filters, id: \.self) { Text($0).tag($0) }
                }
                .pickerStyle(.segmented)
                .listRowInsets(EdgeInsets())
                .listRowBackground(Color.clear)
            }

            Section(area.listTitle) {
                ForEach(area.items) { WorkCard(item: $0) }
            }
        }
        .listStyle(.insetGrouped)
        .navigationTitle(area.title)
        .navigationBarTitleDisplayMode(.inline)
        .searchable(text: $query, placement: .navigationBarDrawer(displayMode: .always), prompt: area.searchPrompt)
        .toolbar {
            ToolbarItem(placement: .primaryAction) {
                switch area {
                case .bookings:
                    Button("예약 등록", systemImage: "plus") {}
                case .orders:
                    Menu("정렬", systemImage: "arrow.up.arrow.down") {
                        Button("최근 주문순") {}
                    }
                case .deliveries:
                    Menu("정렬", systemImage: "arrow.up.arrow.down") {
                        Button("마감 임박순") {}
                    }
                case .channels:
                    Button("연결 관리", systemImage: "link") {}
                }
            }
        }
    }
}

#Preview {
    NavigationStack {
        OperationAreaView(area: .bookings)
    }
}
