import Foundation
@testable import RoundupCore

/// Stateful server substitute: revisions and completed decisions obey the backend contract.
@MainActor
final class MemoryInquiryRepository: InquiryRepository {
    var records = DemoStore().inquiries
    var loadFails = false
    var writeFails = false
    var loseDecisionResponse = false
    var pauseSave = false
    private var saveGate: CheckedContinuation<Void, Never>?
    private var saveStarted: CheckedContinuation<Void, Never>?

    enum Failure: Error { case offline }

    func load() async throws -> [Inquiry] {
        if loadFails { throw Failure.offline }
        return records
    }

    func save(id: String, draft: InquiryDraft) async throws -> Inquiry {
        if pauseSave {
            await withCheckedContinuation { continuation in
                saveGate = continuation
                saveStarted?.resume()
                saveStarted = nil
            }
        }
        if writeFails { throw Failure.offline }
        let index = try writableIndex(id: id, revision: draft.expectedRevision)
        records[index].draft = draft.draft
        records[index].revision += 1
        return records[index]
    }

    func decide(id: String, decision: InquiryDecision) async throws -> Inquiry {
        if writeFails { throw Failure.offline }
        let index = try writableIndex(id: id, revision: decision.expectedRevision)
        let text = decision.draft.trimmingCharacters(in: .whitespacesAndNewlines)
        switch decision.decision {
        case .approve:
            guard !text.isEmpty else { throw ReplyError.emptyDraft }
            records[index].status = .approved
        case .reject:
            records[index].status = .rejected
        }
        records[index].draft = text
        records[index].revision += 1
        if loseDecisionResponse { throw Failure.offline }
        return records[index]
    }

    func waitForSave() async {
        if saveGate != nil { return }
        await withCheckedContinuation { saveStarted = $0 }
    }

    func finishSave() {
        saveGate?.resume()
        saveGate = nil
    }

    private func writableIndex(id: String, revision: Int) throws -> Int {
        guard let index = records.firstIndex(where: { $0.id == id }) else {
            throw ReplyError.missingInquiry
        }
        guard records[index].revision == revision, records[index].status == .pending else {
            throw InquiryPersistenceError.conflict
        }
        return index
    }
}
