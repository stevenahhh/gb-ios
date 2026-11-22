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
        // Swiping before Today has loaded its cards would scroll past the one this test opens.
        let cards = app.buttons.matching(NSPredicate(format: "identifier BEGINSWITH %@", "inquiry."))
        XCTAssertTrue(cards.firstMatch.waitForExistence(timeout: 90), "Today has no reply to approve")
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

    /// The evidence is below the reply and its button, so moving between them also has to go back up.
    @MainActor
    private func scrollBackTo(_ target: XCUIElement, in app: XCUIApplication) -> Bool {
        for _ in 0..<8 {
            if target.waitForExistence(timeout: 2), target.isHittable { return true }
            app.swipeDown()
        }
        return target.exists && target.isHittable
    }

    /// Writes a reply whose three numbers differ from the ledger and waits for the line that says so.
    @MainActor
    private func writeLockedReply(in app: XCUIApplication) {
        // The scratch server's inquiry-group carries the weekend question, so it is one of the first three cards.
        openInquiry("inquiry-group", in: app)
        let write = app.descendants(matching: .any)["inquiry.generate"].firstMatch
        XCTAssertTrue(scrollTo(write, in: app))
        write.tap()
        app.buttons["새로 쓰기"].tap()
        XCTAssertTrue(app.descendants(matching: .any)["bk25.lockLine"].firstMatch.waitForExistence(timeout: 90),
                      "the line under the button is missing")
        XCTAssertTrue(scrollTo(app.buttons["bk25.more"], in: app), "the mismatch summary is missing")
    }

    @MainActor
    func testReplyIsLockedUntilItsNumbersMatchTheLedger() throws {
        let app = try launch()
        writeLockedReply(in: app)
        keepScreenshot(of: app, named: "bk25-locked-reply")
        let complete = app.buttons["inquiry.complete"]
        XCTAssertTrue(scrollBackTo(complete, in: app))
        XCTAssertFalse(complete.isEnabled, "a reply with numbers that differ must not be completed")
        XCTAssertTrue(element(labelled: "숫자 3개가 장부와 달라요", in: app).exists)
        keepScreenshot(of: app, named: "bk25-locked-button")

        for wrong in ["‘네 자리’", "‘45,000원’", "‘30,000원’"] {
            XCTAssertTrue(scrollTo(app.staticTexts[wrong], in: app), "\(wrong) is missing")
            let fix = app.buttons.matching(identifier: "bk25.fix").firstMatch
            XCTAssertTrue(scrollTo(fix, in: app), "no fix is offered for \(wrong)")
            fix.tap()
            XCTAssertTrue(app.staticTexts[wrong].waitForNonExistence(timeout: 90), "\(wrong) was not fixed")
        }
        XCTAssertTrue(scrollBackTo(app.staticTexts["장부와 다른 숫자를 찾지 못했어요"], in: app))
        let kinds = app.descendants(matching: .any)["bk25.checkedKinds"].firstMatch
        XCTAssertTrue(kinds.waitForExistence(timeout: 60), "the compared kinds are not named")
        for kind in ["남은 자리", "가격", "예약금"] {
            XCTAssertTrue(kinds.label.contains(kind), "\(kind) is not named in \(kinds.label)")
        }
        keepScreenshot(of: app, named: "bk25-cleared-reply")
        XCTAssertTrue(scrollBackTo(complete, in: app))
        XCTAssertTrue(complete.isEnabled)
    }

    @MainActor
    func testSendingALockedReplyNeedsAReason() throws {
        let app = try launch()
        writeLockedReply(in: app)
        app.buttons["bk25.more"].tap()
        app.buttons["이번만 그대로 보내기"].tap()
        let reason = app.buttons["손님과 따로 정했어요"]
        XCTAssertTrue(reason.waitForExistence(timeout: 60), "the reasons did not come up")
        keepScreenshot(of: app, named: "bk25-override-reasons")
        reason.tap()
        XCTAssertTrue(reason.waitForNonExistence(timeout: 90))
        XCTAssertTrue(scrollBackTo(element(labelled: "답변 준비됨", in: app), in: app), "the reply was not completed")
        keepScreenshot(of: app, named: "bk25-override-done")
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
        let asRule = app.buttons["bk25.answer.rule"]
        XCTAssertTrue(scrollTo(asRule, in: app))
        asRule.tap()
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
        let skip = app.buttons["bk25.interview.skip"]
        for _ in 0..<4 { skip.tap() }
        // Swiping while the sheet still closes would scroll the saved row away.
        XCTAssertTrue(skip.waitForNonExistence(timeout: 90))
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
