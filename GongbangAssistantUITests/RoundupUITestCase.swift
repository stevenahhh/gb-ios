import XCTest

/// Launches the app against the local seeded server described by the test environment.
class RoundupUITestCase: XCTestCase {
    private func environment(_ name: String) throws -> String {
        guard let value = ProcessInfo.processInfo.environment[name], !value.isEmpty else {
            throw XCTSkip("Set TEST_RUNNER_\(name) to run UI tests against a local server")
        }
        return value
    }

    @MainActor
    func launch(apiURL: String? = nil) throws -> XCUIApplication {
        let app = XCUIApplication()
        app.launchEnvironment["ROUNDUP_API_URL"] = try apiURL ?? environment("ROUNDUP_UITEST_API_URL")
        app.launchEnvironment["ROUNDUP_API_KEY"] = try environment("ROUNDUP_UITEST_API_KEY")
        app.skipOnboarding()
        app.launch()
        return app
    }

    @MainActor
    func launchEmptyServer() throws -> XCUIApplication {
        try launch(apiURL: try environment("ROUNDUP_UITEST_EMPTY_API_URL"))
    }

    @MainActor
    func element(labelled text: String, in app: XCUIApplication) -> XCUIElement {
        app.descendants(matching: .any).matching(NSPredicate(format: "label CONTAINS %@", text)).firstMatch
    }

    /// Pulls the page down to refresh it, across most of the screen because a swipe on one row is too short.
    @MainActor
    func pullDown(_ app: XCUIApplication) {
        let top = app.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.28))
        top.press(forDuration: 0.1, thenDragTo: app.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.9)), withVelocity: 500, thenHoldForDuration: 0.2)
    }

    @MainActor
    func openArea(_ area: String, in app: XCUIApplication) {
        app.tabBars.buttons["운영"].tap()
        XCTAssertTrue(app.navigationBars["운영"].waitForExistence(timeout: 10))
        let row = app.buttons["operations.\(area)"]
        XCTAssertTrue(scrollTo(row, in: app), "operations row \(area) is missing")
        row.tap()
    }

    /// Lists create rows lazily, so an off-screen row exists only after scrolling to it.
    @MainActor
    func scrollTo(_ target: XCUIElement, in app: XCUIApplication) -> Bool {
        for _ in 0..<8 {
            if target.waitForExistence(timeout: 2), target.isHittable { return true }
            app.swipeUp()
        }
        // A swipe can carry a target that was just below the screen past the top, so the way back is searched too.
        for _ in 0..<8 where !(target.exists && target.isHittable) { app.swipeDown() }
        return target.exists && target.isHittable
    }

    @MainActor
    func keepScreenshot(of app: XCUIApplication, named name: String) {
        let attachment = XCTAttachment(screenshot: app.screenshot())
        attachment.name = name
        attachment.lifetime = .keepAlways
        add(attachment)
    }
}

extension XCTestCase {
    /// `XCUIDevice.appearance` never reaches the app on the iOS 27.2 simulator and then hangs the runner, so the dark
    /// tests run on a simulator that is dark before the app starts: `xcrun simctl ui <device> appearance dark`.
    func requireDarkSimulator() throws {
        let environment = ProcessInfo.processInfo.environment
        try XCTSkipUnless(environment["ROUNDUP_UITEST_DARK"] == "1", "Set TEST_RUNNER_ROUNDUP_UITEST_DARK=1 on a dark simulator")
    }
}

extension XCUIApplication {
    /// Starts on 오늘 instead of the first-launch flow.
    func skipOnboarding() {
        launchArguments += ["-onboarding.done", "YES", "-tutorial.done", "YES"]
    }
}
