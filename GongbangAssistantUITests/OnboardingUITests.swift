import XCTest

final class OnboardingUITests: RoundupUITestCase {
    /// Starts as a first launch: the flow's saved keys are cleared as the app starts.
    @MainActor
    private func firstLaunch() throws -> XCUIApplication {
        let app = try launch()
        app.terminate()
        app.launchArguments = ["-onboarding.reset", "YES"]
        app.launch()
        return app
    }

    @MainActor
    private func page(_ number: Int, in app: XCUIApplication) -> XCUIElement {
        app.descendants(matching: .any)["onboarding.progress.\(number)"].firstMatch
    }

    /// Opens the flow as a first launch and puts pages off until `number` is on screen.
    @MainActor
    private func open(page number: Int) throws -> XCUIApplication {
        let app = try firstLaunch()
        XCTAssertTrue(page(1, in: app).waitForExistence(timeout: 30))
        app.buttons.matching(NSPredicate(format: "label == %@ OR label == %@", "시작하기", "다음")).firstMatch.tap()
        for passed in 2..<number {
            XCTAssertTrue(page(passed, in: app).waitForExistence(timeout: 15), "page \(passed)")
            app.buttons["onboarding.later"].tap()
        }
        XCTAssertTrue(page(number, in: app).waitForExistence(timeout: 15))
        return app
    }

    @MainActor
    private func service(_ id: String, in app: XCUIApplication) -> XCUIElement {
        app.descendants(matching: .any)["connections.row.\(id)"].firstMatch
    }

    @MainActor
    private func type(_ value: String, into id: String, in app: XCUIApplication) {
        let row = service(id, in: app)
        XCTAssertTrue(scrollTo(row, in: app), "\(id) row is missing")
        row.tap()
        let field = app.textFields["connections.edit.field"]
        XCTAssertTrue(field.waitForExistence(timeout: 10))
        field.tap()
        field.typeText(value)
        app.buttons["connections.edit.save"].tap()
    }

    @MainActor
    private func waitFor(_ element: XCUIElement, toShow text: String) -> Bool {
        let shown = XCTNSPredicateExpectation(
            predicate: NSPredicate(format: "label CONTAINS %@", text), object: element)
        return XCTWaiter.wait(for: [shown], timeout: 15) == .completed
    }

    @MainActor
    func testSavingAServiceShowsItSavedAndNeverConnected() throws {
        let app = try open(page: 3)
        type("Nolli_Blog", into: "naver_blog", in: app)
        let row = service("naver_blog", in: app)
        XCTAssertTrue(waitFor(row, toShow: "저장됨"))
        XCTAssertTrue(row.label.contains("nolli_blog"), "the row shows the value the server normalised")
        XCTAssertFalse(row.label.contains("연결됨"))
        keepScreenshot(of: app, named: "onboarding-service-saved")
    }

    @MainActor
    func testARefusedServiceValueShowsTheServersReason() throws {
        let app = try open(page: 3)
        // The device's own check lets this through; only the server knows two periods in a row are refused.
        type("my..workshop", into: "instagram", in: app)
        let problem = app.descendants(matching: .any)["connections.edit.problem"].firstMatch
        XCTAssertTrue(problem.waitForExistence(timeout: 15))
        XCTAssertTrue(waitFor(problem, toShow: "아이디가 좀 이상해요. 한 번 더 봐 주세요."), problem.label)
        keepScreenshot(of: app, named: "onboarding-service-refused")
    }

    @MainActor
    func testDeletingAServiceInTheFlowOffersAnUndoThatBringsItBack() throws {
        let app = try open(page: 3)
        type("https://pf.kakao.com/_nolli", into: "kakao_channel", in: app)
        let row = service("kakao_channel", in: app)
        XCTAssertTrue(waitFor(row, toShow: "저장됨"))
        row.swipeLeft()
        app.buttons["지우기"].tap()
        let undo = app.buttons["toast.undo"]
        XCTAssertTrue(undo.waitForExistence(timeout: 10))
        keepScreenshot(of: app, named: "onboarding-service-deleted")
        XCTAssertTrue(undo.isHittable, "the undo is above the cover")
        XCTAssertFalse(row.label.contains("저장됨"))
        undo.tap()
        XCTAssertTrue(waitFor(row, toShow: "pf.kakao.com/_nolli"))
        XCTAssertTrue(row.label.contains("저장됨"))
    }

