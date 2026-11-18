import Foundation
import XCTest
@testable import RoundupCore

final class InquiryPersistenceTests: XCTestCase {
    @MainActor
    func testProductionLoadFailureNeverSuppliesSampleInquiriesAndRetryLoadsServerState() async {
        let server = MemoryInquiryRepository()
        server.records = Array(server.records.prefix(1))
        server.loadFails = true
        let store = InquiryStore(repository: server)

        await store.loadInquiries()

        XCTAssertEqual(store.inquiries, [])
        XCTAssertFalse(store.hasLoadedInquiries)
        XCTAssertNotNil(store.inquiryLoadError)
        server.loadFails = false
        await store.loadInquiries()
        XCTAssertEqual(store.pendingCount, 1)
        XCTAssertTrue(store.hasLoadedInquiries)
        XCTAssertNil(store.inquiryLoadError)
    }

    @MainActor
    func testSavedDraftSurvivesNewStoreAndDecisionUsesCurrentUnsavedTextAtomically() async throws {
        let server = MemoryInquiryRepository()
        let store = InquiryStore(repository: server)
        await store.loadInquiries()
        try await store.saveDraft(id: "inquiry-clay", draft: InquiryDraft(draft: "저장한 초안", expectedRevision: 0))
        XCTAssertEqual(store.inquiry(id: "inquiry-clay")?.draft, "저장한 초안")
        XCTAssertEqual(store.inquiry(id: "inquiry-clay")?.revision, 1)
        let restarted = InquiryStore(repository: server)
        await restarted.loadInquiries()
        XCTAssertEqual(restarted.inquiry(id: "inquiry-clay")?.draft, "저장한 초안")
        XCTAssertEqual(restarted.inquiry(id: "inquiry-clay")?.revision, 1)

        try await restarted.decide(id: "inquiry-clay", decision: InquiryDecision(
            decision: .approve, draft: InquiryDraft(draft: "  승인 순간 수정한 내용  ", expectedRevision: 1)))
        XCTAssertEqual(restarted.pendingCount, 2)
        XCTAssertEqual(restarted.inquiry(id: "inquiry-clay")?.status, .approved)

        let again = InquiryStore(repository: server)
        await again.loadInquiries()
        XCTAssertEqual(again.inquiry(id: "inquiry-clay")?.draft, "승인 순간 수정한 내용")
        XCTAssertEqual(again.inquiry(id: "inquiry-clay")?.status, .approved)
        XCTAssertEqual(again.pendingCount, 2)
    }

    @MainActor
    func testRejectionOfBlankDraftPersistsAndRefusesSubsequentEditsAndDecisions() async throws {
        let server = MemoryInquiryRepository()
        let store = InquiryStore(repository: server)
        await store.loadInquiries()
        try await store.decide(id: "inquiry-group", decision: InquiryDecision(
            decision: .reject, draft: InquiryDraft(draft: " \n", expectedRevision: 0)))
        XCTAssertEqual(store.pendingCount, 2)
        let restarted = InquiryStore(repository: server)
        await restarted.loadInquiries()

        XCTAssertEqual(restarted.inquiry(id: "inquiry-group")?.status, .rejected)
        XCTAssertEqual(restarted.inquiry(id: "inquiry-group")?.draft, "")
        XCTAssertEqual(restarted.pendingCount, 2)
        do {
            try await restarted.saveDraft(id: "inquiry-group", draft: InquiryDraft(draft: "덮어쓰기", expectedRevision: 1))
            XCTFail("Completed inquiry accepted an edit")
        } catch { XCTAssertEqual(error as? ReplyError, .alreadyDecided) }
        do {
            try await restarted.decide(id: "inquiry-group", decision: InquiryDecision(
                decision: .approve, draft: InquiryDraft(draft: "반복 결정", expectedRevision: 1)))
            XCTFail("Completed inquiry accepted another decision")
        } catch { XCTAssertEqual(error as? ReplyError, .alreadyDecided) }
    }

    @MainActor
    func testBlankApprovalAndStaleEditorRevisionDoNotChangeServerState() async throws {
        let server = MemoryInquiryRepository()
        let store = InquiryStore(repository: server)
        await store.loadInquiries()
        do {
            try await store.decide(id: "inquiry-clay", decision: InquiryDecision(
                decision: .approve, draft: InquiryDraft(draft: " \n", expectedRevision: 0)))
            XCTFail("Blank approval succeeded")
        } catch { XCTAssertEqual(error as? ReplyError, .emptyDraft) }
        try await store.saveDraft(id: "inquiry-clay", draft: InquiryDraft(draft: "서버 최신", expectedRevision: 0))

        do {
            try await store.saveDraft(id: "inquiry-clay", draft: InquiryDraft(draft: "오래된 편집", expectedRevision: 0))
            XCTFail("Stale editor overwrote server state")
        } catch { XCTAssertTrue(error is InquiryPersistenceError) }
        XCTAssertEqual(server.records.first?.draft, "서버 최신")
        XCTAssertEqual(store.pendingCount, 3)
    }

