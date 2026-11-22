import Foundation

/// Whether the server has a slot for the service today.
enum ConnectionAvailability {
    /// PUT /connections/{id} stores a value. A stored value never means connected.
    case savable
    /// Nothing can be stored yet; the row says what will be possible.
    case planned
}

/// What the owner may type for one savable service. The device checks it before anything is sent, with the rules
/// the server applies, so the owner reads the exact reason instead of the transport's general 422 line.
struct ConnectionFormat {
    /// A bare id such as an Instagram handle.
    struct IDRule {
        let allowed: String
        let length: ClosedRange<Int>
        /// Instagram handles are often typed with a leading @.
        let dropsAtSign: Bool
        let hint: String

        func problem(in raw: String) -> String? {
            let value = raw.lowercased()
            guard length.contains(value.count), value.allSatisfy({ allowed.contains($0) }) else { return hint }
            return nil
        }
    }

    /// Hosts an https address may use, each with the path its address must go beyond.
    let hosts: [String: String]
    let id: IDRule?
    let placeholder: String
    let examples: [String]
}

/// One service worth linking for a small craft workshop.
struct ConnectionService: Identifiable {
    /// The /connections service key, or a local key for a planned service.
    let id: String
    let name: String
    let symbol: String
    /// What the service brings into the app, in one sentence.
    let brings: String
    /// What the owner must give.
    let needs: String
    /// What is true today, said plainly.
    let today: String
    /// The source in GET /collectors/status that can prove collection; nil when the server has no collector for it.
    var collectorSource: String?
    /// nil for a planned service.
    var format: ConnectionFormat?

    var availability: ConnectionAvailability { format == nil ? .planned : .savable }
}

extension ConnectionService {
    /// The server stores at most this many characters.
    static let maxLength = 200

    /// Says in Korean what is wrong with a typed value, or nothing when it can be sent.
    func problem(in raw: String) -> String? {
        guard let format else { return "이 서비스는 아직 저장이 안 돼요." }
        let value = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        if value.isEmpty { return "빈칸부터 채워 주세요." }
        if value.count > Self.maxLength { return "\(Self.maxLength)자 넘게는 못 넣어요." }
        if value.contains(where: \.isWhitespace) { return "띄우지 말고 붙여서 넣어 주세요." }
        guard value.contains("/") else {
            guard let rule = format.id else { return "주소창 맨 앞이 https://인 링크만 받아요. 복사해서 넣어 보세요." }
            return rule.problem(in: rule.dropsAtSign && value.hasPrefix("@") ? String(value.dropFirst()) : value)
        }
        guard value.lowercased().hasPrefix("https://") else { return "주소창 맨 앞이 https://인 링크만 받아요. 복사해서 넣어 보세요." }
        guard let parts = URLComponents(string: value), let host = parts.host?.lowercased() else {
            return "링크에 오타가 없는지 봐 주세요."
        }
        if parts.port != nil || parts.user != nil || parts.password != nil {
            return "포트 번호나 아이디·비밀번호가 섞인 링크는 보관하지 않아요."
        }
        guard let prefix = format.hosts[host] else {
            return "\(format.hosts.keys.sorted().joined(separator: ", ")) 링크만 받아요."
        }
        let path = parts.path
        guard path.hasPrefix(prefix), path.count > prefix.count else {
            return "링크가 다 들어가지 않은 것 같아요. 예시 \(format.examples.last ?? "")"
        }
        guard let rule = format.id else { return nil }
        return rule.problem(in: path.split(separator: "/").first.map(String.init) ?? "")
    }
}

/// Every service the app names, savable ones first. Sentences state what the server does today; nothing here
/// promises collection, because only GET /collectors/status can show it.
enum ConnectionCatalog {
    private static let untilCollecting = "아직은 입력값만 보관하는 단계예요. 실제로 불러오기 시작하면 상태 표시도 가져오는 중으로 달라져요."
    private static let notBuilt = "지금은 없는 기능이에요."

