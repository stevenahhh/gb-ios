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

extension XCUIApplication {
    /// Starts on 오늘 instead of the first-launch flow.
    func skipOnboarding() {
        launchArguments += ["-onboarding.done", "YES", "-tutorial.done", "YES"]
    }
}
