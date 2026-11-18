import Foundation

/// Raw values are stable codes for storage and the server; `label` is the text shown on screen.
public enum ReplyStatus: String, Codable, Sendable {
    case pending
    case approved
    case rejected

    public var label: String {
        switch self {
        case .pending: return "승인 대기"
        case .approved: return "답변 승인됨"
        case .rejected: return "답변 반려됨"
        }
    }
}

public enum ReplyDecision: String, Encodable, Sendable {
    case approve
    case reject
}

public enum ReplyError: Error, LocalizedError, Equatable {
    case missingInquiry
    case alreadyDecided
    case emptyDraft
    case notDecided

    public var errorDescription: String? {
        switch self {
        case .missingInquiry: return "문의를 찾을 수 없습니다. 문의 목록에서 다시 열어 주세요."
        case .alreadyDecided: return "이미 처리된 답변입니다. 다시 승인하거나 반려할 수 없습니다."
        case .emptyDraft: return "빈 내용은 승인할 수 없어요. 내용을 쓰거나 반려해 주세요."
        case .notDecided: return "아직 승인하거나 반려하지 않은 초안이에요."
        }
    }
}

public struct Inquiry: Identifiable, Codable, Equatable, Sendable {
    public let id: String
    public let customer: String
    public let subject: String
    public let question: String
    public let facts: [String]
    public internal(set) var draft: String
    public internal(set) var status: ReplyStatus
    public internal(set) var revision: Int = 0

    /// The only client rule for undoing a decision. Refuse delivered replies here once sending exists.
    public var canReopen: Bool { status != .pending }

    enum CodingKeys: String, CodingKey {
        case id, customer, subject, question, facts, draft, status, revision
    }
}
