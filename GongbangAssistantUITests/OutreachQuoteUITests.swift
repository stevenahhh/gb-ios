import XCTest

/// 출강 견적: cost cards, reading an inquiry, the verdict, and the locked export.
final class OutreachQuoteUITests: RoundupUITestCase {
    override func setUpWithError() throws {
        continueAfterFailure = false
        guard ProcessInfo.processInfo.environment["ROUNDUP_UITEST_K14"] == "1" else {
            throw XCTSkip("Set TEST_RUNNER_ROUNDUP_UITEST_K14=1 to run against a local server whose model names the class of an inquiry")
        }
    }

    @MainActor
    private func openQuotes(in app: XCUIApplication) {
        app.tabBars.buttons["운영"].tap()
        let row = app.buttons["operations.outreach"]
        XCTAssertTrue(scrollTo(row, in: app), "the outreach row is missing")
        row.tap()
        XCTAssertTrue(app.navigationBars["출장 수업 견적"].waitForExistence(timeout: 10))
    }

    @MainActor
    private func fill(_ identifier: String, _ value: String, in app: XCUIApplication) {
        let field = app.textFields[identifier]
        XCTAssertTrue(scrollTo(field, in: app), "\(identifier) is missing")
        // Values are right-aligned, so the trailing edge puts the caret after the last digit.
        field.coordinate(withNormalizedOffset: CGVector(dx: 0.98, dy: 0.5)).tap()
        if let current = field.value as? String, current != "입력" {
            field.typeText(String(repeating: XCUIKeyboardKey.delete.rawValue, count: current.count))
        }
        field.typeText(value)
    }

