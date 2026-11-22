#if BUILD_B
import Foundation
import RoundupCore

/// The grounded reply routes. Build A never calls them.
enum BK25API {
    private struct NoBody: Encodable {}

    // MARK: Replies

    static func replyState(_ inquiryID: String) async throws -> BK25ReplyState {
        try await RoundupAPI.get("grounded-replies/\(inquiryID)")
    }

    static func draft(_ inquiryID: String) async throws -> BK25Draft {
        try await RoundupAPI.send(method: "POST", path: "grounded-replies/\(inquiryID)/draft", body: NoBody())
    }

    static func verify(_ inquiryID: String, draft: String) async throws -> BK25Verification {
        struct Body: Encodable { let draft: String }
        return try await RoundupAPI.send(method: "POST", path: "grounded-replies/\(inquiryID)/verify",
                                         body: Body(draft: draft))
    }

    /// Approves like the existing decision route; a locked reply needs the reason the owner chose.
    static func decide(_ inquiryID: String, draft: String, expectedRevision: Int,
                       overrideReason: String?) async throws -> Inquiry {
        struct Body: Encodable {
            let decision = "approve"
            let draft: String
            let expectedRevision: Int
            let overrideReason: String?
        }
        return try await RoundupAPI.send(method: "POST", path: "grounded-replies/\(inquiryID)/decision",
                                         body: Body(draft: draft, expectedRevision: expectedRevision,
                                                    overrideReason: overrideReason))
    }

    // MARK: Judgments

    static func openJudgments() async throws -> [BK25Judgment] {
        try await RoundupAPI.get("judgments", query: ["status": "open"])
    }

    static func previewRule(_ judgmentID: String, answer: String) async throws -> BK25RulePreview {
        struct Body: Encodable { let answer: String }
        return try await RoundupAPI.send(method: "POST", path: "judgments/\(judgmentID)/rule-preview",
                                         body: Body(answer: answer))
    }

    static func answer(_ judgmentID: String, answer: String, scope: BK25Scope) async throws -> BK25JudgmentAnswer {
        struct Body: Encodable { let answer: String; let scope: BK25Scope }
        return try await RoundupAPI.send(method: "POST", path: "judgments/\(judgmentID)/answer",
                                         body: Body(answer: answer, scope: scope))
    }

    static func dismiss(_ judgmentID: String) async throws -> BK25Judgment {
        try await RoundupAPI.send(method: "POST", path: "judgments/\(judgmentID)/dismiss", body: NoBody())
    }

    // MARK: Fact cards and rules

    static func factCards() async throws -> [BK25FactCardSummary] { try await RoundupAPI.get("fact-cards") }

    static func factCard(_ cardID: String) async throws -> BK25FactCard {
        try await RoundupAPI.get("fact-cards/\(cardID)")
    }

    static func saveFactCard(_ cardID: String, _ update: BK25FactCardUpdate) async throws -> BK25FactCard {
        try await RoundupAPI.send(method: "PUT", path: "fact-cards/\(cardID)", body: update)
    }

    static func interview(_ cardID: String, field: BK25FactField, answer: String) async throws -> BK25InterviewValue {
        struct Body: Encodable { let field: BK25FactField; let answer: String }
        return try await RoundupAPI.send(method: "POST", path: "fact-cards/\(cardID)/interview",
                                         body: Body(field: field, answer: answer))
    }

    static func retireRule(_ ruleID: String) async throws -> BK25Rule {
        try await RoundupAPI.send(method: "DELETE", path: "owner-rules/\(ruleID)", body: NoBody())
    }
}

/// The quick approval from the Today card, which never sends a reply whose numbers are locked.
enum BK25Approval {
    struct LockedReply: LocalizedError {
        var errorDescription: String? { "초안의 숫자가 장부와 달라요. 문의를 열어 확인한 뒤 보내 주세요." }
    }

    @MainActor
    static func approve(_ inquiry: Inquiry, store: InquiryStore) async throws {
        let state = try await BK25API.replyState(inquiry.id)
        if state.arm == .grounded && state.lock == .locked { throw LockedReply() }
        _ = try await BK25API.decide(inquiry.id, draft: inquiry.draft, expectedRevision: inquiry.revision,
                                     overrideReason: nil)
        await store.loadInquiries()
    }
}
#endif
