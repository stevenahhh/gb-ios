import XCTest

/// The owner's feedback on 오늘, against a local server seeded with seed.py, b_k06_seed.py and work left from earlier days.
final class TodayFeedbackUITests: RoundupUITestCase {
    private let approveGroup = "approval.approve.inquiry.inquiry-group"
    private let editGroup = "approval.edit.inquiry.inquiry-group"
    private let undoGroup = "approval.undo.inquiry.inquiry-group"

    override func setUpWithError() throws {
        continueAfterFailure = false
    }

    // MARK: Helpers

    /// Opens 오늘 on 할 일 with nothing hidden, whatever an earlier run left on the device.
    @MainActor
    private func openToday() throws -> XCUIApplication {
        let app = try launch()
        showTasksWithNothingHidden(in: app)
        return app
    }

    @MainActor
    private func showTasksWithNothingHidden(in app: XCUIApplication) {
        let tasks = todaySegment("tasks", in: app)
        XCTAssertTrue(tasks.waitForExistence(timeout: 20), "the 오늘 tabs are missing")
        tasks.tap()
        XCTAssertTrue(header(in: app).waitForExistence(timeout: 20), "확인해 주실 일 did not load")
        for identifier in ["attention.restore", "today.metrics.restore"] {
            let restore = app.buttons[identifier].firstMatch
            if restore.exists, scrollTo(restore, in: app) {
                restore.tap()
                XCTAssertTrue(restore.waitForNonExistence(timeout: 10))
            }
        }
        scrollToTop(app)
    }

    @MainActor
    private func waitUntil(_ what: String, timeout: TimeInterval = 10, _ condition: @escaping @MainActor () -> Bool) {
        let predicate = NSPredicate { _, _ in MainActor.assumeIsolated { condition() } }
        let expectation = XCTNSPredicateExpectation(predicate: predicate, object: nil)
        XCTAssertEqual(XCTWaiter().wait(for: [expectation], timeout: timeout), .completed, what)
    }

    @MainActor
    private func scrollToTop(_ app: XCUIApplication) {
        for _ in 0..<6 { app.swipeDown() }
    }

    /// Rows are lazy, so absence counts only after the whole list has been on screen.
    @MainActor
    private func appearsWhileScrolling(_ target: XCUIElement, in app: XCUIApplication) -> Bool {
        for _ in 0..<8 {
            if target.exists { return true }
            app.swipeUp()
        }
        return target.exists
    }

    @MainActor
    private func header(in app: XCUIApplication) -> XCUIElement {
        app.descendants(matching: .any).matching(NSPredicate(format: "label BEGINSWITH %@", "확인해 주실 일 ")).firstMatch
    }

    @MainActor
    private func headerCount(in app: XCUIApplication) -> Int? {
        let title = header(in: app)
        guard title.exists, let match = title.label.firstMatch(of: /확인해 주실 일 (\d+)건/) else { return nil }
        return Int(match.1)
    }

    @MainActor
    private func greetingCount(in app: XCUIApplication) -> Int? {
        let line = element(labelled: "확인할 요청이", in: app)
        guard line.exists, let match = line.label.firstMatch(of: /확인할 요청이 (\d+)건 있어요!/) else { return nil }
        return Int(match.1)
    }

    @MainActor
    private func cell(holding identifier: String, in app: XCUIApplication) -> XCUIElement {
        app.cells.containing(.button, identifier: identifier).firstMatch
    }

    @MainActor
    private func hide(_ row: XCUIElement, in app: XCUIApplication) {
        row.swipeLeft()
        let action = app.buttons["숨기기"].firstMatch
        XCTAssertTrue(action.waitForExistence(timeout: 5), "swiping offers no 숨기기")
        action.tap()
    }

    @MainActor
    private func brandImages(in app: XCUIApplication) -> [XCUIElement] {
        let format = "label == %@ OR identifier == %@ OR label ==[c] %@ OR identifier ==[c] %@"
        return app.images.matching(NSPredicate(format: format, "공도리", "today.brand", "brandMark", "brandMark"))
            .allElementsBoundByIndex
    }

