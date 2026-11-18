import Foundation

/// Raw values are stable codes for storage and the server; `label` is the text shown on screen.
public enum ReplyStatus: String, Codable, Sendable {
    case pending
    case approved

    public var label: String {
        switch self {
        case .pending: return "답변 대기"
        case .approved: return "답변 완료"
        }
    }
}

public enum ReplyDecision: String, Encodable, Sendable {
    case approve
}

public enum ReplyError: Error, LocalizedError, Equatable {
    case missingInquiry
    case emptyDraft

    public var errorDescription: String? {
        switch self {
        case .missingInquiry: return "문의를 찾을 수 없습니다. 문의 목록에서 다시 열어 주세요."
        case .emptyDraft: return "빈 답변은 완료할 수 없습니다. 답변 내용을 입력해 주세요."
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
