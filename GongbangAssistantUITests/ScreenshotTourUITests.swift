import XCTest

final class ScreenshotTourUITests: XCTestCase {
    private var app: XCUIApplication!
    private var index = 0

    override func setUpWithError() throws {
        continueAfterFailure = true
    }

    @MainActor
    func testCaptureEveryScreen() throws {
        app = XCUIApplication()
        app.launch()

        selectTab("오늘")
        for segment in ["할 일", "채널", "배송", "비서 추천"] {
            selectSegment(segment, menu: "today.segment")
            capture("today-\(segment)")
            scrollToEnd()
            capture("today-\(segment)-end")
            scrollToTop()
        }
        selectSegment("할 일", menu: "today.segment")

        selectTab("캘린더")
        capture("calendar-week")
        scrollToEnd()
        capture("calendar-week-end")
        scrollToTop()
        selectSegment("월간", menu: "calendar.mode")
        capture("calendar-month")
        tapIfExists(app.buttons.matching(NSPredicate(format: "label CONTAINS '9'")).firstMatch)
        scrollToEnd()
        capture("calendar-month-end")
        scrollToTop()
        selectSegment("주간", menu: "calendar.mode")

        selectTab("운영")
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
                app.launch()
            } else {
                goBack()
            }
        }

        selectTab("설정")
        capture("settings")
        scrollToEnd()
        capture("settings-end")
        scrollToTop()
        let firstRow = app.buttons["공방 정보"].firstMatch
        _ = firstRow.waitForExistence(timeout: 5)
        if reveal(firstRow) {
            firstRow.tap()
            waitForPush(from: "설정")
            capture("settings-placeholder")
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
    func testCaptureScreenStates() throws {
        for state in ["loading", "empty", "error"] {
            app = XCUIApplication()
            app.launchArguments = ["-screenState", state]
            app.launch()
            selectTab("오늘")
            capture("state-\(state)-today")
            selectTab("캘린더")
            capture("state-\(state)-calendar")
            selectTab("운영")
            let row = app.buttons["operations.bookings"]
            if reveal(row) {
                row.tap()
                waitForPush(from: "운영")
                capture("state-\(state)-bookings")
            }
            app.terminate()
        }
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