    // MARK: Greeting

    @MainActor
    func testTitleGreetsTheWorkshopByName() throws {
        let app = try openToday()
        let title = app.navigationBars.matching(NSPredicate(format: "identifier ENDSWITH %@", "님 반갑습니다.")).firstMatch
        XCTAssertTrue(title.waitForExistence(timeout: 10))
        XCTAssertTrue(title.identifier.contains("오롯 공방"), "the seeded shop has no owner name: \(title.identifier)")
    }

    @MainActor
    func testChangingLineCountsTheSameWorkAsTheHeader() throws {
        let app = try openToday()
        waitUntil("the greeting line and the header show different counts") { [self] in
            guard let count = headerCount(in: app), count > 0 else { return false }
            return greetingCount(in: app) == count
        }
        let line = element(labelled: "확인할 요청이", in: app).label
        XCTAssertNotNil(line.firstMatch(of: /좋은 (아침|오후|저녁)입니다/), "no time-of-day greeting: \(line)")
    }

    @MainActor
    func testTitleDoesNotNameUnsentParcels() throws {
        let app = try openToday()
        XCTAssertTrue(app.navigationBars.firstMatch.waitForExistence(timeout: 10))
        XCTAssertFalse(element(labelled: "못 보낸 택배", in: app).exists)
    }

    @MainActor
    func testEmptyServerSaysThereAreNoRequests() throws {
        let app = try launchEmptyServer()
        XCTAssertTrue(element(labelled: "확인할 요청이 없어요", in: app).waitForExistence(timeout: 20))
        XCTAssertNil(greetingCount(in: app))
    }

    // MARK: Tabs

    @MainActor
    func testSegmentBarSitsAboveAttention() throws {
        let app = try openToday()
        let frames = ["tasks", "channels", "delivery", "suggestions"].map { todaySegment($0, in: app).frame }
        let top = header(in: app).frame.minY
        for frame in frames {
            XCTAssertFalse(frame.isEmpty)
            XCTAssertLessThanOrEqual(frame.maxY, top, "확인해 주실 일 is not under the tabs")
        }
    }

    @MainActor
    func testSegmentBarStaysVisibleAfterScrolling() throws {
        let app = try openToday()
        let title = header(in: app)
        let before = title.frame.minY
        app.swipeUp()
        app.swipeUp()
        waitUntil("the list did not scroll") { !title.exists || title.frame.minY < before }
        for name in ["tasks", "channels", "delivery", "suggestions"] {
            XCTAssertTrue(todaySegment(name, in: app).isHittable, "\(name) scrolled away")
        }
        todaySegment("delivery", in: app).tap()
        waitUntil("the pinned tab does not switch") { [self] in todaySegment("delivery", in: app).isSelected }
        todaySegment("tasks", in: app).tap()
    }

    @MainActor
    func testSegmentSelectionIsKeptAfterRelaunch() throws {
        var app = try openToday()
        todaySegment("delivery", in: app).tap()
        waitUntil("배송 was not selected") { [self, app] in todaySegment("delivery", in: app).isSelected }
        // The scene saves its state when it leaves the screen, so a kill must follow the home screen.
        XCUIDevice.shared.press(.home)
        XCTAssertTrue(app.wait(for: .runningBackground, timeout: 10) || app.state == .runningBackgroundSuspended)
        app.terminate()
        app = try launch()
        let delivery = todaySegment("delivery", in: app)
        XCTAssertTrue(delivery.waitForExistence(timeout: 20))
        XCTAssertTrue(delivery.isSelected, "the chosen tab was lost")
        todaySegment("tasks", in: app).tap()
    }

    // MARK: Rows

