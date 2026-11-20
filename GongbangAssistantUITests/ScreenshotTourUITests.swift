import XCTest

final class ScreenshotTourUITests: RoundupUITestCase {
    private var app: XCUIApplication!
    private var index = 0

    override func setUpWithError() throws {
        continueAfterFailure = true
    }

    @MainActor
    func testCaptureEveryScreen() throws {
        app = try launch()

        selectTab("오늘")
        XCTAssertTrue(app.segmentedControls.firstMatch.waitForExistence(timeout: 10))
        for segment in ["할 일", "채널", "배송", "비서 추천"] {
            selectSegment(segment, menu: "today.segment")
            capture("today-\(segment)")
            scrollToEnd()
            capture("today-\(segment)-end")
            scrollToTop()
        }
        selectSegment("할 일", menu: "today.segment")

        selectTab("캘린더")
        XCTAssertTrue(app.buttons["calendar.mode.week"].waitForExistence(timeout: 10))
        capture("calendar-week")
        scrollToEnd()
        capture("calendar-week-end")
        scrollToTop()
        app.buttons["calendar.mode.month"].tap()
        capture("calendar-month")
        tapIfExists(app.buttons.matching(NSPredicate(format: "label CONTAINS '9'")).firstMatch)
        scrollToEnd()
        capture("calendar-month-end")
        scrollToTop()
        app.buttons["calendar.mode.week"].tap()

        selectTab("운영")
        // The work-area rows sit below the fold now, and List creates them only when scrolled into view.
        XCTAssertTrue(app.buttons["operations.period"].waitForExistence(timeout: 10))
        capture("operations")
        scrollToEnd()
        capture("operations-end")
        scrollToTop()
        for area in ["bookings", "orders", "deliveries", "channels"] {
            let row = app.buttons["operations.\(area)"]
            guard reveal(row) else { continue }
            row.tap()
            waitForPush(from: "운영")
            capture("operations-\(area)")
            scrollToEnd()
            capture("operations-\(area)-end")
            goBack()
            scrollToTop()
        }

        let deliveries = app.buttons["operations.deliveries"]
        if reveal(deliveries) {
            deliveries.tap()
            waitForPush(from: "운영")
            selectSegment("완료", menu: "area.filter")
            capture("operations-deliveries-filter-done")
            selectSegment("전체", menu: "area.filter")
            let search = app.searchFields.firstMatch
            if search.waitForExistence(timeout: 3) {
                search.tap()
                search.typeText("없는주문")
                capture("operations-deliveries-search-empty")
                app.terminate()
                app = try launch()
            } else {
                goBack()
            }
        }

        selectTab("설정")
        capture("settings")
        scrollToEnd()
        capture("settings-end")
        scrollToTop()
        let firstRow = app.buttons["settings.workshop"].firstMatch
        XCTAssertTrue(firstRow.waitForExistence(timeout: 10))
        if reveal(firstRow) {
            firstRow.tap()
            waitForPush(from: "설정")
            capture("settings-workshop")
            goBack()
        } else {
            XCTFail("settings row 공방 정보 was not reachable")
        }

        selectTab("오늘")
        let accessory = app.buttons["assistant.accessory"]
        if accessory.waitForExistence(timeout: 5) {
            accessory.tap()
            capture("assistant-sheet")
        }
    }

    @MainActor
    func testCaptureEmptyAndErrorStates() throws {
        app = try launchEmptyServer()
        XCTAssertTrue(app.descendants(matching: .any)["today.empty"].waitForExistence(timeout: 10))
        capture("state-empty-today")
        selectTab("운영")
        let row = app.buttons["operations.bookings"]
        XCTAssertTrue(row.waitForExistence(timeout: 10))
        if reveal(row) {
            row.tap()
            waitForPush(from: "운영")
            XCTAssertTrue(app.descendants(matching: .any)["area.empty"].waitForExistence(timeout: 10))
            capture("state-empty-bookings")
        }
        app.terminate()

        app = try launch(apiURL: "http://127.0.0.1:9")
        XCTAssertTrue(app.buttons["screen.retry"].waitForExistence(timeout: 30))
        capture("state-error-today")
        app.terminate()
    }

    @MainActor
    private func selectTab(_ label: String) {
        let barButton = app.tabBars.buttons[label]
        if barButton.waitForExistence(timeout: 3) {
            barButton.tap()
        } else {
            app.buttons[label].firstMatch.tap()
        }
    }

    @MainActor
    private func selectSegment(_ label: String, menu identifier: String? = nil) {
        let segment = app.segmentedControls.buttons[label].firstMatch
        if segment.waitForExistence(timeout: 3) {
            segment.tap()
            return
        }
        guard let identifier else { return }
        let trigger = app.buttons[identifier].firstMatch
        guard trigger.waitForExistence(timeout: 3) else { return }
        trigger.tap()
        let item = app.buttons[label].firstMatch
        if item.waitForExistence(timeout: 3) {
            item.tap()
        }
    }

    @MainActor
    private func reveal(_ element: XCUIElement) -> Bool {
        for _ in 0..<8 {
            if element.exists && element.isHittable { return true }
            app.swipeUp()
        }
        return element.exists && element.isHittable
    }

    @MainActor
    private func tapIfExists(_ element: XCUIElement) {
        if element.waitForExistence(timeout: 2) { element.tap() }
    }

    @MainActor
    private func scrollToEnd() {
        for _ in 0..<6 { app.swipeUp() }
    }

    @MainActor
    private func scrollToTop() {
        for _ in 0..<6 { app.swipeDown() }
    }

    @MainActor
    private func waitForPush(from parentTitle: String) {
        XCTAssertTrue(app.navigationBars[parentTitle].waitForNonExistence(timeout: 5), "push from \(parentTitle) did not finish")
    }

    @MainActor
    private func goBack() {
        let backButton = app.navigationBars.buttons.element(boundBy: 0)
        if backButton.exists { backButton.tap() }
    }

    @MainActor
    private func capture(_ name: String) {
        index += 1
        let attachment = XCTAttachment(screenshot: app.screenshot())
        attachment.name = String(format: "%02d-%@", index, name)
        attachment.lifetime = .keepAlways
        add(attachment)
    }
}
