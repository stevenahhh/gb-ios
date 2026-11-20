import XCTest

final class ActionFlowUITests: RoundupUITestCase {
    override func setUpWithError() throws {
        continueAfterFailure = false
    }

    @MainActor
    private func waitFor(_ element: XCUIElement, _ format: String, _ value: String) {
        let predicate = NSPredicate(format: format, value)
        wait(for: [expectation(for: predicate, evaluatedWith: element)], timeout: 10)
    }

    @MainActor
    private func waitUntil(_ element: XCUIElement, isEnabled: Bool) {
        let predicate = NSPredicate(format: "isEnabled == %@", NSNumber(value: isEnabled))
        wait(for: [expectation(for: predicate, evaluatedWith: element)], timeout: 10)
    }

    @MainActor
    private func goBack(_ app: XCUIApplication) {
        app.navigationBars.buttons.element(boundBy: 0).tap()
    }

    @MainActor
    func testPackingAndOrderConfirmationAdvanceTheirWork() throws {
        let app = try launch()
        openArea("deliveries", in: app)
        let pack = app.buttons["action.shipment-order-1040"]
        XCTAssertTrue(scrollTo(pack, in: app))
        pack.tap()
        waitFor(pack, "label == %@", "송장 등록하기")

        goBack(app)
        openArea("orders", in: app)
        let confirm = app.buttons["action.order-1042"]
        XCTAssertTrue(scrollTo(confirm, in: app))
        confirm.tap()
        XCTAssertTrue(confirm.waitForNonExistence(timeout: 10))
    }

    @MainActor
    private func approveThenReopenDraft(_ row: XCUIElement, in app: XCUIApplication) {
        XCTAssertTrue(scrollTo(row, in: app))
        row.tap()
        let approve = app.buttons["draft.approve"]
        XCTAssertTrue(approve.waitForExistence(timeout: 10))
        approve.tap()
        let reopen = app.buttons["draft.reopen"]
        XCTAssertTrue(reopen.waitForExistence(timeout: 10))
        reopen.tap()
        XCTAssertTrue(app.buttons["draft.approve"].waitForExistence(timeout: 10))
    }

    @MainActor
    func testContentDraftCanBeApprovedAndUndone() throws {
        let app = try launch()
        openArea("channels", in: app)
        app.segmentedControls.buttons["콘텐츠"].tap()
        approveThenReopenDraft(app.buttons["draft.content.draft-keyring-result"], in: app)
    }

    @MainActor
    func testRecommendationDraftCanBeApprovedAndUndone() throws {
        let app = try launch()
        let segment = app.segmentedControls.buttons["비서 추천"]
        // The segments sit below 확인해 주실 일, so scroll to them first.
        XCTAssertTrue(scrollTo(segment, in: app))
        segment.tap()
        approveThenReopenDraft(app.buttons["draft.recommendation.recommendation-market"], in: app)
    }

    @MainActor
    func testDepositConfirmationCanBeUndoneFromBookingDetail() throws {
        let app = try launch()
        openArea("bookings", in: app)
        let row = app.buttons["booking.row.booking-minwoo"]
        XCTAssertTrue(scrollTo(row, in: app))
        row.tap()
        let confirm = app.buttons["step.do.예약금"]
        XCTAssertTrue(confirm.waitForExistence(timeout: 10))
        confirm.tap()
        let undo = app.buttons["step.undo.예약금"]
        XCTAssertTrue(undo.waitForExistence(timeout: 10))
        undo.tap()
        XCTAssertTrue(app.buttons["step.do.예약금"].waitForExistence(timeout: 10))
    }

