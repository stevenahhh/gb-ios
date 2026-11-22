import Foundation

struct BK06Rule: Codable, Hashable {
    var daysBefore: Int
    var refundPercent: Int?
    var deductMaterial = false
    var carryOverAllowed = false
    var note = ""

    var dayText: String { daysBefore == 0 ? "당일" : "\(daysBefore)일 전까지" }

    var outcomeText: String {
        switch refundPercent {
        case nil: "정하지 않음"
        case 0: "환불 없음"
        case 100: "전액 환불"
        case let percent?: "\(percent)% 환불"
        }
    }

    var extrasText: String {
        [deductMaterial ? "재료비 공제" : nil, carryOverAllowed ? "이월 가능" : nil].compactMap { $0 }
            .joined(separator: " · ")
    }
}

struct BK06LateRule: Codable, Hashable {
    var lateMinutes: Int
    var note: String
}

struct BK06PolicyDraft: Decodable {
    let rules: [BK06Rule]
    let late: BK06LateRule?
    let unread: [String]
    let source: String
}

struct BK06PolicyVersion: Decodable, Identifiable, Hashable {
    let version: Int
    let approvedAt: String
    let rules: [BK06Rule]
    let late: BK06LateRule?
    let unread: [String]
    let change: String
    let summary: String
    var id: Int { version }
}

struct BK06Notice: Decodable {
    let version: Int
    let summary: String
}

enum BK06MessageKind: String, Decodable { case cancel, change, question }

struct BK06Candidate: Decodable, Identifiable, Hashable {
    let bookingId: String
    let customerName: String
    let classTitle: String
    let sessionStartsAt: String
    let seats: Int
    let paid: Int
    var id: String { bookingId }
}

struct BK06Intake: Decodable {
    let kind: BK06MessageKind
    let reasonCategory: String?
    let candidates: [BK06Candidate]
    let recent: [BK06Candidate]
}

enum BK06Decision: String, Codable, CaseIterable, Identifiable {
    case byRule = "by_rule"
    case carryOver = "carry_over"
    case fullRefund = "full_refund"
    case custom

    var id: Self { self }
    var title: String {
        switch self {
        case .byRule: "규정대로"
        case .carryOver: "1회 이월"
        case .fullRefund: "전액 환불"
        case .custom: "직접 정하기"
        }
    }
}

struct BK06Precedent: Decodable, Identifiable {
    let caseId: String
    let decidedAt: String
    let reason: String
    let decision: BK06Decision
    var id: String { caseId }
}

enum BK06Warning: String, Decodable {
    case noNotice = "no_notice"
    case noPolicy = "no_policy"
    case undecidedRule = "undecided_rule"
    case unreadRule = "unread_rule"
    case materialUnknown = "material_unknown"
    case naverBooking = "naver_booking"

    var text: String {
        switch self {
        case .noNotice: "이 손님에게 안내한 규정 기록이 없어요. 지금 규정으로 계산했어요."
        case .noPolicy: "규정을 먼저 정해 두면 금액을 계산해 드려요."
        case .undecidedRule: "규정에 정하지 않은 조건이에요. 사장님이 판단해 주세요."
        case .unreadRule: "규정에 아직 확인하지 않은 문장이 있어 금액을 정하지 않았어요. 문장을 확인한 뒤 다시 저장해 주세요."
        case .materialUnknown: "재료비가 적혀 있지 않아 공제 금액을 계산하지 못했어요."
        case .naverBooking: "네이버 예약으로 들어온 예약이에요. 네이버에 설정한 환불 기준을 먼저 확인해 주세요."
        }
    }
}

struct BK06Quote: Decodable {
    let bookingId: String
    let revision: Int
    let customerName: String
    let classTitle: String
    let sessionStartsAt: String
    let policyVersion: Int?
    let noticedAt: String?
    let daysLeft: Int
    let paid: Int
    let refund: Int?
    let matchedLabel: String?
    let precedents: [BK06Precedent]
    let warnings: [BK06Warning]
    let unread: [String]
}

struct BK06DecisionResult: Decodable {
    let caseId: String
    let draft: String
    let refund: Int
    let seatOpened: Bool
    let sessionId: String
}

struct BK06Draft: Decodable {
    let draft: String
    let source: String
}

struct BK06Case: Decodable, Identifiable {
    let caseId: String
    let bookingId: String?
    let customerName: String?
    let kind: String
    let decision: String?
    let reason: String
    let decidedAt: String
    var id: String { caseId }