    @MainActor
    func testFailedSavePreservesConfirmedDraftAndRequiresReconciliationBeforeRetry() async throws {
        let server = MemoryInquiryRepository()
        let store = InquiryStore(repository: server)
        await store.loadInquiries()
        let original = store.inquiries
        server.writeFails = true

        do {
            try await store.saveDraft(id: "inquiry-clay", draft: InquiryDraft(draft: "미저장", expectedRevision: 0))
            XCTFail("Offline save succeeded")
        } catch { XCTAssertTrue(store.requiresInquiryReload) }

        XCTAssertEqual(store.inquiries, original)
        XCTAssertFalse(store.isInquiryBusy)
        server.writeFails = false
        do {
            try await store.decide(id: "inquiry-clay", decision: InquiryDecision(
                decision: .approve, draft: InquiryDraft(draft: "재시도", expectedRevision: 0)))
            XCTFail("Unreconciled write was allowed")
        } catch { XCTAssertTrue(error is InquiryPersistenceError) }
        await store.loadInquiries()
        XCTAssertFalse(store.requiresInquiryReload)
    }

    @MainActor
    func testLostDecisionResponseIsNotReportedSavedUntilReloadRestoresCommittedDecision() async throws {
        let server = MemoryInquiryRepository()
        let store = InquiryStore(repository: server)
        await store.loadInquiries()
        server.loseDecisionResponse = true

        do {
            try await store.decide(id: "inquiry-clay", decision: InquiryDecision(
                decision: .approve, draft: InquiryDraft(draft: "응답 유실", expectedRevision: 0)))
            XCTFail("Lost response was reported as success")
        } catch { XCTAssertTrue(store.requiresInquiryReload) }

        XCTAssertEqual(store.pendingCount, 3)
        await store.loadInquiries()
        XCTAssertEqual(store.pendingCount, 2)
        XCTAssertEqual(store.inquiry(id: "inquiry-clay")?.status, .approved)
    }

    @MainActor
    func testInFlightSaveBlocksDuplicateSaveDecisionAndRefreshUntilCompletion() async throws {
        let server = MemoryInquiryRepository()
        server.pauseSave = true
        let store = InquiryStore(repository: server)
        await store.loadInquiries()
        let draft = InquiryDraft(draft: "저장 중", expectedRevision: 0)
        let saving = Task { try await store.saveDraft(id: "inquiry-clay", draft: draft) }
        await server.waitForSave()
        server.pauseSave = false
        defer { server.finishSave() }

        do {
            try await store.saveDraft(id: "inquiry-clay", draft: draft)
            XCTFail("Duplicate save succeeded")
        } catch { XCTAssertTrue(error is InquiryPersistenceError) }
        do {
            try await store.decide(id: "inquiry-clay", decision: InquiryDecision(decision: .approve, draft: draft))
            XCTFail("Decision raced a save")
        } catch { XCTAssertTrue(error is InquiryPersistenceError) }
        await store.loadInquiries()
        XCTAssertTrue(store.isSavingInquiry)
        server.finishSave()
        try await saving.value
        XCTAssertEqual(store.inquiry(id: "inquiry-clay")?.revision, 1)
        XCTAssertEqual(store.inquiry(id: "inquiry-clay")?.status, .pending)
    }

    @MainActor
    func testServerConflictAndMissingInquiryPreserveCountsUntilReload() async throws {
        for missing in [false, true] {
            let server = MemoryInquiryRepository()
            let store = InquiryStore(repository: server)
            await store.loadInquiries()
            if missing {
                server.records.removeFirst()
            } else {
                _ = try await server.decide(id: "inquiry-clay", decision: InquiryDecision(
                    decision: .reject, draft: InquiryDraft(draft: "다른 기기 결정", expectedRevision: 0)))
            }

            do {
                try await store.saveDraft(id: "inquiry-clay", draft: InquiryDraft(draft: "오래된 초안", expectedRevision: 0))
                XCTFail("Server conflict or deletion was ignored")
            } catch { XCTAssertTrue(store.requiresInquiryReload) }

            XCTAssertEqual(store.pendingCount, 3)
            await store.loadInquiries()
            XCTAssertEqual(store.pendingCount, 2)
            XCTAssertEqual(store.inquiry(id: "inquiry-clay")?.status, missing ? nil : .rejected)
        }
    }

    func testStatusCodesStayStableAndSeparateFromLabels() {
        XCTAssertEqual(ReplyStatus.pending.rawValue, "pending")
        XCTAssertEqual(ReplyStatus.approved.rawValue, "approved")
        XCTAssertEqual(ReplyStatus.rejected.rawValue, "rejected")
        XCTAssertEqual(ReplyStatus.pending.label, "승인 대기")
    }

    func testBackendJSONDecodesRevisionAndDecisionEncodesAtomicContract() throws {
        let data = Data("""
        [{"id":"server-only","customer":"손님","subject":"문의","question":"질문",
        "facts":["근거"],"draft":"서버 답변","status":"approved","revision":7}]
        """.utf8)
        let inquiries = try JSONDecoder().decode([Inquiry].self, from: data)
        XCTAssertEqual(inquiries.first?.revision, 7)
        XCTAssertEqual(inquiries.first?.status, .approved)
        let decision = InquiryDecision(decision: .reject, draft: InquiryDraft(draft: "현재 편집", expectedRevision: 7))
        let encoded = try JSONEncoder().encode(decision)
        let object = try XCTUnwrap(JSONSerialization.jsonObject(with: encoded) as? [String: AnyHashable])
        XCTAssertEqual(object, ["decision": "reject", "draft": "현재 편집", "expectedRevision": 7])
    }
}