    @MainActor
    func testTaskCompletionIsReflectedFromTheServer() throws {
        let app = try launch()
        let task = app.buttons["task.task-market"]
        // After its 17:00 deadline the task joins the overdue group, whose rows past the third sit behind 모두 보기.
        let all = app.buttons["today.overdue.all"]
        if scrollTo(all, in: app) {
            all.tap()
            // The list loads its own data, so give it the same bound as other server waits.
            if !task.waitForExistence(timeout: 10) {
                app.navigationBars.buttons.element(boundBy: 0).tap()
            }
        } else {
            // No overdue overflow: return to the top, where the task's own section starts the search.
            for _ in 0..<8 { app.swipeDown() }
        }
        XCTAssertTrue(scrollTo(task, in: app))
        XCTAssertEqual(task.value as? String, "미완료")
        task.tap()
        waitFor(task, "value == %@", "완료")
    }

    @MainActor
    func testCalendarCheckIsInstantAndCanBeUndone() throws {
        let app = try launch()
        app.tabBars.buttons["캘린더"].tap()
        let check = app.buttons["timeline.check.task:task-market"]
        XCTAssertTrue(scrollTo(check, in: app))
        XCTAssertEqual(check.value as? String, "미완료")
        check.tap()
        waitFor(check, "value == %@", "완료")
        let undo = app.buttons["calendar.toast.undo"]
        XCTAssertTrue(undo.waitForExistence(timeout: 10))
        XCTAssertTrue(app.navigationBars["캘린더"].exists)
        undo.tap()
        waitFor(check, "value == %@", "미완료")

        let orders = app.buttons["calendar.orders"]
        XCTAssertTrue(scrollTo(orders, in: app))
        orders.tap()
        XCTAssertTrue(element(labelled: "새 주문", in: app).waitForExistence(timeout: 10))
    }

    @MainActor
    func testCompletedInquiryReplyCanBeEditedAgain() throws {
        let app = try launch()
        let row = app.buttons["inquiry.inquiry-change"]
        XCTAssertTrue(scrollTo(row, in: app))
        row.tap()
        let complete = app.buttons["inquiry.complete"]
        XCTAssertTrue(scrollTo(complete, in: app))
        complete.tap()
        waitUntil(complete, isEnabled: false)

        let editor = app.textViews["inquiry.draft"]
        XCTAssertTrue(scrollTo(editor, in: app))
        editor.tap()
        editor.typeText("추가 안내")
        XCTAssertTrue(scrollTo(complete, in: app))
        waitUntil(complete, isEnabled: true)
    }

    @MainActor
    func testBookingFormCreatesABookingWaitingForDeposit() throws {
        let app = try launch()
        openArea("bookings", in: app)
        let add = app.buttons["booking.add"]
        XCTAssertTrue(add.waitForExistence(timeout: 10))
        add.tap()
        let picker = app.buttons["booking.session"]
        XCTAssertTrue(picker.waitForExistence(timeout: 10))
        picker.tap()
        let option = app.buttons.matching(NSPredicate(format: "label CONTAINS %@", "주말 도자기 클래스")).firstMatch
        XCTAssertTrue(option.waitForExistence(timeout: 5))
        option.tap()
        let name = app.textFields["booking.name"]
        XCTAssertTrue(name.waitForExistence(timeout: 5))
        name.tap()
        name.typeText("김민수")
        app.buttons["form.save"].tap()
        XCTAssertTrue(name.waitForNonExistence(timeout: 10))
        XCTAssertTrue(scrollTo(element(labelled: "김*수 · 1명", in: app), in: app))
    }

    @MainActor
    func testWorkshopEditIsSavedToTheServer() throws {
        let app = try launch()
        app.tabBars.buttons["설정"].tap()
        let row = app.buttons["settings.workshop"]
        XCTAssertTrue(row.waitForExistence(timeout: 10))
        row.tap()
        let name = app.textFields["workshop.name"]
        XCTAssertTrue(name.waitForExistence(timeout: 5))
        // The value is right-aligned, so tap its trailing edge to put the cursor after the name.
        name.coordinate(withNormalizedOffset: CGVector(dx: 0.98, dy: 0.5)).tap()
        name.typeText(" 본점")
        app.buttons["workshop.save"].tap()
        XCTAssertTrue(element(labelled: "오롯 공방 본점", in: app).waitForExistence(timeout: 10))
    }
}