    static let all: [ConnectionService] = [
        ConnectionService(
            id: "instagram", name: "인스타그램", symbol: "camera",
            brings: "피드 게시물과 댓글을 읽어 뒀다가 손님 질문에 답하거나 글감을 고를 때 참고해요.",
            needs: "인스타 아이디", today: untilCollecting, collectorSource: "instagram",
            format: ConnectionFormat(
                hosts: ["www.instagram.com": "/"],
                id: .init(allowed: "abcdefghijklmnopqrstuvwxyz0123456789._", length: 1...30, dropsAtSign: true,
                          hint: "영어 글자·숫자·마침표·밑줄로 30자 안에서 넣어 보세요."),
                placeholder: "my_workshop",
                examples: ["my_workshop", "https://www.instagram.com/my_workshop/"])),
        ConnectionService(
            id: "naver_smartstore", name: "네이버 스마트스토어", symbol: "bag",
            brings: "스마트스토어로 들어온 주문과 상품 질문이 앱 안 주문 관리·문의 목록에 같이 떠요.",
            needs: "스마트스토어 링크", today: untilCollecting, collectorSource: "naver_smartstore",
            format: ConnectionFormat(
                hosts: ["smartstore.naver.com": "/", "m.smartstore.naver.com": "/", "brand.naver.com": "/"],
                id: nil, placeholder: "https://smartstore.naver.com/",
                examples: ["https://smartstore.naver.com/myworkshop"])),
        ConnectionService(
            id: "naver_blog", name: "네이버 블로그", symbol: "doc.text",
            brings: "블로그 새 글을 읽어 두고 채널 현황과 글감 고를 때 참고해요.",
            needs: "블로그 아이디", today: untilCollecting, collectorSource: "naver_blog",
            format: ConnectionFormat(
                hosts: ["blog.naver.com": "/", "m.blog.naver.com": "/"],
                id: .init(allowed: "abcdefghijklmnopqrstuvwxyz0123456789_-", length: 2...40, dropsAtSign: false,
                          hint: "영어 글자·숫자·밑줄(_)·붙임표(-)로 2~40자 사이로 넣어 보세요."),
                placeholder: "myworkshop",
                examples: ["myworkshop", "https://blog.naver.com/myworkshop"])),
        ConnectionService(
            id: "naver_booking", name: "네이버 예약", symbol: "calendar.badge.clock",
            brings: "손님께 예약 안내할 때 쓰도록 예약 페이지 링크를 보관해 둬요.",
            needs: "예약 페이지 링크",
            today: "여기엔 링크만 둬요. 네이버 쪽에서 예약 내역을 바깥 앱에 내주지 않아서 예약은 사장님이 손으로 넣으셔야 해요.",
            collectorSource: "naver_booking",
            format: ConnectionFormat(
                hosts: ["booking.naver.com": "/", "m.booking.naver.com": "/"],
                id: nil, placeholder: "https://booking.naver.com/",
                examples: ["https://booking.naver.com/booking/6/bizes/123456"])),
        ConnectionService(
            id: "naver_place", name: "네이버 플레이스", symbol: "mappin.and.ellipse",
            brings: "오시는 길 알려 줄 때 쓰려고 공방 위치·영업 정보 페이지를 넣어 둬요.",
            needs: "플레이스 링크", today: "리뷰 불러오기는 아직 안 돼요. 지금은 플레이스 링크만 갖고 있어요.",
            format: ConnectionFormat(
                hosts: ["map.naver.com": "/", "m.place.naver.com": "/", "pcmap.place.naver.com": "/", "naver.me": "/"],
                id: nil, placeholder: "https://naver.me/",
                examples: ["https://naver.me/abcd1234", "https://m.place.naver.com/place/123456"])),
        ConnectionService(
            id: "kakao_channel", name: "카카오톡 채널", symbol: "message",
            brings: "문의 안내에 쓰려고 채널 채팅 주소를 넣어 둬요.",
            needs: "채널 링크",
            today: "여기엔 링크만 둬요. 카카오가 바깥 앱에 채널 채팅을 내주지 않아서 대화 내용은 옮겨 올 방법이 없어요.",
            format: ConnectionFormat(
                hosts: ["pf.kakao.com": "/_"],
                id: nil, placeholder: "https://pf.kakao.com/_",
                examples: ["https://pf.kakao.com/_abcde"])),
        ConnectionService(
            id: "google_maps", name: "구글 지도", symbol: "map",
            brings: "외국인 손님께 길 알려 줄 때 쓰려고 구글 지도 주소를 넣어 둬요.",
            needs: "지도 공유 링크", today: "리뷰 불러오기는 아직 안 돼요. 지금은 플레이스 링크만 갖고 있어요.",
            format: ConnectionFormat(
                hosts: ["maps.app.goo.gl": "/", "maps.google.com": "", "www.google.com": "/maps", "google.com": "/maps"],
                id: nil, placeholder: "https://maps.app.goo.gl/",
                examples: ["https://maps.app.goo.gl/AbCdEf123"])),
        ConnectionService(
            id: "naver_talktalk", name: "네이버 톡톡", symbol: "ellipsis.bubble",
            brings: "톡톡으로 온 손님 질문은 문의함 한곳에 쌓여요.",
            needs: "준비물: 챗봇 API 신청서 (톡톡 파트너센터에서 접수)",
            today: "톡톡 문의를 받아 오는 기능은 아직 없어요. 지금은 톡톡 앱에서 봐 주세요.",
            collectorSource: "naver_talktalk"),
        ConnectionService(
            id: "courier_file", name: "택배사 송장 파일", symbol: "shippingbox",
            brings: "택배사가 준 엑셀 송장 파일을 올리면 배송 목록 번호 칸이 한꺼번에 채워져요.",
            needs: "송장 파일 (택배사 프로그램에서 내보낸 것)",
            today: "파일 읽기는 \(notBuilt) 그때까지는 송장번호를 복사해 붙이시거나 카메라로 바코드를 비추면 돼요."),
        ConnectionService(
            id: "calendar", name: "캘린더", symbol: "calendar",
            brings: "사장님 개인 약속과 수업이 캘린더에 같이 보여요.",
            needs: "아이폰 캘린더 보기 허용",
            today: "\(notBuilt) 비공개 캘린더 링크는 알기만 해도 누구나 일정을 볼 수 있어서 안 받을게요."),
        ConnectionService(
            id: "bank_deposit", name: "통장 입금 문자", symbol: "wonsign.circle",
            brings: "입금 문자가 오면 예약금 기다리는 예약과 대조해 입금 확인 요청을 띄워요.",
            needs: "통장 입금 알림 문자",
            today: "\(notBuilt) 앞으로도 통장 비밀번호와 공동인증서는 절대 묻지 않을게요."),
        ConnectionService(
            id: "kakao_alimtalk", name: "카카오 알림톡 보내기", symbol: "bell",
            brings: "예약이 확정됐을 때와 수업 하루 전에 손님께 카카오 알림톡이 자동으로 가요.",
            needs: "준비물: 카카오 비즈니스 채널, 그 채널의 발신 프로필", today: notBuilt),
        ConnectionService(
            id: "idus", name: "아이디어스", symbol: "gift",
            brings: "아이디어스 작품 주문과 손님 질문도 주문 관리 탭에서 봐요.",
            needs: "아이디어스 작가 페이지 링크", today: notBuilt),
        ConnectionService(
            id: "class_platform", name: "솜씨당·프립 같은 클래스 앱", symbol: "person.2",
            brings: "솜씨당·프립 같은 클래스 앱에서 들어온 예약도 예약 탭 하나로 모아 볼 수 있어요.",
            needs: "클래스 앱 예약 내역", today: "\(notBuilt) 그때까지는 예약을 손으로 넣어 주세요."),
        ConnectionService(
            id: "daangn", name: "당근 비즈프로필", symbol: "house",
            brings: "당근에서 동네 손님이 보낸 질문과 소식 글을 한데 모아요.",
            needs: "당근 비즈프로필 링크", today: notBuilt),
    ]

    /// The order for one kind of workshop. `key` is BusinessType's raw value; an unknown or empty key keeps the
    /// catalogue order, which is also the order the server lists services in.
    static func ordered(forBusinessType key: String) -> [ConnectionService] {
        let lowered = key.lowercased()
        let first: [String]
        if ["class", "lesson"].contains(where: lowered.contains) {
            first = ["naver_booking", "instagram", "naver_place", "kakao_channel", "class_platform"]
        } else if ["goods", "product", "shop", "store", "sale"].contains(where: lowered.contains) {
            first = ["naver_smartstore", "instagram", "naver_blog", "kakao_channel", "idus", "courier_file"]
        } else {
            return all
        }
        let lead = first.compactMap { id in all.first { $0.id == id } }
        return lead + all.filter { !first.contains($0.id) }
    }
}
