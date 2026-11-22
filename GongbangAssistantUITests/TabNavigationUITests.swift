import XCTest

final class TabNavigationUITests: RoundupUITestCase {
    private let tabs: [(label: String, titlePrefix: String)] = [
        ("오늘", ""), // The today headline changes with the day's work, so any title counts.
        ("캘린더", "캘린더"),
        ("운영", "운영"),
        ("설정", "설정"),
    ]

    override func setUpWithError() throws {
        continueAfterFailure = false
    }

    @MainActor
    func testEveryTabShowsItsNavigationTitle() throws {
        let app = try launch()

        for tab in tabs {
            let button = app.tabBars.buttons[tab.label]
            XCTAssertTrue(button.waitForExistence(timeout: 5), "tab \(tab.label) is missing")
            button.tap()
            let title = tab.titlePrefix.isEmpty
                ? app.navigationBars.firstMatch
                : app.navigationBars.matching(NSPredicate(format: "identifier BEGINSWITH %@", tab.titlePrefix)).firstMatch
            XCTAssertTrue(title.waitForExistence(timeout: 5), "navigation title starting with \(tab.titlePrefix) is missing")
            keepScreenshot(of: app, named: "tab-\(tab.label)")
        }
    }

    @MainActor
    func testOperationsPushesAreaScreenAndGoesBack() throws {
        let app = try launch()
        openArea("bookings", in: app)

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
        let app = try launch()
        openArea("deliveries", in: app)

        let packing = element(labelled: "머그컵 2종 세트", in: app)
        let delivered = element(labelled: "핸드메이드 머그컵", in: app)
        // Before its pickup time the packing parcel sorts below the parcels in transit, off screen, so the list is
        // narrowed to it first. That keeps the test independent of the time of day.
        let scheduled = app.segmentedControls.buttons["발송 예정"]
        XCTAssertTrue(scheduled.waitForExistence(timeout: 10))
        scheduled.tap()
        XCTAssertTrue(packing.waitForExistence(timeout: 10))

        app.segmentedControls.buttons["완료"].tap()
        XCTAssertTrue(delivered.waitForExistence(timeout: 10))
        XCTAssertTrue(packing.waitForNonExistence(timeout: 10))

        let search = app.searchFields.firstMatch
        XCTAssertTrue(search.waitForExistence(timeout: 5))
        search.tap()
        search.typeText("없는주문")
        XCTAssertTrue(delivered.waitForNonExistence(timeout: 10))
    }

