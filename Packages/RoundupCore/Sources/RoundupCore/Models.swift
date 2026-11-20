import Foundation

/// Raw values are stable codes for storage and the server; `label` is the text shown on screen.
/// Raw values are stable codes shared with the server. Inquiries use only `pending` and `approved`;
/// assistant drafts for posts and recommendations can also be `rejected`.
public enum ReplyStatus: String, Codable, Sendable {
    case pending
    case approved
    case rejected
}

public enum ReplyDecision: String, Encodable, Sendable {
    case approve
    case reject
}

public enum ReplyError: Error, LocalizedError, Equatable {
    case missingInquiry
    case emptyDraft
    case notCompleted

    public var errorDescription: String? {
        switch self {
        case .missingInquiry: return "문의를 찾을 수 없습니다. 문의 목록에서 다시 열어 주세요."
        case .emptyDraft: return "빈 내용으로는 저장하거나 완료할 수 없어요. 내용을 입력해 주세요."
        case .notCompleted: return "아직 완료하지 않은 답변이에요."
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
