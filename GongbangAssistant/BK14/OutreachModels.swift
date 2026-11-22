import Foundation

nonisolated enum OutreachSignal: String, Codable, Hashable {
    case mobileOnlyContact = "mobile_only_contact"
    case proxyPurchase = "proxy_purchase"
    case marginOffer = "margin_offer"
    case sameDayPressure = "same_day_pressure"
    case prepayByOwner = "prepay_by_owner"

    var text: String {
        switch self {
        case .mobileOnlyContact: "받은 번호가 개인 휴대폰 하나뿐이에요"
        case .proxyPurchase: "특정 업체에서 물건을 대신 사 달래요"
        case .marginOffer: "수수료나 차액을 떼어 준대요"
        case .sameDayPressure: "답을 오늘 안에 달라고 서둘러요"
        case .prepayByOwner: "공방 쪽에서 돈부터 먼저 내라고 해요"
        }
    }
}

enum OutreachOrgType: String, Codable, CaseIterable, Identifiable, Hashable {
    case school, `public`, company, welfare, other, unknown

    var id: Self { self }

    var label: String {
        switch self {
        case .school: "학교"
        case .public: "공공기관"
        case .company: "회사"
        case .welfare: "복지기관"
        case .other: "기타 기관"
        case .unknown: "잘 모르겠어요"
        }
    }
}

enum OutreachVat: String, Codable, CaseIterable, Identifiable, Hashable {
    case unknown, included, excluded, exempt

    var id: Self { self }

    var label: String {
        switch self {
        case .unknown: "고르지 않았어요"
        case .included: "부가세 포함"
        case .excluded: "부가세 별도"
        case .exempt: "면세"
        }
    }
}

enum OutreachContact: String, Codable, Hashable {
    case landline, mobile, email, unknown

    var label: String {
        switch self {
        case .landline: "대표번호"
        case .mobile: "휴대폰"
        case .email: "이메일"
        case .unknown: "잘 모르겠어요"
        }
    }
}

enum OutreachQuoteStatus: String, Decodable, Hashable {
    case draft, sent, accepted, declined
    case followUp = "follow_up"
    case acceptedAdjusted = "accepted_adjusted"
    case noReply = "no_reply"

    var badge: Status {
        switch self {
        case .draft: Status(text: "작성 중", tone: .neutral)
        case .sent: Status(text: "보냄", tone: .progress)
        case .followUp: Status(text: "한 번 더 연락하기", tone: .attention)
        case .accepted, .acceptedAdjusted: Status(text: "수락", tone: .done)
        case .declined: Status(text: "거절", tone: .neutral)
        case .noReply: Status(text: "답이 없어요", tone: .neutral)
        }
    }
}

enum OutreachOutcome: String, Codable, CaseIterable, Identifiable, Hashable {
    case accepted
    case acceptedAdjusted = "accepted_adjusted"
    case declined
    case noReply = "no_reply"

    var id: Self { self }

    var label: String {
        switch self {
        case .accepted: "수락"
        case .acceptedAdjusted: "금액 조정하고 수락"
        case .declined: "거절"
        case .noReply: "답이 없어요"
        }
    }
}

struct OutreachExtraction: Decodable {
    struct Fields: Decodable {
        var orgType: OutreachOrgType
        var orgName: String?
        var headcount: Int?
        var headcountMax: Int?
        var budgetKrw: Int?
        var budgetVat: OutreachVat
        var date: String?
        var dateText: String?
        var timeRange: String?
        var locationText: String?
        var classHint: String?
        var contactKind: OutreachContact
    }

    enum Confidence: String, Decodable { case high, low }

    let fields: Fields
    let confidence: [String: Confidence]
    let signals: [OutreachSignal]
    let locked: Bool
    let error: String?
}

/// Inquiry fields after the owner checked them; the pasted text never travels with them.
struct OutreachFields: Codable, Hashable {
    var orgType: OutreachOrgType = .unknown
    var orgName: String?
    var budgetKrw: Int?
    var budgetVat: OutreachVat = .unknown
    var date: String?
    var dateText: String?
    var timeRange: String?
    var locationText: String?
    var classHint: String?
    var contactKind: OutreachContact = .unknown
}

struct OutreachInputs: Decodable, Hashable {
    let headcount: Int
    let perPersonKrw: Int?
    let assistants: Int
    let travelMinutes: Int?
    let distanceKm: Int?
}

struct OutreachCalculation: Decodable, Hashable {
    struct Line: Decodable, Hashable, Identifiable {
        let key: String
        let label: String
        let amountKrw: Int?
        let formula: String
        var id: String { key }
    }

    struct Tier: Decodable, Hashable, Identifiable {
        let headcount: Int
        let perPersonKrw: Int
        var id: Int { headcount }
    }

