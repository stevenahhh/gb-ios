import XCTest

final class TabNavigationUITests: XCTestCase {
    private let tabs: [(label: String, titlePrefix: String)] = [
        ("오늘", "사장님"),
        ("캘린더", "캘린더"),
        ("운영", "운영"),
        ("설정", "설정"),
    ]

    override func setUpWithError() throws {
        continueAfterFailure = false
    }

    @MainActor
    func testEveryTabShowsItsNavigationTitle() throws {
        let app = XCUIApplication()
        app.launchArguments += ["-sampleInquiries"]
        app.launch()

        for tab in tabs {
            let button = app.tabBars.buttons[tab.label]
            XCTAssertTrue(button.waitForExistence(timeout: 5), "tab \(tab.label) is missing")
            button.tap()
            let title = app.navigationBars.matching(NSPredicate(format: "identifier BEGINSWITH %@", tab.titlePrefix)).firstMatch
            XCTAssertTrue(title.waitForExistence(timeout: 5), "navigation title starting with \(tab.titlePrefix) is missing")
            keepScreenshot(of: app, named: "tab-\(tab.label)")
        }
    }

    @MainActor
    func testOperationsPushesAreaScreenAndGoesBack() throws {
        let app = XCUIApplication()
        app.launchArguments += ["-sampleInquiries"]
        app.launch()

        app.tabBars.buttons["운영"].tap()
        let bookingsRow = app.buttons["operations.bookings"]
        if !bookingsRow.waitForExistence(timeout: 3) {
            app.swipeUp()
        }
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
    func testStatusFilterAndSearchNarrowTheList() throws {
        let app = XCUIApplication()
        app.launchArguments += ["-sampleInquiries"]
        app.launch()

        app.tabBars.buttons["운영"].tap()
        let deliveriesRow = app.buttons["operations.deliveries"]
        if !deliveriesRow.waitForExistence(timeout: 3) {
            app.swipeUp()
        }
        XCTAssertTrue(deliveriesRow.waitForExistence(timeout: 5))
        deliveriesRow.tap()

        let packing = element(labelled: "머그컵 2종 세트", in: app)
        let delivered = element(labelled: "핸드메이드 머그컵", in: app)
        XCTAssertTrue(packing.waitForExistence(timeout: 5))

        app.segmentedControls.buttons["완료"].tap()
        XCTAssertTrue(delivered.waitForExistence(timeout: 5))
        XCTAssertTrue(packing.waitForNonExistence(timeout: 5))

        let search = app.searchFields.firstMatch
        XCTAssertTrue(search.waitForExistence(timeout: 5))
        search.tap()
        search.typeText("없는주문")
        XCTAssertTrue(delivered.waitForNonExistence(timeout: 5))
    }

    @MainActor
    private func element(labelled text: String, in app: XCUIApplication) -> XCUIElement {
        app.descendants(matching: .any).matching(NSPredicate(format: "label CONTAINS %@", text)).firstMatch
    }

    @MainActor
    func testAssistantIsReachableFromEveryTab() throws {
        let app = XCUIApplication()
        app.launchArguments += ["-sampleInquiries"]
        app.launch()

        let accessory = app.buttons["assistant.accessory"]
        XCTAssertTrue(accessory.waitForExistence(timeout: 5))

        app.tabBars.buttons["캘린더"].tap()
        XCTAssertTrue(app.navigationBars["캘린더"].waitForExistence(timeout: 5))
        XCTAssertTrue(accessory.waitForExistence(timeout: 5))
        XCTAssertTrue(app.buttons["assistant.voice"].exists)

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
