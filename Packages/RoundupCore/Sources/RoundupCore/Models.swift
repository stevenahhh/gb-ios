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

    public var errorDescription: String? {
        switch self {
        case .missingInquiry: return "문의를 찾을 수 없습니다. 문의 목록에서 다시 열어 주세요."
        case .alreadyDecided: return "이미 처리된 답변입니다. 다시 승인하거나 반려할 수 없습니다."
        case .emptyDraft: return "빈 답변은 승인할 수 없습니다. 답변 내용을 입력하거나 초안을 반려해 주세요."
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

    enum CodingKeys: String, CodingKey {
        case id, customer, subject, question, facts, draft, status, revision
    }
}