    @MainActor
    func testAssistantIsReachableFromEveryTab() throws {
        let app = try launch()

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
    func testDepositConfirmationSurvivesRelaunch() throws {
        var app = try launch()
        openArea("bookings", in: app)
        let row = app.buttons["booking.row.booking-jieun"]
        XCTAssertTrue(scrollTo(row, in: app))
        row.tap()
        let confirm = app.buttons["step.do.예약금"]
        XCTAssertTrue(confirm.waitForExistence(timeout: 10))
        confirm.tap()
        XCTAssertTrue(app.buttons["step.undo.예약금"].waitForExistence(timeout: 10))

        app.terminate()
        app = try launch()
        openArea("bookings", in: app)
        let reopened = app.buttons["booking.row.booking-jieun"]
        XCTAssertTrue(scrollTo(reopened, in: app))
        reopened.tap()
        XCTAssertTrue(app.buttons["step.undo.예약금"].waitForExistence(timeout: 10))
        XCTAssertFalse(app.buttons["step.do.예약금"].exists)
    }

    @MainActor
    func testInvoiceRegistrationMovesParcelIntoTransit() throws {
        let app = try launch()
        openArea("deliveries", in: app)
        let search = app.searchFields.firstMatch
        XCTAssertTrue(search.waitForExistence(timeout: 10))
        search.tap()
        search.typeText("1041")
        let action = app.buttons["action.shipment-order-1041"]
        XCTAssertTrue(scrollTo(action, in: app))
        action.tap()
        let number = app.textFields["invoice.number.shipment-order-1041"]
        XCTAssertTrue(number.waitForExistence(timeout: 5))
        // The field has focus when the sheet opens, so typing needs no tap first.
        number.typeText("682100042841")
        app.buttons["form.save"].tap()
        XCTAssertTrue(number.waitForNonExistence(timeout: 10))
        XCTAssertTrue(scrollTo(element(labelled: "CJ대한통운 682100042841", in: app), in: app))
    }

    @MainActor
    func testCalendarEventIsSavedToTheSelectedDay() throws {
        let app = try launch()
        app.tabBars.buttons["캘린더"].tap()
        let add = app.buttons["calendar.add"]
        XCTAssertTrue(add.waitForExistence(timeout: 10))
        add.tap()
        let title = app.textFields["event.title"]
        XCTAssertTrue(title.waitForExistence(timeout: 5))
        title.tap()
        title.typeText("공방 대청소")
        app.buttons["form.save"].tap()
        XCTAssertTrue(add.waitForExistence(timeout: 10))
        XCTAssertTrue(scrollTo(element(labelled: "공방 대청소", in: app), in: app))
    }

    @MainActor
    func testDayWithEventsOffersAddWithoutScrolling() throws {
        let app = try launch()
        app.tabBars.buttons["캘린더"].tap()
        // Today has seeded classes and tasks, so the pinned button shows in place of the empty-day one.
        let add = app.buttons["calendar.day.add"]
        XCTAssertTrue(add.waitForExistence(timeout: 10))
        XCTAssertTrue(add.isHittable, "일정 추가 must be in reach before any scrolling")
        XCTAssertFalse(app.buttons["calendar.empty.add"].exists)
        XCTAssertTrue(app.buttons["calendar.add"].exists, "the toolbar plus stays")
        keepScreenshot(of: app, named: "calendar-day-add")

        add.tap()
        let title = app.textFields["event.title"]
        XCTAssertTrue(title.waitForExistence(timeout: 5))
        title.tap()
        title.typeText("가마 청소")
        app.buttons["form.save"].tap()
        XCTAssertTrue(add.waitForExistence(timeout: 10))
        XCTAssertTrue(scrollTo(element(labelled: "가마 청소", in: app), in: app))
    }

    @MainActor
    func testOperationsShowsLiveCollectionInPlaceOfTheRate() throws {
        let app = try launch()
        app.tabBars.buttons["운영"].tap()
        let tile = app.buttons["operations.attention.depositPending"]
        XCTAssertTrue(tile.waitForExistence(timeout: 10))
        XCTAssertNotNil(tile.label.wholeMatch(of: /(기한 지남, )?예약금 미확인 \d+건/), "the tile ends at its label: \(tile.label)")
        keepScreenshot(of: app, named: "operations-tiles")

        let rings = app.descendants(matching: .any)
            .matching(NSPredicate(format: "identifier BEGINSWITH %@", "operations.collection.source."))
        let first = rings.firstMatch
        XCTAssertTrue(scrollTo(first, in: app), "운영 현황 shows no ring")
        XCTAssertEqual(rings.count, 3)
        XCTAssertFalse(element(labelled: "처리율", in: app).exists)

        let start = Date()
        let still = first.screenshot().pngRepresentation
        keepScreenshot(of: app, named: "collection-motion-0s")
        // With nothing connected the rings are a sample, tagged as such, and they turn without a touch. Each capture
        // takes a moment, so a turning ring cannot look the same in all of them.
        if app.descendants(matching: .any)["operations.collection.sample"].exists {
            XCTAssertTrue((0..<5).contains { _ in first.screenshot().pngRepresentation != still }, "the rings do not move")
        }
        // Motion is what this pair of captures shows, so the second one waits until two real seconds have passed.
        Thread.sleep(until: start.addingTimeInterval(2))
        keepScreenshot(of: app, named: "collection-motion-2s")
    }

    @MainActor
    func testUnreachableServerShowsRetryInsteadOfData() throws {
        let app = try launch(apiURL: "http://127.0.0.1:9")
        XCTAssertTrue(app.buttons["screen.retry"].waitForExistence(timeout: 30))
        XCTAssertTrue(element(labelled: "서버에 연결하지 못했어요", in: app).exists)
        XCTAssertFalse(element(labelled: "도자기 원데이 클래스", in: app).exists)
    }

    @MainActor
    func testMissingServerAddressExplainsConfiguration() throws {
        let app = XCUIApplication()
        app.launchEnvironment["ROUNDUP_API_URL"] = ""
        app.launch()
        XCTAssertTrue(element(labelled: "서버 주소가 설정되지 않았어요", in: app).waitForExistence(timeout: 10))
    }

    @MainActor
    func testEmptyDatabaseShowsEmptyStates() throws {
        let app = try launchEmptyServer()
        XCTAssertTrue(app.descendants(matching: .any)["today.empty"].waitForExistence(timeout: 10))
        openArea("orders", in: app)
        XCTAssertTrue(app.descendants(matching: .any)["area.empty"].waitForExistence(timeout: 10))
    }
}
