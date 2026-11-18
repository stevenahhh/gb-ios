import Foundation
@testable import RoundupCore

/// Stateful server substitute: revisions and completed decisions obey the backend contract.
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

    func reopen(id: String, request: InquiryReopen) async throws -> Inquiry {
        if writeFails { throw Failure.offline }
        guard let index = records.firstIndex(where: { $0.id == id }) else {
            throw ReplyError.missingInquiry
        }
        guard records[index].revision == request.expectedRevision, records[index].status != .pending else {
            throw InquiryPersistenceError.conflict
        }
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
        guard records[index].revision == revision, records[index].status == .pending else {
            throw InquiryPersistenceError.conflict
        }
        return index
    }
}
