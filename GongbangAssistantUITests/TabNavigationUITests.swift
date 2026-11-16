import XCTest

final class TabNavigationUITests: XCTestCase {
    private let tabs: [(label: String, title: String)] = [
        ("오늘", "사장님, 좋은 아침이에요"),
        ("캘린더", "캘린더"),
        ("운영", "운영"),
        ("더보기", "더보기"),
    ]

    override func setUpWithError() throws {
        continueAfterFailure = false
    }

    @MainActor
    func testEveryTabShowsItsNavigationTitle() throws {
        let app = XCUIApplication()
        app.launch()

        for tab in tabs {
            let button = app.tabBars.buttons[tab.label]
            XCTAssertTrue(button.waitForExistence(timeout: 5), "tab \(tab.label) is missing")
            button.tap()
            XCTAssertTrue(app.navigationBars[tab.title].waitForExistence(timeout: 5), "navigation title \(tab.title) is missing")
            keepScreenshot(of: app, named: "tab-\(tab.label)")
        }
    }

    @MainActor
    func testOperationsPushesAreaScreenAndGoesBack() throws {
        let app = XCUIApplication()
        app.launch()

        app.tabBars.buttons["운영"].tap()
        let bookingsRow = app.buttons["operations.bookings"]
        XCTAssertTrue(bookingsRow.waitForExistence(timeout: 5))
        bookingsRow.tap()

        let detailBar = app.navigationBars["예약 관리"]
        XCTAssertTrue(detailBar.waitForExistence(timeout: 5))
        keepScreenshot(of: app, named: "push-예약 관리")

        let backButton = detailBar.buttons.element(boundBy: 0)
        XCTAssertTrue(backButton.exists)
        backButton.tap()
        XCTAssertTrue(app.navigationBars["운영"].waitForExistence(timeout: 5))
    }

    @MainActor
    func testAssistantAccessoryBelongsToTodayTab() throws {
        let app = XCUIApplication()
        app.launch()

        let accessory = app.buttons["assistant.accessory"]
        XCTAssertTrue(accessory.waitForExistence(timeout: 5))

        app.tabBars.buttons["캘린더"].tap()
        XCTAssertTrue(app.navigationBars["캘린더"].waitForExistence(timeout: 5))
        XCTAssertFalse(accessory.exists)

        app.tabBars.buttons["오늘"].tap()
        XCTAssertTrue(accessory.waitForExistence(timeout: 5))
        accessory.tap()
        XCTAssertTrue(app.navigationBars["비서"].waitForExistence(timeout: 5))
        keepScreenshot(of: app, named: "assistant-sheet")
    }

    @MainActor
    private func keepScreenshot(of app: XCUIApplication, named name: String) {
        let attachment = XCTAttachment(screenshot: app.screenshot())
        attachment.name = name
        attachment.lifetime = .keepAlways
        add(attachment)
    }
}
