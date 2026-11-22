import XCTest

/// Build B's grounded replies against a local server whose model is scripted. Skipped unless ROUNDUP_UITEST_BK25 is 1,
/// so the build A suite never needs this server.
final class BK25UITests: RoundupUITestCase {
    private struct SeededJudgment: Decodable { let judgment: Judgment?; struct Judgment: Decodable { let id: String } }

    override func setUpWithError() throws {
        continueAfterFailure = false
        guard ProcessInfo.processInfo.environment["ROUNDUP_UITEST_BK25"] == "1" else {
            throw XCTSkip("Set TEST_RUNNER_ROUNDUP_UITEST_BK25=1 to run against the local build B server")
        }
    }

    /// Asks the server for a judgment before the app opens, the way a customer's question would raise one.
    private func raiseJudgment(for inquiryID: String) async throws -> String {
        let base = try XCTUnwrap(ProcessInfo.processInfo.environment["ROUNDUP_UITEST_API_URL"])
        let key = try XCTUnwrap(ProcessInfo.processInfo.environment["ROUNDUP_UITEST_API_KEY"])
        var request = URLRequest(url: try XCTUnwrap(URL(string: "\(base)/grounded-replies/\(inquiryID)/draft")))
        request.httpMethod = "POST"
        request.setValue(key, forHTTPHeaderField: "X-Roundup-Key")
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = Data("{}".utf8)
        let (data, _) = try await URLSession.shared.data(for: request)
        let seeded = try JSONDecoder().decode(SeededJudgment.self, from: data)
        return try XCTUnwrap(seeded.judgment?.id)
    }

    @MainActor
    private func openInquiry(_ inquiryID: String, in app: XCUIApplication) {
        let card = app.buttons["inquiry.\(inquiryID)"]
        XCTAssertTrue(scrollTo(card, in: app), "the inquiry \(inquiryID) is missing")
        tapInTheMiddle(card, in: app)
        let editor = app.textViews["inquiry.draft"]
        XCTAssertTrue(editor.waitForExistence(timeout: 60), "the inquiry did not open")
        keepScreenshot(of: app, named: "bk25-inquiry-open")
    }

    /// A row scrolled under the navigation bar reports itself hittable, so it is moved into the middle of the screen first.
    @MainActor
    private func tapInTheMiddle(_ target: XCUIElement, in app: XCUIApplication) {
        let height = app.frame.height
        for _ in 0..<8 {
            let middle = target.frame.midY
            if middle > height * 0.25 && middle < height * 0.65 { break }
            if middle <= height * 0.25 { app.swipeDown(velocity: .slow) } else { app.swipeUp(velocity: .slow) }
        }
        target.tap()
    }

    /// Waits until the number of matching buttons reaches the expected count, without a fixed sleep.
    @MainActor
    private func waitForCount(_ expected: Int, of query: XCUIElementQuery) {
        let predicate = NSPredicate { _, _ in query.count == expected }
        wait(for: [XCTNSPredicateExpectation(predicate: predicate, object: nil)], timeout: 90)
    }

    @MainActor
    func testReplyIsLockedUntilItsNumbersMatchTheLedger() throws {
        let app = try launch()
        // The scratch server's inquiry-group carries the weekend question, so it is one of the first three cards.
        openInquiry("inquiry-group", in: app)
        let write = app.descendants(matching: .any)["inquiry.generate"].firstMatch
        XCTAssertTrue(scrollTo(write, in: app))
        write.tap()
        app.buttons["새로 쓰기"].tap()

        let locked = app.staticTexts.matching(NSPredicate(format: "label CONTAINS %@", "장부와 달라요")).firstMatch
        XCTAssertTrue(scrollTo(locked, in: app), "the mismatch summary is missing")
        keepScreenshot(of: app, named: "bk25-locked-reply")
        let complete = app.buttons["inquiry.complete"]
        XCTAssertTrue(scrollTo(complete, in: app))
        XCTAssertFalse(complete.isEnabled, "a reply with numbers that differ must not be completed")

        let fixes = app.buttons.matching(identifier: "bk25.fix")
        XCTAssertTrue(scrollTo(fixes.firstMatch, in: app))
        for remaining in stride(from: 2, through: 0, by: -1) {
            let first = fixes.firstMatch
            XCTAssertTrue(scrollTo(first, in: app))
            first.tap()
            waitForCount(remaining, of: fixes)
        }
        let clear = app.staticTexts.matching(NSPredicate(format: "label CONTAINS %@", "모든 숫자가 장부와 맞아요")).firstMatch
        XCTAssertTrue(scrollTo(clear, in: app))
        keepScreenshot(of: app, named: "bk25-cleared-reply")
        XCTAssertTrue(scrollTo(complete, in: app))
        XCTAssertTrue(complete.isEnabled)
    }

