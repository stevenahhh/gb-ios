import Foundation
@testable import RoundupCore

/// Stateful server substitute: revisions and completed replies obey the backend contract.
@MainActor
final class MemoryInquiryRepository: InquiryRepository {
    var records = [
        Inquiry(id: "inquiry-clay", customer: "김하늘", subject: "도자기 체험 준비물", question: "준비물이 있을까요?",
                facts: ["공방 안내 · 앞치마와 도구를 제공합니다."], draft: "준비되어 있습니다.", status: .pending),
        Inquiry(id: "inquiry-group", customer: "이도윤", subject: "두 사람 함께 참여", question: "같이 참여할 수 있나요?",
                facts: ["수업 정원 · 한 회차 최대 6명입니다."], draft: "함께 참여하실 수 있습니다.", status: .pending),
        Inquiry(id: "inquiry-change", customer: "박서연", subject: "수업 일정 변경", question: "날짜를 바꾸고 싶어요.",
                facts: ["변경 규정 · 수업 2일 전까지 가능합니다."], draft: "2일 전까지 가능합니다.", status: .pending),
    ]
    var loadFails = false
    var loadIsRejected = false
    var loadIsCancelled = false
    var cachedRecords: (inquiries: [Inquiry], savedAt: Date)?
    var writeFails = false
    var loseDecisionResponse = false
    var pauseSave = false
    private var saveGate: CheckedContinuation<Void, Never>?
    private var saveStarted: CheckedContinuation<Void, Never>?

    enum Failure: Error { case offline, unsupportedDecision }
    struct Offline: TransientFailure {}

    func load() async throws -> [Inquiry] {
        if loadIsCancelled { throw CancellationError() }
        if loadIsRejected { throw Failure.offline }
        if loadFails { throw Offline() }
        return records
    }

    func cached() async -> (inquiries: [Inquiry], savedAt: Date)? { cachedRecords }

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
        if records[index].status == .approved,
           draft.draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            throw ReplyError.emptyDraft
        }
        records[index].draft = draft.draft
        records[index].revision += 1
        return records[index]
    }

    func decide(id: String, decision: InquiryDecision) async throws -> Inquiry {
        if writeFails { throw Failure.offline }
        let index = try writableIndex(id: id, revision: decision.expectedRevision)
        guard decision.decision == .approve else { throw Failure.unsupportedDecision }
        let text = decision.draft.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty else { throw ReplyError.emptyDraft }
        records[index].status = .approved
        records[index].draft = text
        records[index].revision += 1
        if loseDecisionResponse { throw Failure.offline }
        return records[index]
    }

    func undoCompletion(id: String, expectedRevision: Int) async throws -> Inquiry {
        if writeFails { throw Failure.offline }
        let index = try writableIndex(id: id, revision: expectedRevision)
        guard records[index].status == .approved else { throw InquiryPersistenceError.conflict }
        records[index].status = .pending
        records[index].revision += 1
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
        guard records[index].revision == revision else {
            throw InquiryPersistenceError.conflict
        }
        return index
    }
}
