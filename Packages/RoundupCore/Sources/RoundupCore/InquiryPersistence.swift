import Foundation

public struct InquiryDraft: Encodable, Sendable {
    public let draft: String
    public let expectedRevision: Int

    public init(draft: String, expectedRevision: Int) {
        self.draft = draft
        self.expectedRevision = expectedRevision
    }
}

public struct InquiryDecision: Encodable, Sendable {
    public let decision: ReplyDecision
    public let draft: String
    public let expectedRevision: Int

    public init(decision: ReplyDecision, draft: InquiryDraft) {
        self.decision = decision
        self.draft = draft.draft
        self.expectedRevision = draft.expectedRevision
    }
}

@MainActor
public protocol InquiryRepository {
    func load() async throws -> [Inquiry]
    func save(id: String, draft: InquiryDraft) async throws -> Inquiry
    func decide(id: String, decision: InquiryDecision) async throws -> Inquiry
    func undoCompletion(id: String, expectedRevision: Int) async throws -> Inquiry
    /// The last list the server returned on this device, shown until a fresh load arrives.
    func cached() async -> (inquiries: [Inquiry], savedAt: Date)?
}

extension InquiryRepository {
    public func cached() async -> (inquiries: [Inquiry], savedAt: Date)? { nil }
}

/// A failure that retrying later can fix, such as a lost connection. Other failures are not retried by themselves.
public protocol TransientFailure: Error {}

public enum InquiryPersistenceError: Error, LocalizedError {
    case busy
    case conflict

    public var errorDescription: String? {
        switch self {
        case .busy: return "문의를 처리 중이에요. 완료된 뒤 다시 시도해 주세요."
        case .conflict: return "다른 곳에서 변경되었거나 이미 처리된 문의예요. 목록을 새로 불러온 뒤 확인해 주세요."
        }
    }
}
