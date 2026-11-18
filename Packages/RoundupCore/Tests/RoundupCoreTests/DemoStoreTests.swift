import Foundation
import XCTest
@testable import RoundupCore

final class DemoStoreTests: XCTestCase {
    // 2026-11-16 00:00 in Seoul, independent of the host clock and locale.
    private let day = Date(timeIntervalSince1970: 1_794_754_800)

    func testApprovalUsesEditedDraftAndRemovesPendingItem() throws {
        let store = DemoStore(now: day)
        try store.editDraft(id: "inquiry-clay", text: "  수정한 준비물 안내입니다. \n")

        try store.decide(id: "inquiry-clay", decision: .approve)

        XCTAssertEqual(store.inquiry(id: "inquiry-clay")?.draft, "수정한 준비물 안내입니다.")
        XCTAssertEqual(store.inquiry(id: "inquiry-clay")?.status, .approved)
        XCTAssertEqual(store.pendingCount, 2)
        XCTAssertFalse(store.pendingInquiries.contains { $0.id == "inquiry-clay" })
    }

    func testBlankDraftRefusesApprovalAndStaysPending() throws {
        let store = DemoStore(now: day)
        try store.editDraft(id: "inquiry-clay", text: " \n\t ")

        XCTAssertThrowsError(try store.decide(id: "inquiry-clay", decision: .approve)) {
            XCTAssertEqual($0 as? ReplyError, .emptyDraft)
        }

        XCTAssertEqual(store.inquiry(id: "inquiry-clay")?.status, .pending)
        XCTAssertEqual(store.pendingCount, 3)
    }

    func testBlankDraftCanStillBeRejected() throws {
        let store = DemoStore(now: day)
        try store.editDraft(id: "inquiry-clay", text: " \n\t ")

        try store.decide(id: "inquiry-clay", decision: .reject)

        XCTAssertEqual(store.inquiry(id: "inquiry-clay")?.status, .rejected)
        XCTAssertEqual(store.inquiry(id: "inquiry-clay")?.draft, "")
        XCTAssertEqual(store.pendingCount, 2)
    }

    func testStatusCodesStayStableAndSeparateFromLabels() {
        XCTAssertEqual(ReplyStatus.pending.rawValue, "pending")
        XCTAssertEqual(ReplyStatus.approved.rawValue, "approved")
        XCTAssertEqual(ReplyStatus.rejected.rawValue, "rejected")
        XCTAssertEqual(ReplyStatus.pending.label, "승인 대기")
    }

    func testRejectionUpdatesStatusAndPendingCount() throws {
        let store = DemoStore(now: day)

        try store.decide(id: "inquiry-group", decision: .reject)

        XCTAssertEqual(store.inquiry(id: "inquiry-group")?.status, .rejected)
        XCTAssertEqual(store.pendingCount, 2)
    }

    func testCompletedReplyRefusesEverySubsequentDecisionAndEdit() throws {
        for first in [ReplyDecision.approve, .reject] {
            let store = DemoStore(now: day)
            try store.decide(id: "inquiry-clay", decision: first)
            let completed = store.inquiry(id: "inquiry-clay")

            for repeated in [ReplyDecision.approve, .reject] {
                XCTAssertThrowsError(try store.decide(id: "inquiry-clay", decision: repeated)) {
                    XCTAssertEqual($0 as? ReplyError, .alreadyDecided)
                }
            }
            XCTAssertThrowsError(try store.editDraft(id: "inquiry-clay", text: "덮어쓰기")) {
                XCTAssertEqual($0 as? ReplyError, .alreadyDecided)
            }
            XCTAssertEqual(store.inquiry(id: "inquiry-clay"), completed)
            XCTAssertEqual(store.pendingCount, 2)
        }
    }

    func testReplyApprovalLeavesSessionsAndBookingsUnchanged() throws {
        let store = DemoStore(now: day)
        let original = store.sessions

        try store.decide(id: "inquiry-group", decision: .approve)

        XCTAssertEqual(store.sessions, original)
        XCTAssertEqual(store.reservationCount, 4)
    }

    func testSelectedDatesReturnOnlyMatchingSessionDetails() {
        let store = DemoStore(now: day)
        let today = store.referenceDay
        let tomorrow = today.addingTimeInterval(86400)

        XCTAssertEqual(store.sessions(on: today).map(\.id), ["session-morning", "session-afternoon"])
        XCTAssertEqual(store.sessions(on: tomorrow).map(\.id), ["session-tomorrow"])
        XCTAssertEqual(store.sessions(on: today.addingTimeInterval(172800)), [])
        for session in store.sessions(on: tomorrow) {
            XCTAssertEqual(store.session(id: session.id), session)
            XCTAssertTrue(DemoStore.calendar.isDate(session.startsAt, inSameDayAs: tomorrow))
            XCTAssertEqual(DemoStore.calendar.component(.hour, from: session.startsAt), 11)
        }
    }

    func testResetRestoresDemoDataWithNewDateAnchor() throws {
        let store = DemoStore(now: day)
        try store.decide(id: "inquiry-clay", decision: .approve)
        let nextWeek = store.referenceDay.addingTimeInterval(7 * 86400)

        store.reset(now: nextWeek)

        XCTAssertEqual(store.pendingCount, 3)
        XCTAssertEqual(store.reservationCount, 4)
        XCTAssertEqual(store.sessions(on: nextWeek).count, 2)
        XCTAssertEqual(store.sessions(on: nextWeek.addingTimeInterval(86400)).count, 1)
        XCTAssertEqual(store.inquiry(id: "inquiry-clay")?.status, .pending)
    }
}
