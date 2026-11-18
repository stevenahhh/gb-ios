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
    func testContentReviewIsRecorded() throws {
        let app = try launch()
        openArea("channels", in: app)
        app.segmentedControls.buttons["콘텐츠"].tap()
        let review = app.buttons["action.draft-keyring-result"]
        XCTAssertTrue(scrollTo(review, in: app))
        review.tap()
        let save = app.buttons["form.save"]
        XCTAssertTrue(save.waitForExistence(timeout: 5))
        wait(for: [expectation(for: NSPredicate(format: "isEnabled == true"), evaluatedWith: save)], timeout: 10)
        save.tap()
        XCTAssertTrue(review.waitForNonExistence(timeout: 10))
    }

    @MainActor
    func testRecommendationAcknowledgementIsRecorded() throws {
        let app = try launch()
        let segment = app.segmentedControls.buttons["비서 추천"]
        XCTAssertTrue(segment.waitForExistence(timeout: 10))
        segment.tap()
        let acknowledge = app.buttons["action.recommendation-market"]
        XCTAssertTrue(scrollTo(acknowledge, in: app))
        acknowledge.tap()
        XCTAssertTrue(acknowledge.waitForNonExistence(timeout: 10))
    }

    @MainActor
    func testTaskCompletionIsReflectedFromTheServer() throws {
        let app = try launch()
        let task = app.buttons["task.task-market"]
        XCTAssertTrue(scrollTo(task, in: app))
        XCTAssertEqual(task.value as? String, "미완료")
        task.tap()
        waitFor(task, "value == %@", "완료")
    }

    @MainActor
    func testCalendarRowTogglesInPlaceAndOpensItsDetail() throws {
        let app = try launch()
        app.tabBars.buttons["캘린더"].tap()
        let order = app.buttons.matching(NSPredicate(format: "label CONTAINS %@", "#1042")).firstMatch
        XCTAssertTrue(scrollTo(order, in: app))
        order.tap()
        XCTAssertTrue(app.navigationBars["일정 상세"].waitForExistence(timeout: 10))
        XCTAssertTrue(element(labelled: "주문과 배송", in: app).waitForExistence(timeout: 10))
        goBack(app)

        // The enclosing row link inherits the toggle's identifier, so the label picks the toggle.
        let toggle = app.buttons.matching(NSPredicate(
            format: "identifier == %@ AND label ENDSWITH %@", "task.task-market", "완료 표시")).firstMatch
        XCTAssertTrue(scrollTo(toggle, in: app))
        XCTAssertEqual(toggle.value as? String, "미완료")
        toggle.tap()
        waitFor(toggle, "value == %@", "완료")
        XCTAssertFalse(app.navigationBars["일정 상세"].exists)
        toggle.tap()
        waitFor(toggle, "value == %@", "미완료")
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
        name.tap()
        name.typeText(" 본점")
        app.buttons["workshop.save"].tap()
        XCTAssertTrue(element(labelled: "오롯 공방 본점", in: app).waitForExistence(timeout: 10))
    }
}