    @MainActor
    func testRowButtonsSitToTheRightOfTheTitle() throws {
        let app = try openToday()
        let approve = app.buttons[approveGroup], edit = app.buttons[editGroup]
        XCTAssertTrue(scrollTo(approve, in: app))
        let title = app.staticTexts["두 사람 함께 참여"].firstMatch
        let titleFrame = title.exists ? title.frame : app.buttons["inquiry.inquiry-group"].frame
        for button in [approve, edit] {
            XCTAssertGreaterThanOrEqual(button.frame.minX, titleFrame.maxX - 1, "\(button.label) is not right of the title")
        }
        let row = cell(holding: approveGroup, in: app).frame
        XCTAssertTrue(row.insetBy(dx: -1, dy: -1).contains(approve.frame) && row.insetBy(dx: -1, dy: -1).contains(edit.frame))
        XCTAssertEqual(approve.frame.midY, edit.frame.midY, accuracy: 2, "the two buttons are not side by side")
        keepScreenshot(of: app, named: "today-attention-rows")
    }

    @MainActor
    func testRowIsLow() throws {
        let app = try openToday()
        XCTAssertTrue(scrollTo(app.buttons[approveGroup], in: app))
        XCTAssertLessThan(cell(holding: approveGroup, in: app).frame.height, 100)
    }

    @MainActor
    func testRowButtonsKeepTheirTapTargets() throws {
        let app = try openToday()
        for identifier in [approveGroup, editGroup] {
            let button = app.buttons[identifier]
            XCTAssertTrue(scrollTo(button, in: app))
            XCTAssertGreaterThanOrEqual(button.frame.height, 44, identifier)
            XCTAssertGreaterThanOrEqual(button.frame.width, 44, identifier)
        }
    }

    @MainActor
    func testApprovalShowsOnlyUndoAndTheStoreThenUndoRestores() throws {
        let app = try openToday()
        let approve = app.buttons[approveGroup]
        XCTAssertTrue(scrollTo(approve, in: app))
        approve.tap()
        let undo = app.buttons[undoGroup]
        XCTAssertTrue(undo.waitForExistence(timeout: 15))
        let row = cell(holding: undoGroup, in: app)
        XCTAssertTrue(row.descendants(matching: .any)["draft.open"].firstMatch.exists)
        XCTAssertTrue(row.descendants(matching: .any).matching(
            NSPredicate(format: "label CONTAINS %@", "네이버 스마트스토어 열기")).firstMatch.exists)
        XCTAssertFalse(element(labelled: "답변 복사하기", in: app).exists)
        XCTAssertFalse(app.buttons["draft.copy"].exists)
        XCTAssertFalse(app.buttons[approveGroup].exists)
        XCTAssertFalse(app.buttons[editGroup].exists)
        keepScreenshot(of: app, named: "today-approved-row")
        undo.tap()
        XCTAssertTrue(approve.waitForExistence(timeout: 15), "undo did not bring 승인 back")
        XCTAssertTrue(undo.waitForNonExistence(timeout: 10))
    }

    // MARK: Work left from earlier days

    @MainActor
    func testOverdueQuestionsSayWhichDayTheyAreAbout() throws {
        let app = try openToday()
        for question in ["어제 하지 못한 일을 오늘 할 일에 넣을까요?", "지난 일을 오늘 할 일에 넣을까요?"] {
            XCTAssertTrue(revealAttention(element(labelled: question, in: app), in: app), "\(question) is missing")
        }
    }

    @MainActor
    func testApprovingTheOverdueQuestionMovesItsWorkAndUndoBringsItBack() throws {
        let app = try openToday()
        let task = app.buttons["task.task-tf-overdue-a"]
        XCTAssertFalse(appearsWhileScrolling(task, in: app), "left-over work is in 할 일 before the owner approves")
        scrollToTop(app)
        let approve = app.buttons["carryover.approve.carryover.yesterday"]
        let undo = app.buttons["carryover.undo.carryover.yesterday"]
        XCTAssertTrue(revealAttention(approve, in: app))
        approve.tap()
        XCTAssertTrue(undo.waitForExistence(timeout: 15))
        XCTAssertFalse(approve.exists)
        leaveAttentionList(app)
        XCTAssertTrue(appearsWhileScrolling(task, in: app), "the approved work is not in 할 일")
        scrollToTop(app)
        XCTAssertTrue(revealAttention(undo, in: app))
        undo.tap()
        XCTAssertTrue(approve.waitForExistence(timeout: 15), "undo did not bring the question back")
        leaveAttentionList(app)
        XCTAssertFalse(appearsWhileScrolling(task, in: app), "undone work stayed in 할 일")
    }

