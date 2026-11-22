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
        guard let format else { return "아직 저장할 수 없는 서비스예요." }
        let value = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        if value.isEmpty { return "값을 입력해 주세요." }
        if value.count > Self.maxLength { return "\(Self.maxLength)자까지 저장할 수 있어요." }
        if value.contains(where: \.isWhitespace) { return "띄어쓰기 없이 입력해 주세요." }
        guard value.contains("/") else {
            guard let rule = format.id else { return "https://로 시작하는 주소를 붙여 넣어 주세요." }
            return rule.problem(in: rule.dropsAtSign && value.hasPrefix("@") ? String(value.dropFirst()) : value)
        }
        guard value.lowercased().hasPrefix("https://") else { return "https://로 시작하는 주소를 붙여 넣어 주세요." }
        guard let parts = URLComponents(string: value), let host = parts.host?.lowercased() else {
            return "주소를 다시 확인해 주세요."
        }
        if parts.port != nil || parts.user != nil || parts.password != nil {
            return "포트 번호나 로그인 정보가 든 주소는 저장할 수 없어요."
        }
        guard let prefix = format.hosts[host] else {
            return "\(format.hosts.keys.sorted().joined(separator: ", ")) 주소만 저장할 수 있어요."
        }
        let path = parts.path
        guard path.hasPrefix(prefix), path.count > prefix.count else {
            return "주소가 끝까지 입력되지 않았어요. 예: \(format.examples.last ?? "")"
        }
        guard let rule = format.id else { return nil }
        return rule.problem(in: path.split(separator: "/").first.map(String.init) ?? "")
    }
}

/// Every service the app names, savable ones first. Sentences state what the server does today; nothing here
/// promises collection, because only GET /collectors/status can show it.
enum ConnectionCatalog {
    private static let untilCollecting = "지금은 값만 저장해요. 수집이 시작되면 수집 중으로 바뀌어요."
    private static let notBuilt = "아직 만들지 않았어요."