    var title: String {
        let kindText = switch kind {
        case "no_show": "노쇼"
        case "under_min": "인원 미달"
        default: "취소"
        }
        let outcome = switch decision {
        case "run": "진행"
        case "merge": "합반"
        case "cancel": "회차 취소"
        case let value?: BK06Decision(rawValue: value)?.title
        case nil: String?.none
        }
        return [kindText, outcome].compactMap { $0 }.joined(separator: " · ")
    }
}

struct BK06Attendance: Decodable {
    let attendedAt: String?
    let noShowAt: String?
    let draft: String?
}

struct BK06LateCard: Decodable, Identifiable, Hashable {
    let bookingId: String
    let customerName: String
    let phone: String?
    let classTitle: String
    let startsAt: String
    let minutesLate: Int
    let draft: String
    var id: String { bookingId }
}

struct BK06Reminder: Decodable {
    let bookingId: String
    let customerName: String
    let fireAt: String
}

struct BK06RefillCard: Decodable, Identifiable {
    let sessionId: String
    let classTitle: String
    let startsAt: String
    let openSeats: Int
    let targetCount: Int
    let expired: Bool
    var id: String { sessionId }
}

struct BK06MergeOption: Decodable, Identifiable {
    let sessionId: String
    let classTitle: String
    let startsAt: String
    let openSeats: Int
    var id: String { sessionId }
}

struct BK06UnderMinCard: Decodable, Identifiable {
    let sessionId: String
    let className: String
    let startsAt: String
    let revision: Int
    let booked: Int
    let minSeats: Int
    let orderDeadline: String
    let materialWon: Int?
    let mergeCandidates: [BK06MergeOption]
    var id: String { sessionId }
}

struct BK06SessionLine: Decodable, Identifiable {
    let sessionId: String
    let classTitle: String
    let startsAt: String
    let schedule: String
    let booked: Int
    let capacity: Int
    var id: String { sessionId }
}

struct BK06Cards: Decodable {
    let policyVersion: Int?
    let late: [BK06LateCard]
    let refill: [BK06RefillCard]
    let underMin: [BK06UnderMinCard]
    let reminders: [BK06Reminder]
    let sessions: [BK06SessionLine]
}

struct BK06Guest: Decodable, Identifiable {
    let bookingId: String
    let customerName: String
    let people: Int
    let attendedAt: String?
    let noShowAt: String?
    let noticed: Bool
    var id: String { bookingId }
}

struct BK06RefillTarget: Decodable, Identifiable, Hashable {
    let entryId: String
    let name: String
    let source: String
    let draft: String
    var id: String { entryId }
    var sourceText: String { source == "waitlist" ? "대기 요청" : "보강 남음" }
}

struct BK06Refill: Decodable {
    let classTitle: String
    let startsAt: String
    let startsInMinutes: Int
    let openSeats: Int
    let targets: [BK06RefillTarget]
}

struct BK06SessionDetail: Decodable {
    let classTitle: String
    let startsAt: String
    let schedule: String
    let capacity: Int
    let booked: Int
    let minSeats: Int?
    let materialOrderDeadline: String?
    let materialWon: Int?
    let guests: [BK06Guest]
    let targets: [BK06RefillTarget]
}

struct BK06GuestDraft: Decodable, Identifiable {
    let bookingId: String
    let customerName: String
    let draft: String
    var id: String { bookingId }
}

struct BK06UnderMinResult: Decodable { let drafts: [BK06GuestDraft] }
struct BK06Removed: Decodable { let removed: Int }

enum BK06Format {
    static func date(_ value: String) -> Date? { try? Date(value, strategy: .iso8601) }

    /// "11월 22일 일요일 14:00" in workshop time.
    static func when(_ value: String) -> String {
        guard let date = date(value) else { return value }
        return "\(date.koreanDay()) \(clock(date))"
    }

    static func day(_ value: String) -> String { date(value)?.koreanDay(weekday: false) ?? value }

    static func clock(_ date: Date) -> String {
        let parts = Calendar.workshop.dateComponents([.hour, .minute], from: date)
        return String(format: "%02d:%02d", parts.hour ?? 0, parts.minute ?? 0)
    }

    static func won(_ amount: Int) -> String { "\(amount.formatted(.number.locale(Locale(identifier: "ko_KR"))))원" }

    /// "45분", "4시간", or "4시간 30분".
    static func elapsed(_ minutes: Int) -> String {
        guard minutes >= 60 else { return "\(minutes)분" }
        return minutes % 60 == 0 ? "\(minutes / 60)시간" : "\(minutes / 60)시간 \(minutes % 60)분"
    }

    static func remaining(_ minutes: Int) -> String {
        if minutes <= 0 { return "지남" }
        if minutes < 60 { return "\(minutes)분 남음" }
        if minutes < 60 * 24 { return "\(minutes / 60)시간 남음" }
        return "\(minutes / (60 * 24))일 남음"
    }
}