    @MainActor
    func testTasksHaveNoOverdueHeader() throws {
        let app = try openToday()
        XCTAssertFalse(appearsWhileScrolling(element(labelled: "기한 지난 일", in: app), in: app))
    }

    /// 모두 보기 pushes a list, so the steps after it need 오늘 itself.
    @MainActor
    private func leaveAttentionList(_ app: XCUIApplication) {
        let list = app.navigationBars["확인해 주실 일"]
        guard list.exists else { return }
        list.buttons.element(boundBy: 0).tap()
        XCTAssertTrue(list.waitForNonExistence(timeout: 10))
    }

    // MARK: Hiding

    @MainActor
    func testSwipingHidesARowAndRestoreBringsItBack() throws {
        let app = try openToday()
        waitUntil("확인해 주실 일 has no count") { [self] in headerCount(in: app) != nil }
        let before = try XCTUnwrap(headerCount(in: app))
        let approve = app.buttons[approveGroup]
        XCTAssertTrue(scrollTo(approve, in: app))
        hide(cell(holding: approveGroup, in: app), in: app)
        XCTAssertTrue(approve.waitForNonExistence(timeout: 10))
        scrollToTop(app)
        waitUntil("a hidden row is still counted") { [self] in headerCount(in: app) == before - 1 }
        let restore = app.buttons["attention.restore"].firstMatch
        XCTAssertTrue(scrollTo(restore, in: app))
        restore.tap()
        scrollToTop(app)
        XCTAssertTrue(scrollTo(approve, in: app), "restore did not bring the row back")
        scrollToTop(app)
        waitUntil("the restored row is not counted") { [self] in headerCount(in: app) == before }
    }

    @MainActor
    func testSwipingHidesTheMetricStripAndRestoreBringsItBack() throws {
        let app = try openToday()
        let metrics = app.descendants(matching: .any)["today.metrics"].firstMatch
        XCTAssertTrue(metrics.waitForExistence(timeout: 10))
        hide(metrics, in: app)
        XCTAssertTrue(metrics.waitForNonExistence(timeout: 10))
        let restore = app.buttons["today.metrics.restore"].firstMatch
        XCTAssertTrue(scrollTo(restore, in: app))
        restore.tap()
        scrollToTop(app)
        XCTAssertTrue(metrics.waitForExistence(timeout: 10))
        XCTAssertTrue(restore.waitForNonExistence(timeout: 10))
    }

    // MARK: Cancellation and no-show

    @MainActor
    func testTodayHasNoCancellationHeader() throws {
        let app = try openToday()
        XCTAssertFalse(appearsWhileScrolling(app.staticTexts["취소·노쇼"], in: app))
    }

    @MainActor
    func testPasteCancellationIsReachable() throws {
        let app = try openToday()
        let row = app.buttons["k06.paste"]
        XCTAssertTrue(scrollTo(row, in: app))
        row.tap()
        XCTAssertTrue(app.descendants(matching: .any)["k06.message"].firstMatch.waitForExistence(timeout: 10))
    }

    @MainActor
    func testAttendanceIsReachable() throws {
        let app = try openToday()
        let row = app.buttons["k06.sessions"]
        XCTAssertTrue(scrollTo(row, in: app))
        row.tap()
        let session = app.descendants(matching: .any).matching(NSPredicate(format: "identifier BEGINSWITH %@", "k06.session."))
        XCTAssertTrue(session.firstMatch.waitForExistence(timeout: 10))
    }

