#if BUILD_B
import Foundation

/// Which draft an inquiry gets: the existing one, or the one checked against the studio's own facts.
enum BK25Arm: String, Decodable {
    case control
    case grounded
}

/// Whether a draft's numbers may be approved. `unchecked` means the numbers could not be confirmed.
enum BK25Lock: String, Decodable {
    case clear
    case locked
    case unchecked
}

/// One number or statement in a draft and where it comes from.
struct BK25Claim: Decodable, Hashable {
    enum Kind: String, Decodable { case price, seats, date, deposit, fact, rule }

    enum Source: String, Decodable {
        case ledger
        case priceList = "price_list"
        case factCard = "fact_card"
        case ownerRule = "owner_rule"
        case customer
        case none

        var symbol: String {
            switch self {
            case .ledger: "calendar"
            case .priceList, .factCard: "doc.text"
            case .ownerRule: "checkmark.seal"
            case .customer: "quote.bubble"
            case .none: "questionmark.circle"
            }
        }
    }

    enum Status: String, Decodable { case matched, mismatched, unsupported, unchecked }

    let kind: Kind
    let text: String
    let value: String
    let source: Source
    let sourceLabel: String
    let ledgerValue: String?
    let status: Status
    let match: Bool
    let note: String?
    let replacement: String?
}

/// A question the studio's facts could not answer, waiting for the owner.
struct BK25Judgment: Decodable, Identifiable, Hashable {
    let id: String
    let inquiryId: String
    let issue: String
    let status: String
    let customer: String
    let question: String
    let answerText: String?
}

struct BK25Draft: Decodable {
    let arm: BK25Arm
    let draft: String
    let claims: [BK25Claim]
    let lock: BK25Lock
    let mismatchCount: Int
    let judgment: BK25Judgment?
}

struct BK25ReplyState: Decodable {
    let inquiryId: String
    let arm: BK25Arm?
    let claims: [BK25Claim]
    let lock: BK25Lock
    let mismatchCount: Int
    let judgment: BK25Judgment?
    let overrideReason: String?
}

struct BK25Verification: Decodable {
    let claims: [BK25Claim]
    let lock: BK25Lock
    let mismatchCount: Int
}

/// Whether the owner's answer is reused in later replies.
enum BK25Scope: String, Encodable {
    case rule
    case once
}

/// The sentence an answer would become, and the class it would belong to (nil for the whole studio).
struct BK25RulePreview: Decodable, Equatable {
    let ruleText: String
    let className: String?
}

/// The result of answering: the saved rule, if any, and the reply written again.
struct BK25JudgmentAnswer: Decodable {
    let judgmentId: String
    let ruleText: String?
    let ruleId: String?
    let arm: BK25Arm
    let draft: String
    let claims: [BK25Claim]
    let lock: BK25Lock
    let mismatchCount: Int
}

/// A sentence the owner saved for later replies.
struct BK25Rule: Decodable, Identifiable, Hashable {
    let id: String
    let cardId: String?
    let className: String?
    let ruleText: String
    let questionSummary: String
}

/// The five questions of the interview, in the order they are asked.
enum BK25FactField: String, CaseIterable, Identifiable, Codable {
    case durationMinutes
    case capacity
    case includedMaterials
    case parking
    case refundPolicy

    var id: Self { self }

    var title: String {
        switch self {
        case .durationMinutes: "소요 시간"
        case .capacity: "정원"
        case .includedMaterials: "포함 재료와 준비물"
        case .parking: "주차"
        case .refundPolicy: "환불 규정"
        }
    }

    var question: String {
        switch self {
        case .durationMinutes: "수업은 얼마나 걸려요?"
        case .capacity: "한 회에 몇 명까지 받아요?"
        case .includedMaterials: "가격에 포함된 재료는 무엇이고, 손님이 가져올 것은 있나요?"
        case .parking: "주차는 어떻게 안내하나요?"
        case .refundPolicy: "환불과 취소 규정은 어떻게 되나요?"
        }
    }

    var hint: String {
        switch self {
        case .durationMinutes: "예: 두 시간 정도요"
        case .capacity: "예: 최대 여섯 명이요"
        case .includedMaterials: "예: 앞치마와 도구는 다 있고, 편한 신발만 신고 오세요"
        case .parking: "예: 건물 뒤 공영주차장에 세우면 돼요"
        case .refundPolicy: "예: 수업 2일 전까지는 전액 환불해요"
        }
    }
}

/// One class on the fact card list. A revision of 0 means nothing has been saved yet.
struct BK25FactCardSummary: Decodable, Identifiable, Hashable {
    let id: String
    let className: String
    let filledCount: Int
    let ruleCount: Int
    let revision: Int
    let updatedAt: String?
}

/// A class's facts and the rules that apply to it.
struct BK25FactCard: Decodable, Identifiable {
    let id: String
    let className: String
    let durationMinutes: Int?
    let capacity: Int?
    let includedMaterials: String?
    let parking: String?
    let refundPolicy: String?
    let priceWon: Int?
    let filledCount: Int
    let revision: Int
    let updatedAt: String?
    let rules: [BK25Rule]
}

struct BK25FactCardUpdate: Encodable {
    let className: String
    let expectedRevision: Int
    let durationMinutes: Int?
    let capacity: Int?
    let includedMaterials: String?
    let parking: String?
    let refundPolicy: String?
    let priceWon: Int?
}

/// One interview answer as a card value, or nothing when it was unclear.
struct BK25InterviewValue: Decodable {
    enum Confidence: String, Decodable { case clear, unclear }

    let field: String
    let value: String
    let confidence: Confidence
}
#endif
