import XCTest

/// The cancellation and no-show card against the local server seeded with b_k06_seed.py.
final class BK06UITests: RoundupUITestCase {
    override func setUpWithError() throws {
        guard ProcessInfo.processInfo.environment["ROUNDUP_UITEST_K06"] == "1" else {
            throw XCTSkip("Set TEST_RUNNER_ROUNDUP_UITEST_K06=1 to run against a local server seeded with b_k06_seed.py")
        }
    }

    /// A tap that lands while the push still animates loses its focus, so the covered screen must be gone first.
    @MainActor
    private func waitUntilCovered(_ row: XCUIElement) {
        XCTAssertTrue(row.waitForNonExistence(timeout: 30))
    }

    @MainActor
    private func openPaste(_ message: String, in app: XCUIApplication) {
        let row = app.buttons["k06.paste"]
        XCTAssertTrue(scrollTo(row, in: app))
        row.tap()
        waitUntilCovered(row)
        let editor = app.descendants(matching: .any)["k06.message"].firstMatch
        XCTAssertTrue(editor.waitForExistence(timeout: 10))
        editor.tap()
        editor.typeText(message)
        let find = app.buttons["k06.find"]
        XCTAssertTrue(scrollTo(find, in: app))
        find.tap()
    }

    @MainActor
    func testCancellationCardDraftsAReplyAndOffersTheSeat() throws {
        let app = try launch()
        keepScreenshot(of: app, named: "k06-today")
        openPaste("김하윤이에요. 오늘 아이가 아파서 못 갈 것 같은데 환불되나요?", in: app)
        XCTAssertTrue(element(labelled: "손님께 보여 드린 3번째 규정으로 계산", in: app).waitForExistence(timeout: 15))
        XCTAssertTrue(element(labelled: "미리 계산해 본 금액", in: app).exists)
        keepScreenshot(of: app, named: "k06-cancellation-card")
        let picker = app.descendants(matching: .any)["k06.decision"].firstMatch
        XCTAssertTrue(scrollTo(picker, in: app))
        picker.tap()
        app.buttons["다음 수업으로 1회 넘기기"].tap()
        let reason = app.textFields["k06.reason"]
        XCTAssertTrue(scrollTo(reason, in: app))
        reason.tap()
        reason.typeText("아이가 아픔")
        keepScreenshot(of: app, named: "k06-decision")
        let decide = app.buttons["k06.decide"]
        XCTAssertTrue(scrollTo(decide, in: app))
        decide.tap()
        let draft = app.textViews["k06.draft"]
        XCTAssertTrue(draft.waitForExistence(timeout: 15))
        XCTAssertTrue((draft.value as? String)?.contains("다음 회차로 한 번 옮겨 드릴게요") == true)
        let approve = app.buttons["k06.approve"]
        XCTAssertTrue(scrollTo(approve, in: app))
        keepScreenshot(of: app, named: "k06-draft")
        approve.tap()
        let refill = app.buttons["k06.openRefill"]
        XCTAssertTrue(scrollTo(refill, in: app))
        refill.tap()
        XCTAssertTrue(app.buttons["k06.refill.copy"].waitForExistence(timeout: 10))
        keepScreenshot(of: app, named: "k06-refill")
    }

    @MainActor
    func testUnmatchedMessageOffersRecentBookings() throws {
        let app = try launch()
        openPaste("환불되나요?", in: app)
        XCTAssertTrue(element(labelled: "이 문자에 맞는 예약이 안 보여요", in: app).waitForExistence(timeout: 15))
        keepScreenshot(of: app, named: "k06-not-found")
    }

    @MainActor
    func testLateAndUnderFilledCardsOpen() throws {
        let app = try launch()
        app.terminate()
        let day = DateFormatter()
        day.locale = Locale(identifier: "en_US_POSIX")
        day.timeZone = TimeZone(identifier: "Asia/Seoul")
        day.dateFormat = "yyyy-MM-dd"
        app.launchEnvironment["ROUNDUP_K06_AT"] = "\(day.string(from: .now))T18:30:00+09:00"
        app.launch()
        let late = app.buttons.matching(NSPredicate(format: "identifier BEGINSWITH 'k06.late.'")).firstMatch
        XCTAssertTrue(scrollTo(late, in: app))
        XCTAssertTrue(late.label.contains("4시간 30분"), late.label)
        keepScreenshot(of: app, named: "k06-today-cards")
        late.tap()
        XCTAssertTrue(app.buttons["k06.noShow"].waitForExistence(timeout: 10))
        XCTAssertTrue(element(labelled: "4시간 30분", in: app).exists)
        keepScreenshot(of: app, named: "k06-late")
        app.navigationBars.buttons.firstMatch.tap()
        let small = app.buttons["k06.underMin.session-k06-small"]
        XCTAssertTrue(scrollTo(small, in: app))
        small.tap()
        XCTAssertTrue(app.buttons["k06.underMin.decide"].waitForExistence(timeout: 10))
        XCTAssertTrue(element(labelled: "수업을 어떻게 할까요", in: app).exists)
        keepScreenshot(of: app, named: "k06-under-min")
    }

    @MainActor
    func testRulesStartEmptyAndAreSavedAsTheFirstVersion() throws {
        let app = try launchEmptyServer()
        app.tabBars.buttons["설정"].tap()
        let row = app.buttons["settings.k06Policy"]
        XCTAssertTrue(scrollTo(row, in: app))
        row.tap()
        XCTAssertTrue(element(labelled: "아직 만들어 둔 규정이 없어요", in: app).waitForExistence(timeout: 10))
        keepScreenshot(of: app, named: "k06-policy-empty")
        let start = app.buttons["k06.policy.start"]
        start.tap()
        waitUntilCovered(start)
        let editor = app.descendants(matching: .any)["k06.policy.text"].firstMatch
        XCTAssertTrue(editor.waitForExistence(timeout: 10))
        editor.tap()
        editor.typeText("3일 전까지 전액 환불, 2일 전 50%, 당일 환불 불가. 15분 넘게 늦으면 노쇼")
        let extract = app.buttons["k06.policy.extract"]
        XCTAssertTrue(scrollTo(extract, in: app))
        extract.tap()
        XCTAssertTrue(element(labelled: "전액 환불", in: app).waitForExistence(timeout: 15))
        keepScreenshot(of: app, named: "k06-policy-table")
        let save = app.buttons["k06.policy.save"]
        XCTAssertTrue(scrollTo(save, in: app))
        save.tap()
        XCTAssertTrue(element(labelled: "현재 1번째 규정", in: app).waitForExistence(timeout: 10))
        keepScreenshot(of: app, named: "k06-policy-saved")
    }
}