    @MainActor
    func testLateGuestIsReachable() throws {
        let app = try launch()
        app.terminate()
        let day = DateFormatter()
        day.locale = Locale(identifier: "en_US_POSIX")
        day.timeZone = TimeZone(identifier: "Asia/Seoul")
        day.dateFormat = "yyyy-MM-dd"
        app.launchEnvironment["ROUNDUP_K06_AT"] = "\(day.string(from: .now))T18:30:00+09:00"
        app.launch()
        showTasksWithNothingHidden(in: app)
        let late = app.buttons.matching(NSPredicate(format: "identifier BEGINSWITH %@", "k06.late.")).firstMatch
        XCTAssertTrue(revealAttention(late, in: app))
        late.tap()
        XCTAssertTrue(app.buttons["k06.noShow"].waitForExistence(timeout: 10))
    }

    // MARK: Brand and chat

    @MainActor
    func testBrandIsAtTheTopLeft() throws {
        let app = try openToday()
        let brand = app.images["today.brand"]
        XCTAssertTrue(brand.waitForExistence(timeout: 10))
        XCTAssertLessThan(brand.frame.midX, app.frame.width / 4)
        XCTAssertLessThan(brand.frame.maxY, todaySegment("tasks", in: app).frame.minY)
        XCTAssertEqual(brandImages(in: app).count, 1)
    }

    @MainActor
    func testBrandIsNotBesideAssistantText() throws {
        let app = try openToday()
        let row = app.buttons["inquiry.inquiry-group"]
        XCTAssertTrue(scrollTo(row, in: app))
        row.tap()
        XCTAssertTrue(app.textViews["inquiry.draft"].waitForExistence(timeout: 15))
        XCTAssertTrue(brandImages(in: app).isEmpty, "the logo is beside the assistant's reply")
        app.navigationBars.buttons.element(boundBy: 0).tap()

        let accessory = app.buttons["assistant.accessory"]
        XCTAssertTrue(accessory.waitForExistence(timeout: 10))
        accessory.tap()
        let bar = app.navigationBars["비서"]
        XCTAssertTrue(bar.waitForExistence(timeout: 10))
        // 오늘 can stay in the tree behind the sheet, so only what the sheet itself draws counts.
        XCTAssertTrue(brandImages(in: app).allSatisfy { $0.frame.minY < bar.frame.minY }, "the logo is in the chat")
    }

    @MainActor
    func testChatEntryInvitesTyping() throws {
        let app = try openToday()
        let accessory = app.buttons["assistant.accessory"]
        XCTAssertTrue(accessory.waitForExistence(timeout: 10))
        XCTAssertEqual(accessory.label, "채팅하기")
        XCTAssertFalse(element(labelled: "비서에게 맡기기", in: app).exists)
    }

    @MainActor
    func testTabBarMinimizesWithTheChatEntryAndReturns() throws {
        let app = try openToday()
        let accessory = app.buttons["assistant.accessory"]
        let settings = app.tabBars.buttons["설정"]
        XCTAssertTrue(accessory.waitForExistence(timeout: 10))
        XCTAssertTrue(settings.waitForExistence(timeout: 10))
        let restingY = accessory.frame.midY
        XCTAssertLessThan(restingY, settings.frame.minY, "the chat entry does not start above the tab bar")

        app.swipeUp()
        waitUntil("the tab bar did not minimize") { !settings.exists || !settings.isHittable }
        waitUntil("the chat entry did not move into the tab bar") { accessory.exists && accessory.frame.midY > restingY + 20 }
        XCTAssertTrue(accessory.isHittable)
        keepScreenshot(of: app, named: "today-tabbar-minimized")

        app.swipeDown()
        waitUntil("the tab bar did not return") { settings.exists && settings.isHittable }
        waitUntil("the chat entry did not move back") { accessory.exists && abs(accessory.frame.midY - restingY) < 4 }
    }
}