    static let all: [ConnectionService] = [
        ConnectionService(
            id: "instagram", name: "인스타그램", symbol: "camera",
            brings: "게시물과 댓글을 모아 문의 답변과 글감 추천에 써요.",
            needs: "계정 이름", today: untilCollecting, collectorSource: "instagram",
            format: ConnectionFormat(
                hosts: ["www.instagram.com": "/"],
                id: .init(allowed: "abcdefghijklmnopqrstuvwxyz0123456789._", length: 1...30, dropsAtSign: true,
                          hint: "영문, 숫자, 마침표, 밑줄로 30자까지 입력해 주세요."),
                placeholder: "my_workshop",
                examples: ["my_workshop", "https://www.instagram.com/my_workshop/"])),
        ConnectionService(
            id: "naver_smartstore", name: "네이버 스마트스토어", symbol: "bag",
            brings: "주문과 상품 문의를 주문 관리와 문의로 가져와요.",
            needs: "스토어 주소", today: untilCollecting, collectorSource: "naver_smartstore",
            format: ConnectionFormat(
                hosts: ["smartstore.naver.com": "/", "m.smartstore.naver.com": "/", "brand.naver.com": "/"],
                id: nil, placeholder: "https://smartstore.naver.com/",
                examples: ["https://smartstore.naver.com/myworkshop"])),
        ConnectionService(
            id: "naver_blog", name: "네이버 블로그", symbol: "doc.text",
            brings: "새 글을 읽어 콘텐츠 현황과 글감 추천에 써요.",
            needs: "블로그 아이디", today: untilCollecting, collectorSource: "naver_blog",
            format: ConnectionFormat(
                hosts: ["blog.naver.com": "/", "m.blog.naver.com": "/"],
                id: .init(allowed: "abcdefghijklmnopqrstuvwxyz0123456789_-", length: 2...40, dropsAtSign: false,
                          hint: "영문, 숫자, 밑줄, 붙임표로 2자에서 40자까지 입력해 주세요."),
                placeholder: "myworkshop",
                examples: ["myworkshop", "https://blog.naver.com/myworkshop"])),
        ConnectionService(
            id: "naver_booking", name: "네이버 예약", symbol: "calendar.badge.clock",
            brings: "예약 페이지 주소를 예약 안내에 쓸 수 있게 보관해요.",
            needs: "예약 페이지 주소",
            today: "지금은 주소만 저장해요. 네이버가 예약 내역을 읽는 길을 공개하지 않아 예약은 직접 등록해요.",
            collectorSource: "naver_booking",
            format: ConnectionFormat(
                hosts: ["booking.naver.com": "/", "m.booking.naver.com": "/"],
                id: nil, placeholder: "https://booking.naver.com/",
                examples: ["https://booking.naver.com/booking/6/bizes/123456"])),
        ConnectionService(
            id: "naver_place", name: "네이버 플레이스", symbol: "mappin.and.ellipse",
            brings: "공방 위치와 영업 정보 페이지를 오시는 길 안내에 쓸 수 있게 보관해요.",
            needs: "플레이스 주소", today: "지금은 주소만 저장해요. 리뷰는 아직 가져오지 않아요.",
            format: ConnectionFormat(
                hosts: ["map.naver.com": "/", "m.place.naver.com": "/", "pcmap.place.naver.com": "/", "naver.me": "/"],
                id: nil, placeholder: "https://naver.me/",
                examples: ["https://naver.me/abcd1234", "https://m.place.naver.com/place/123456"])),
        ConnectionService(
            id: "kakao_channel", name: "카카오톡 채널", symbol: "message",
            brings: "채널 채팅 주소를 문의 안내에 쓸 수 있게 보관해요.",
            needs: "채널 주소",
            today: "지금은 주소만 저장해요. 카카오가 채널 대화 읽기를 열어 두지 않아 대화는 가져오지 못해요.",
            format: ConnectionFormat(
                hosts: ["pf.kakao.com": "/_"],
                id: nil, placeholder: "https://pf.kakao.com/_",
                examples: ["https://pf.kakao.com/_abcde"])),
        ConnectionService(
            id: "google_maps", name: "구글 지도", symbol: "map",
            brings: "구글 지도 주소를 외국인 손님 길 안내에 쓸 수 있게 보관해요.",
            needs: "지도 공유 주소", today: "지금은 주소만 저장해요. 리뷰는 아직 가져오지 않아요.",
            format: ConnectionFormat(
                hosts: ["maps.app.goo.gl": "/", "maps.google.com": "", "www.google.com": "/maps", "google.com": "/maps"],
                id: nil, placeholder: "https://maps.app.goo.gl/",
                examples: ["https://maps.app.goo.gl/AbCdEf123"])),
        ConnectionService(
            id: "naver_talktalk", name: "네이버 톡톡", symbol: "ellipsis.bubble",
            brings: "톡톡 문의를 문의함으로 모아요.",
            needs: "톡톡 파트너센터의 챗봇 API 신청",
            today: "톡톡은 문의가 올 때 서버로 보내 주는 방식인데 받는 창구를 아직 만들지 않았어요.",
            collectorSource: "naver_talktalk"),
        ConnectionService(
            id: "courier_file", name: "택배사 프로그램 파일", symbol: "shippingbox",
            brings: "송장 파일을 올리면 배송 관리의 송장 번호를 한 번에 채워요.",
            needs: "택배사 프로그램에서 내려받은 송장 파일",
            today: "파일 읽기는 \(notBuilt) 지금은 송장 번호를 붙여 넣거나 바코드로 읽어요."),
        ConnectionService(
            id: "calendar", name: "캘린더", symbol: "calendar",
            brings: "개인 일정과 수업 일정을 한 화면에서 봐요.",
            needs: "기기 캘린더 접근 허용",
            today: "\(notBuilt) 비공개 캘린더 주소는 비밀번호와 같아서 받지 않아요."),
        ConnectionService(
            id: "bank_deposit", name: "계좌 입금 알림", symbol: "wonsign.circle",
            brings: "입금 알림을 예약금 대기와 맞춰 입금 확인을 제안해요.",
            needs: "은행 입금 알림",
            today: "\(notBuilt) 계좌 비밀번호나 인증서는 앞으로도 받지 않아요."),
        ConnectionService(
            id: "kakao_alimtalk", name: "카카오 알림톡", symbol: "bell",
            brings: "예약 확정과 수업 전날 안내를 알림톡으로 보내요.",
            needs: "카카오 비즈니스 채널과 발신 프로필", today: notBuilt),
        ConnectionService(
            id: "idus", name: "아이디어스", symbol: "gift",
            brings: "작품 주문과 문의를 주문 관리로 모아요.",
            needs: "작가 스토어 주소", today: notBuilt),
        ConnectionService(
            id: "class_platform", name: "클래스 플랫폼", symbol: "person.2",
            brings: "솜씨당이나 프립에서 받은 수업 예약을 예약 관리로 모아요.",
            needs: "플랫폼 예약 내역", today: "\(notBuilt) 지금은 예약을 직접 등록해요."),
        ConnectionService(
            id: "daangn", name: "당근 비즈프로필", symbol: "house",
            brings: "동네 손님 문의와 소식 글을 모아요.",
            needs: "비즈프로필 주소", today: notBuilt),
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