    @MainActor
    func testAnswerToAJudgmentBecomesARule() async throws {
        _ = try await raiseJudgment(for: "inquiry-k25")
        let app = try launch()
        let row = app.buttons.matching(NSPredicate(format: "identifier BEGINSWITH %@", "judgment.")).firstMatch
        XCTAssertTrue(scrollTo(row, in: app), "the judgment card is missing on Today")
        keepScreenshot(of: app, named: "bk25-today-judgment")
        row.tap()

        let field = app.descendants(matching: .any)["bk25.field"].firstMatch
        XCTAssertTrue(field.waitForExistence(timeout: 60))
        field.tap()
        field.typeText("6명부터 1인 3만 원")
        let show = app.buttons["bk25.rule.show"]
        XCTAssertTrue(show.waitForExistence(timeout: 60))
        show.tap()
        let preview = app.descendants(matching: .any)["bk25.rule.preview"].firstMatch
        XCTAssertTrue(preview.waitForExistence(timeout: 90))
        keepScreenshot(of: app, named: "bk25-rule-preview")
        app.buttons["bk25.answer.rule"].tap()
        XCTAssertTrue(show.waitForNonExistence(timeout: 90))

        app.tabBars.buttons["설정"].tap()
        let cards = app.buttons["settings.factCards"]
        XCTAssertTrue(cards.waitForExistence(timeout: 60))
        cards.tap()
        let card = app.buttons["bk25.card.주말 도자기 클래스"]
        XCTAssertTrue(scrollTo(card, in: app))
        card.tap()
        let rule = element(labelled: "6명부터", in: app)
        XCTAssertTrue(scrollTo(rule, in: app), "the saved rule is missing from the class card")
        keepScreenshot(of: app, named: "bk25-class-rules")
    }

    @MainActor
    func testFactCardListIsEmptyWithoutClasses() throws {
        let app = try launchEmptyServer()
        app.tabBars.buttons["설정"].tap()
        let cards = app.buttons["settings.factCards"]
        XCTAssertTrue(cards.waitForExistence(timeout: 60))
        cards.tap()
        XCTAssertTrue(element(labelled: "캘린더에 수업을 먼저 넣어 주세요", in: app).waitForExistence(timeout: 60))
        keepScreenshot(of: app, named: "bk25-fact-card-empty")
    }

    @MainActor
    func testFactCardIsFilledThroughTheInterview() throws {
        let app = try launch()
        app.tabBars.buttons["설정"].tap()
        let cards = app.buttons["settings.factCards"]
        XCTAssertTrue(cards.waitForExistence(timeout: 60))
        cards.tap()
        let list = app.buttons["bk25.card.원데이 물레 체험"]
        XCTAssertTrue(scrollTo(list, in: app), "the class list is missing")
        keepScreenshot(of: app, named: "bk25-fact-card-list")
        list.tap()
        let start = app.buttons["bk25.interview.start"]
        XCTAssertTrue(scrollTo(start, in: app))
        start.tap()
        let field = app.descendants(matching: .any)["bk25.field"].firstMatch
        XCTAssertTrue(field.waitForExistence(timeout: 60))
        field.tap()
        field.typeText("두 시간 정도요")
        app.buttons["bk25.field.submit"].tap()
        let next = app.staticTexts["2/5"]
        XCTAssertTrue(next.waitForExistence(timeout: 90))
        for _ in 0..<4 {
            app.buttons["bk25.interview.skip"].tap()
        }
        let saved = element(labelled: "120분", in: app)
        XCTAssertTrue(scrollTo(saved, in: app), "the spoken length is missing from the card")
        let save = app.buttons["bk25.card.save"]
        XCTAssertTrue(scrollTo(save, in: app))
        save.tap()
        let toast = app.descendants(matching: .any)["toast.message"].firstMatch
        XCTAssertTrue(toast.waitForExistence(timeout: 60))
        keepScreenshot(of: app, named: "bk25-fact-card-saved")
    }
}