    @MainActor
    func testChoosingAPlanKeepsItAndSaysNothingIsPaid() throws {
        let app = try open(page: 5)
        let option = app.buttons["plan.option.none"]
        XCTAssertTrue(scrollTo(option, in: app))
        option.tap()
        XCTAssertTrue(option.isSelected)
        XCTAssertTrue(element(labelled: "아직 결제되지 않아요", in: app).exists)
        keepScreenshot(of: app, named: "onboarding-plan-chosen")
        app.buttons["이걸로 할게요"].tap()
        XCTAssertTrue(page(6, in: app).waitForExistence(timeout: 15))
        app.buttons["onboarding.skipAll"].tap()
        XCTAssertTrue(app.tabBars.buttons["설정"].waitForExistence(timeout: 20))
        app.tabBars.buttons["설정"].tap()
        let row = app.descendants(matching: .any)["settings.plan"].firstMatch
        XCTAssertTrue(scrollTo(row, in: app))
        XCTAssertTrue(waitFor(row, toShow: "요금제 없이"), row.label)
    }

    @MainActor
    func testTheTutorialRunsToItsEndAndDoesNotComeBack() throws {
        let app = try open(page: 6)
        app.buttons["onboarding.tutorial.start"].tap()
        let sentence = app.descendants(matching: .any)["tutorial.sentence"].firstMatch
        XCTAssertTrue(sentence.waitForExistence(timeout: 20))
        keepScreenshot(of: app, named: "tutorial-first")
        var seen: [String] = []
        // Six stops; one whose element is not on screen drops out, so the run may show fewer.
        while sentence.exists, seen.count <= 6 {
            let current = sentence.label
            XCTAssertFalse(seen.contains(current), current)
            seen.append(current)
            app.buttons["tutorial.next"].tap()
            let moved = XCTNSPredicateExpectation(
                predicate: NSPredicate(format: "exists == 1 AND label != %@", current), object: sentence)
            _ = XCTWaiter.wait(for: [moved], timeout: 8)
        }
        XCTAssertGreaterThanOrEqual(seen.count, 3)
        XCTAssertFalse(app.buttons["tutorial.next"].exists)
        XCTAssertTrue(app.tabBars.buttons["오늘"].isHittable)
        app.terminate()
        app.launchArguments = []
        app.launch()
        XCTAssertTrue(app.tabBars.buttons["오늘"].waitForExistence(timeout: 30))
        XCTAssertFalse(sentence.waitForExistence(timeout: 5))
    }

    @MainActor
    func testFirstLaunchShowsTheFlowAndSkippingOpensToday() throws {
        let app = try firstLaunch()
        XCTAssertTrue(page(1, in: app).waitForExistence(timeout: 30))
        keepScreenshot(of: app, named: "onboarding-1-welcome")
        app.buttons["onboarding.skipAll"].tap()
        XCTAssertTrue(app.tabBars.buttons["오늘"].waitForExistence(timeout: 20))
        XCTAssertFalse(page(1, in: app).exists)
    }

    @MainActor
    func testEveryStepCanBePutOffAndTheLastOneEndsTheFlow() throws {
        let app = try firstLaunch()
        XCTAssertTrue(page(1, in: app).waitForExistence(timeout: 30))
        app.buttons.matching(NSPredicate(format: "label == %@ OR label == %@", "시작하기", "다음")).firstMatch.tap()
        for number in 2...5 {
            XCTAssertTrue(page(number, in: app).waitForExistence(timeout: 15), "page \(number)")
            keepScreenshot(of: app, named: "onboarding-\(number)")
            app.buttons["onboarding.later"].tap()
        }
        XCTAssertTrue(page(6, in: app).waitForExistence(timeout: 15))
        keepScreenshot(of: app, named: "onboarding-6-tutorial")
        app.buttons["onboarding.tutorial.later"].tap()
        XCTAssertTrue(app.tabBars.buttons["오늘"].waitForExistence(timeout: 20))
    }

    @MainActor
    func testTheFlowResumesOnThePageTheOwnerLeft() throws {
        let app = try firstLaunch()
        XCTAssertTrue(page(1, in: app).waitForExistence(timeout: 30))
        app.buttons.matching(NSPredicate(format: "label == %@ OR label == %@", "시작하기", "다음")).firstMatch.tap()
        XCTAssertTrue(page(2, in: app).waitForExistence(timeout: 15))
        app.terminate()
        app.launchArguments = []
        app.launch()
        XCTAssertTrue(page(2, in: app).waitForExistence(timeout: 30))
        app.buttons["onboarding.back"].tap()
        XCTAssertTrue(page(1, in: app).waitForExistence(timeout: 10))
    }

    @MainActor
    func testSettingsReplaysTheFlow() throws {
        let app = try launch()
        app.tabBars.buttons["설정"].tap()
        let row = app.buttons["settings.onboarding"]
        XCTAssertTrue(scrollTo(row, in: app))
        row.tap()
        XCTAssertTrue(page(1, in: app).waitForExistence(timeout: 15))
    }
}