    enum Verdict: String, Decodable { case better, worse, unknown }
    enum Suggestion: String, Decodable { case accept, raise, decline, unknown }

    let lines: [Line]
    let totalKrw: Int
    let perPersonKrw: Int
    let instructorGapKrw: Int
    let outreachMinutes: Int
    let travelUnknown: Bool
    let netPerPersonOutreach: Int?
    let netPerPersonOneday: Int?
    let netPerHourOutreach: Int?
    let netPerHourOneday: Int?
    let verdict: Verdict
    let suggestion: Suggestion
    let breakEvenHeadcount: Int?
    let maxHeadcount: Int?
    let neededTotalKrw: Int?
    let tierPrices: [Tier]
    let outreachBasis: String
    let onedayBasis: String
}

struct OutreachQuote: Decodable, Hashable, Identifiable {
    struct Conflict: Decodable, Hashable, Identifiable {
        let sessionId: String
        let title: String
        let startsAt: String
        let bookedCount: Int
        let lostKrw: Int?
        var id: String { sessionId }

        var time: String {
            (try? Date(startsAt, strategy: .iso8601)).map { $0.formatted(OutreachFormat.clock) } ?? ""
        }
    }

    let id: String
    let status: OutreachQuoteStatus
    let classId: String
    let fields: OutreachFields
    let inputs: OutreachInputs
    let signals: [OutreachSignal]
    let locked: Bool
    let orgVerifiedAt: String?
    let calculation: OutreachCalculation
    let missingCosts: [String]
    let conflicts: [Conflict]
    let summary: String
    let replyDraft: String
    let changeDeadline: String?
    let followUpAt: String
    let followUpDue: CardDue?
    let outcome: OutreachOutcome?
    let finalTotalKrw: Int?

    var title: String { fields.orgName ?? "\(fields.orgType == .unknown ? "기관" : fields.orgType.label) 출장 수업" }
}

struct OutreachQuoteRow: Decodable, Hashable, Identifiable {
    let id: String
    let status: OutreachQuoteStatus
    let title: String
    let detail: String
    let totalKrw: Int
    let followUpDue: CardDue?
}

struct OutreachClassCost: Decodable, Hashable, Identifiable {
    let classId: String
    let title: String
    let classMinutes: Int
    let materialPerPersonKrw: Int?
    let onedayPriceKrw: Int?
    let prepMinutes: Int
    let cleanupMinutes: Int
    let maxHeadcount: Int

    var id: String { classId }
    var isMissing: Bool { materialPerPersonKrw == nil || onedayPriceKrw == nil }
}

enum OutreachTravelMode: String, Codable, CaseIterable, Identifiable, Hashable {
    case flat
    case perKm = "per_km"

    var id: Self { self }
    var label: String { self == .flat ? "한 번에 정해진 금액" : "1km마다" }
}

struct OutreachDefaults: Codable, Hashable {
    var instructorHourlyKrw: Int
    var assistantDailyKrw: Int
    var travelMode: OutreachTravelMode
    var travelPerKmKrw: Int
    var travelFlatKrw: Int
    var minimumFeeKrw: Int
}

struct OutreachCostSettings: Decodable {
    let classes: [OutreachClassCost]
    let defaults: OutreachDefaults?
}

enum OutreachFormat {
    private static var seoul: TimeZone { Calendar.workshop.timeZone }

    static var clock: Date.VerbatimFormatStyle {
        Date.VerbatimFormatStyle(
            format: "\(hour: .twoDigits(clock: .twentyFourHour, hourCycle: .zeroBased)):\(minute: .twoDigits)",
            timeZone: seoul, calendar: .workshop)
    }

    static func won(_ value: Int) -> String { "\(value.formatted(.number.grouping(.automatic)))원" }
    static func won(_ value: Int?) -> String { value.map { won($0) } ?? "잘 모르겠어요" }

    /// "2026-12-05" and "14:00" as one moment in workshop time.
    static func moment(day: String, clock: String = "00:00") -> Date? {
        let parts = day.split(separator: "-").compactMap { Int($0) }
        let time = clock.split(separator: ":").compactMap { Int($0) }
        guard parts.count == 3, time.count == 2 else { return nil }
        return Calendar.workshop.date(from: DateComponents(
            year: parts[0], month: parts[1], day: parts[2], hour: time[0], minute: time[1]))
    }

    static func dayText(_ day: String) -> String {
        guard let date = moment(day: day) else { return day }
        var style = Date.FormatStyle(locale: Locale(identifier: "ko_KR"), calendar: .workshop, timeZone: seoul)
        style = style.year().month().day().weekday()
        return date.formatted(style)
    }
}
