import Foundation
import Observation

/// What the server knows about one inquiry's reply, and how far the text in the editor has been checked.
@MainActor
@Observable
final class BK25Grounding {
    private(set) var arm: BK25Arm?
    private(set) var claims: [BK25Claim] = []
    private(set) var lock: BK25Lock = .unchecked
    private(set) var mismatchCount = 0
    private(set) var checkedKinds: [String] = []
    private(set) var judgment: BK25Judgment?
    private(set) var verifiedText: String?
    private(set) var isVerifying = false
    private(set) var loadFailed = false
    /// The reason the owner chose for sending this locked text as it is. It ends with the approval or the next edit.
    var overrideReason: String?

    var isGrounded: Bool { arm == .grounded }

    /// The server checks the saved draft, so a text that differs from it waits for its own check.
    func needsVerification(_ text: String) -> Bool {
        isGrounded && verifiedText != text && !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }

    /// A locked reply waits for a fix or a reason; a changed text waits for its check.
    func blocksApproval(_ text: String) -> Bool {
        guard isGrounded, overrideReason == nil else { return false }
        return lock == .locked || isVerifying || (verifiedText != nil && verifiedText != text)
    }

    func load(_ inquiryID: String, draft: String) async {
        do {
            let state = try await BK25API.replyState(inquiryID)
            arm = state.arm
            show(state)
            judgment = state.judgment
            verifiedText = draft
            loadFailed = false
        } catch is CancellationError {
            return
        } catch {
            loadFailed = true
        }
    }

    /// Returns the text to put in the editor, or nil when the question was handed to the owner instead.
    func generate(_ inquiryID: String) async throws -> String? {
        let written = try await BK25API.draft(inquiryID)
        arm = written.arm
        judgment = written.judgment
        overrideReason = nil
        guard written.judgment == nil else { return nil }
        show(written)
        verifiedText = written.draft
        return written.draft
    }

    /// The reply written after the owner's answer, checked like any other draft.
    func apply(_ answer: BK25JudgmentAnswer) {
        arm = answer.arm
        judgment = nil
        overrideReason = nil
        show(answer)
        verifiedText = answer.draft
    }

    func verify(_ inquiryID: String, text: String) async {
        guard needsVerification(text) else { return }
        isVerifying = true
        overrideReason = nil
        defer { isVerifying = false }
        do {
            show(try await BK25API.verify(inquiryID, draft: text))
        } catch {
            // The approval is checked again by the server, so a failed check here only leaves the text unchecked.
            show(BK25Verification(claims: [], lock: .unchecked, mismatchCount: 0, checkedKinds: []))
        }
        verifiedText = text
    }

    func decide(_ inquiryID: String, draft: String, expectedRevision: Int) async throws {
        _ = try await BK25API.decide(inquiryID, draft: draft, expectedRevision: expectedRevision,
                                     overrideReason: overrideReason)
        overrideReason = nil
    }

    /// Puts the ledger's own words where the draft has the claim, so the next check finds the fix.
    func replacing(_ claim: BK25Claim, in text: String) -> String {
        guard let replacement = claim.replacement, let range = text.range(of: claim.text) else { return text }
        return text.replacingCharacters(in: range, with: replacement)
    }

    private func show(_ checked: some BK25Checked) {
        claims = checked.claims
        lock = checked.lock
        mismatchCount = checked.mismatchCount
        checkedKinds = checked.checkedKinds
    }
}
