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
        for segment in ["오늘 할 일", "SNS·스토어", "배송", "AI 추천"] {
            selectSegment(segment)
            capture("today-\(segment)")
            scrollToEnd()
            capture("today-\(segment)-end")
            scrollToTop()
        }

        selectTab("캘린더")
        capture("calendar-month")
        scrollToEnd()
        capture("calendar-month-end")
        scrollToTop()
        selectSegment("주간")
        capture("calendar-week")
        selectSegment("월간")

        selectTab("운영")
        capture("operations")
        scrollToEnd()
        capture("operations-end")
        scrollToTop()
        for area in ["bookings", "orders", "deliveries", "channels"] {
            let row = app.buttons["operations.\(area)"]
            if !row.exists { scrollToEnd() }
            guard row.waitForExistence(timeout: 5) else { continue }
            row.tap()
            capture("operations-\(area)")
            scrollToEnd()
            capture("operations-\(area)-end")
            goBack()
            scrollToTop()
        }

        selectTab("더보기")
        capture("more")
        scrollToEnd()
        capture("more-end")
        scrollToTop()
        let firstRow = app.buttons["기회"].firstMatch
        if firstRow.waitForExistence(timeout: 5) {
            firstRow.tap()
            capture("more-placeholder")
            goBack()
        }

        selectTab("오늘")
        let accessory = app.buttons["assistant.accessory"]
        if accessory.waitForExistence(timeout: 5) {
            accessory.tap()
            capture("assistant-sheet")
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
    private func selectSegment(_ label: String) {
        let segment = app.segmentedControls.buttons[label].firstMatch
        if segment.waitForExistence(timeout: 3) {
            segment.tap()
        }
    }

    @MainActor
    private func scrollToEnd() {
        for _ in 0..<4 { app.swipeUp() }
    }

    @MainActor
    private func scrollToTop() {
        for _ in 0..<4 { app.swipeDown() }
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