    @MainActor
    private func read(_ inquiry: String, in app: XCUIApplication) {
        app.buttons["outreach.new"].firstMatch.tap()
        let text = app.textViews["outreach.text"]
        XCTAssertTrue(text.waitForExistence(timeout: 10))
        text.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.5)).tap()
        XCTAssertTrue(app.keyboards.firstMatch.waitForExistence(timeout: 20))
        text.typeText(inquiry)
        let readButton = app.buttons["outreach.read"]
        XCTAssertTrue(scrollTo(readButton, in: app))
        readButton.tap()
    }

    @MainActor
    private func saveCosts(in app: XCUIApplication) {
        app.tabBars.buttons["설정"].tap()
        let row = app.buttons["settings.classCosts"]
        XCTAssertTrue(scrollTo(row, in: app))
        row.tap()
        let mug = app.buttons["classCost.나만의 머그컵 만들기"]
        XCTAssertTrue(mug.waitForExistence(timeout: 10))
        keepScreenshot(of: app, named: "k14-01-class-costs")
        mug.tap()
        fill("classCost.material", "14000", in: app)
        fill("classCost.price", "35000", in: app)
        fill("classCost.prep", "30", in: app)
        fill("classCost.cleanup", "30", in: app)
        XCTAssertTrue(scrollTo(app.buttons["outreach.save"], in: app))
        app.buttons["outreach.save"].tap()
        let defaults = app.buttons["classCost.defaults"]
        XCTAssertTrue(scrollTo(defaults, in: app))
        defaults.tap()
        fill("defaults.hourly", "100000", in: app)
        fill("defaults.assistant", "90000", in: app)
        fill("defaults.flat", "50000", in: app)
        fill("defaults.minimum", "300000", in: app)
        XCTAssertTrue(scrollTo(app.buttons["outreach.save"], in: app))
        app.buttons["outreach.save"].tap()
        XCTAssertTrue(app.navigationBars["수업마다 드는 돈"].waitForExistence(timeout: 10))
    }

    @MainActor
    func testInquiryBecomesAVerdictAndALockedExportNeedsTheInstitutionCheck() throws {
        // The tab bar stays minimized after a scroll, so each tab starts from a fresh launch.
        saveCosts(in: try launch())
        let app = try launch()
        openQuotes(in: app)
        read("시청 총무과입니다. 40명 출강, 예산은 200만 원입니다. 대신 구매도 부탁드려요.", in: app)
        XCTAssertTrue(app.descendants(matching: .any)["outreach.warning"].waitForExistence(timeout: 15))
        XCTAssertTrue(app.buttons["outreach.verify"].exists)
        keepScreenshot(of: app, named: "k14-02-read-warning")
        let create = app.buttons["outreach.create"]
        XCTAssertTrue(scrollTo(create, in: app))
        fill("outreach.travel", "90", in: app)
        XCTAssertTrue(scrollTo(create, in: app))
        keepScreenshot(of: app, named: "k14-03-fields")
        create.tap()
        let verdict = app.staticTexts["outreach.verdict"]
        XCTAssertTrue(verdict.waitForExistence(timeout: 15) || scrollTo(verdict, in: app))
        XCTAssertTrue(element(labelled: "오가는 시간 3시간", in: app).exists)
        keepScreenshot(of: app, named: "k14-04-detail-warning")
        app.buttons["outreach.makePDF"].tap()
        XCTAssertTrue(app.descendants(matching: .any)["outreach.locked"].waitForExistence(timeout: 10))
        keepScreenshot(of: app, named: "k14-05-pdf-locked")
        app.buttons["닫기"].firstMatch.tap()
        let verify = app.buttons["outreach.verify"]
        XCTAssertTrue(verify.waitForExistence(timeout: 10))
        verify.tap()
        XCTAssertTrue(verify.waitForNonExistence(timeout: 10))
        XCTAssertTrue(scrollTo(app.staticTexts["outreach.verdict"], in: app))
        keepScreenshot(of: app, named: "k14-06-detail-verdict")
        app.swipeUp()
        keepScreenshot(of: app, named: "k14-07-detail-lines")
        app.swipeUp()
        XCTAssertTrue(scrollTo(app.buttons["outreach.copyReply"], in: app))
        keepScreenshot(of: app, named: "k14-08-detail-reply")
        app.buttons["outreach.makePDF"].tap()
        XCTAssertTrue(app.switches["outreach.checked"].waitForExistence(timeout: 10) || scrollTo(app.switches["outreach.checked"], in: app))
        XCTAssertFalse(app.descendants(matching: .any)["outreach.locked"].exists)
        keepScreenshot(of: app, named: "k14-09-pdf-open")
        let checked = app.switches["outreach.checked"]
        XCTAssertTrue(scrollTo(checked, in: app))
        // A tap that lands while the list still moves only stops it, so the switch itself says when it is on.
        for _ in 0..<3 where checked.value as? String != "1" {
            checked.coordinate(withNormalizedOffset: CGVector(dx: 0.93, dy: 0.5)).tap()
            let isOn = XCTNSPredicateExpectation(predicate: NSPredicate(format: "value == '1'"), object: checked)
            _ = XCTWaiter().wait(for: [isOn], timeout: 5)
        }
        XCTAssertEqual(checked.value as? String, "1")
        let export = app.buttons["outreach.export"]
        XCTAssertTrue(scrollTo(export, in: app))
        let isEnabled = XCTNSPredicateExpectation(predicate: NSPredicate(format: "isEnabled == true"), object: export)
        XCTAssertEqual(XCTWaiter().wait(for: [isEnabled], timeout: 10), .completed)
        export.tap()
        XCTAssertTrue(app.otherElements["ActivityListView"].waitForExistence(timeout: 20))
        keepScreenshot(of: app, named: "k14-13-share")
    }

    @MainActor
    func testConditionsReminderAndOutcomeAreSaved() throws {
        let app = try launch()
        openQuotes(in: app)
        read("40명 출강, 예산은 200만 원입니다.", in: app)
        let create = app.buttons["outreach.create"]
        XCTAssertTrue(create.waitForExistence(timeout: 15) || scrollTo(create, in: app))
        XCTAssertTrue(scrollTo(create, in: app))
        create.tap()
        let people = app.steppers["outreach.stepHeadcount"]
        XCTAssertTrue(app.staticTexts["outreach.verdict"].waitForExistence(timeout: 15))
        XCTAssertFalse(app.descendants(matching: .any)["outreach.warning"].exists)
        keepScreenshot(of: app, named: "k14-15-detail-first-run")
        XCTAssertTrue(scrollTo(people, in: app))
        people.buttons.element(boundBy: 1).tap()
        XCTAssertTrue(app.steppers.matching(NSPredicate(format: "label CONTAINS %@", "41")).firstMatch.waitForExistence(timeout: 10)
            || app.staticTexts["41명이 온다면"].waitForExistence(timeout: 5))
        let remind = app.buttons["outreach.remind"]
        XCTAssertTrue(scrollTo(remind, in: app))
        remind.tap()
        let moved = NSPredicate(format: "label == %@", "시각 바꾸기")
        expectation(for: moved, evaluatedWith: remind)
        waitForExpectations(timeout: 15)
        let outcome = app.buttons["outreach.outcome"]
        // The fixed 견적표 만들기 bar covers the last row until the list is scrolled to its end.
        app.swipeUp()
        XCTAssertTrue(scrollTo(outcome, in: app))
        // The element spans the whole row; the menu button itself sits at its leading edge.
        outcome.coordinate(withNormalizedOffset: CGVector(dx: 0.18, dy: 0.5)).tap()
        let declined = app.buttons["거절"].firstMatch
        XCTAssertTrue(declined.waitForExistence(timeout: 10))
        declined.tap()
        XCTAssertTrue(remind.waitForNonExistence(timeout: 15))
        XCTAssertTrue(element(labelled: "상태 거절", in: app).waitForExistence(timeout: 10))
        keepScreenshot(of: app, named: "k14-14-outcome")
    }

    @MainActor
    func testFailedReadOffersTheBlankForm() throws {
        let app = try launch()
        openQuotes(in: app)
        read("읽기 실패 시험 문의 30명", in: app)
        XCTAssertTrue(app.descendants(matching: .any)["outreach.readFailed"].waitForExistence(timeout: 15))
        XCTAssertEqual(app.textFields["outreach.headcount"].value as? String, "30")
        XCTAssertTrue(element(labelled: "확인 필요", in: app).exists)
        keepScreenshot(of: app, named: "k14-10-read-failed")
    }

    @MainActor
    func testEmptyServerShowsTheEmptyStates() throws {
        let quotes = try launchEmptyServer()
        openQuotes(in: quotes)
        XCTAssertTrue(quotes.staticTexts["아직 들어온 출장 수업 문의가 없어요"].waitForExistence(timeout: 10))
        keepScreenshot(of: quotes, named: "k14-11-empty-quotes")
        let app = try launchEmptyServer()
        app.tabBars.buttons["설정"].tap()
        let row = app.buttons["settings.classCosts"]
        XCTAssertTrue(scrollTo(row, in: app))
        row.tap()
        XCTAssertTrue(app.staticTexts["아직 만든 수업이 없어요"].waitForExistence(timeout: 10))
        keepScreenshot(of: app, named: "k14-12-empty-costs")
    }
}
