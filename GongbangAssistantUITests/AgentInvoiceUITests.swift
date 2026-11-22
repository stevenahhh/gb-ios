import XCTest

/// Invoice files, the assistant's settings, its memory and history, and runs left to the server, against
/// `agent-stub-invoice.py`. Skipped unless ROUNDUP_UITEST_AGENT_INVOICE is 1, so no other suite needs that stub.
///
/// Every check of what the server holds reads the stub's own state, and every wait is for a named element or for a
/// request the stub reports as arrived, never for a length of time.
final class AgentInvoiceUITests: RoundupUITestCase {
    private struct StubState: Decodable {
        struct Settings: Decodable {
            struct Tool: Decodable {
                let tool: String
                let mode: String
            }

            struct QuietHours: Decodable, Equatable {
                let start: String
                let end: String
            }

            let mode: String
            let proactive: Bool
            let tools: [Tool]
            let dailyCap: Int
            let quietHours: QuietHours?
        }

        struct Run: Decodable {
            let id: String
            let status: String
        }

        let orders: [String: String]
        let settings: Settings
        let memories: [String]
        let runs: [Run]
    }

    private struct StubLog: Decodable {
        struct Request: Decodable {
            let method: String
            let path: String
            let query: [String: String]
        }

        let requests: [Request]
    }

    private struct Scenario: Encodable {
        var mode: String?
        var empty: Bool?
        var rows: String?
        var serverShapes: Bool?
        var onlyChat: Bool?
        var down: Bool?
        var status: String?
    }

    private struct Fault: Encodable {
        let method: String
        let path: String
        let status: Int
        let detail: String
    }

    private struct Ship: Encodable {
        let order: Int
    }

    private static let clean = ["1044", "1045", "1046"]
    private static let waiting = "invoice_pending"
    private static let sent = "in_transit"

    private var stubURL: URL!

    override func setUp() async throws {
        continueAfterFailure = false
        let environment = ProcessInfo.processInfo.environment
        guard environment["ROUNDUP_UITEST_AGENT_INVOICE"] == "1", let address = environment["ROUNDUP_UITEST_API_URL"] else {
            throw XCTSkip("Set TEST_RUNNER_ROUNDUP_UITEST_AGENT_INVOICE=1 and the address of agent-stub-invoice.py")
        }
        stubURL = try XCTUnwrap(URL(string: address))
        try await control("reset", Scenario())
    }

    // MARK: The stub

    private func control(_ command: String, _ body: some Encodable) async throws {
        var request = URLRequest(url: stubURL.appending(path: "__stub").appending(path: command))
        request.httpMethod = "POST"
        request.httpBody = try JSONEncoder().encode(body)
        let (_, response) = try await URLSession.shared.data(for: request)
        XCTAssertEqual((response as? HTTPURLResponse)?.statusCode, 200, "the stub refused \(command)")
    }

    private func fail(_ method: String, _ path: String, _ status: Int, _ detail: String) async throws {
        try await control("fail", Fault(method: method, path: path, status: status, detail: detail))
    }

    private func mend() async throws { try await control("mend", Scenario()) }

    private func read<Value: Decodable>(_ command: String, as type: Value.Type) async throws -> Value {
        let (data, _) = try await URLSession.shared.data(from: stubURL.appending(path: "__stub").appending(path: command))
        return try JSONDecoder().decode(type, from: data)
    }

    private func state() async throws -> StubState { try await read("state", as: StubState.self) }

    private func approvals() async throws -> [StubLog.Request] {
        try await read("log", as: StubLog.self).requests.filter {
            $0.method == "POST" && $0.path.hasPrefix("/agent/invoices/") && $0.path.hasSuffix("/approve")
        }
    }

    /// What the one approval of a file asked for besides the file itself.
    private func approvalQuery() async throws -> [String: String] {
        let sent = try await approvals()
        return try XCTUnwrap(sent.first, "no approval reached the stub").query
    }

    /// Answers once the app's request has reached the stub, so nothing that follows depends on timing.
    private func arrival(_ method: String, _ path: String, count: Int = 1) async throws {
        let url = stubURL.appending(path: "__stub/wait").appending(queryItems: [
            URLQueryItem(name: "method", value: method), URLQueryItem(name: "path", value: path),
            URLQueryItem(name: "count", value: String(count)),
        ])
        let (_, response) = try await URLSession.shared.data(from: url)
        XCTAssertEqual((response as? HTTPURLResponse)?.statusCode, 200, "\(method) \(path) never reached the stub \(count) times")
    }

    // MARK: The app

    @MainActor
    private func open(file: URL? = nil) throws -> XCUIApplication {
        let app = XCUIApplication()
        app.launchEnvironment["ROUNDUP_API_URL"] = stubURL.absoluteString
        app.launchEnvironment["ROUNDUP_API_KEY"] = try XCTUnwrap(ProcessInfo.processInfo.environment["ROUNDUP_UITEST_API_KEY"])
        if let file { app.launchEnvironment["ROUNDUP_UITEST_INVOICE_FILE"] = file.path }
        app.launch()
        return app
    }

    private func file(named name: String = "송장-11월22일.csv", bytes: Int? = nil) throws -> URL {
        let url = FileManager.default.temporaryDirectory.appendingPathComponent(name)
        let text = "주문번호,택배사,송장번호\n1044,CJ대한통운,682100042841\n"
        try (bytes.map { Data(repeating: 0x31, count: $0) } ?? Data(text.utf8)).write(to: url)
        addTeardownBlock { try? FileManager.default.removeItem(at: url) }
        return url
    }

    @MainActor
    private func capture(_ app: XCUIApplication, _ name: String) throws {
        let screenshot = app.screenshot()
        let attachment = XCTAttachment(screenshot: screenshot)
        attachment.name = name
        attachment.lifetime = .keepAlways
        add(attachment)
        guard let directory = ProcessInfo.processInfo.environment["AGENT_UITEST_SHOT_DIR"] else { return }
        try screenshot.pngRepresentation.write(to: URL(fileURLWithPath: directory).appendingPathComponent("\(name).png"))
    }

    @MainActor
    private func named(_ identifier: String, in app: XCUIApplication) -> XCUIElement {
        app.descendants(matching: .any)[identifier].firstMatch
    }

    @MainActor
    private func expect(_ element: XCUIElement, _ format: String, _ message: String) {
        let outcome = XCTWaiter().wait(
            for: [XCTNSPredicateExpectation(predicate: NSPredicate(format: format), object: element)], timeout: 30)
        XCTAssertEqual(outcome, .completed, message)
    }

    /// A switch row answers a tap on its own inner switch; the row's middle is its label.
    @MainActor
    private func flip(_ row: XCUIElement) {
        let inner = row.switches.firstMatch
        (inner.exists ? inner : row).tap()
    }

    @MainActor
    private func steps(in app: XCUIApplication) -> XCUIElementQuery {
        app.descendants(matching: .any).matching(NSPredicate(
            format: "identifier BEGINSWITH %@ AND NOT (identifier BEGINSWITH %@)", "agent.step.", "agent.step.undo."))
    }

    @MainActor
    private func undoButton(in app: XCUIApplication) -> XCUIElement {
        app.buttons.matching(NSPredicate(format: "identifier BEGINSWITH %@", "agent.step.undo.")).firstMatch
    }

    @MainActor
    private func openAssistant(in app: XCUIApplication, startingNew: Bool = true) {
        let accessory = app.buttons["assistant.accessory"]
        XCTAssertTrue(accessory.waitForExistence(timeout: 60), "the assistant bar is missing")
        accessory.tap()
        XCTAssertTrue(app.navigationBars["비서"].waitForExistence(timeout: 20))
        // An earlier test's conversation is recent enough to reopen, so each test starts its own.
        let new = app.buttons["assistant.new"]
        if startingNew, new.waitForExistence(timeout: 2) { new.tap() }
    }

    @MainActor
    private func closeAssistant(in app: XCUIApplication) {
        app.navigationBars["비서"].buttons["닫기"].tap()
        XCTAssertTrue(app.navigationBars["비서"].waitForNonExistence(timeout: 20))
    }

    @MainActor
    private func ask(_ question: String, in app: XCUIApplication) {
        let field = named("assistant.field", in: app)
        XCTAssertTrue(field.waitForExistence(timeout: 20))
        field.tap()
        field.typeText(question)
        let send = app.buttons["assistant.send"]
        expect(send, "isEnabled == true", "the question cannot be sent")
        send.tap()
    }

    @MainActor
    private func importFile(_ file: URL) throws -> XCUIApplication {
        let app = try open(file: file)
        openAssistant(in: app)
        app.buttons["assistant.import"].tap()
        return app
    }

    @MainActor
    private func readFile() throws -> XCUIApplication {
        let app = try importFile(try file())
        XCTAssertTrue(named("invoice.import.summary", in: app).waitForExistence(timeout: 30), "the file was not read")
        return app
    }

    @MainActor
    private func openSettingsRow(_ identifier: String, in app: XCUIApplication) {
        let settings = app.tabBars.buttons["설정"]
        XCTAssertTrue(settings.waitForExistence(timeout: 60))
        settings.tap()
        let row = app.buttons[identifier]
        XCTAssertTrue(row.waitForExistence(timeout: 30), "settings row \(identifier) is missing")
        XCTAssertTrue(scrollTo(row, in: app))
        row.tap()
    }

    @MainActor
    private func openMemories(in app: XCUIApplication) {
        openSettingsRow("settings.delegation", in: app)
        let link = app.buttons["agent.settings.memories"]
        XCTAssertTrue(scrollTo(link, in: app))
        link.tap()
    }

    @MainActor
    private func dismissFailure(saying sentence: String, in app: XCUIApplication) {
        let alert = app.alerts["처리하지 못했어요"]
        XCTAssertTrue(alert.waitForExistence(timeout: 20), "a refused change said nothing")
        XCTAssertTrue(alert.staticTexts.containing(NSPredicate(format: "label CONTAINS %@", sentence)).firstMatch.exists,
                      "the alert does not give the reason: \(alert.debugDescription)")
        alert.buttons["확인"].tap()
        XCTAssertTrue(alert.waitForNonExistence(timeout: 10))
    }

    // MARK: Invoice files

    /// Every row but the clean ones and those whose only fault is their length: listed with a reason, never approvable.
    private static let held = [
        5: "짐작했어요", 6: "칸이 바뀐 것 같아요", 7: "이미 발송한 주문이에요", 8: "아직 포장 완료 전인 주문이에요",
        9: "두 번 나와요", 10: "이미 다른 주문에 등록된 송장번호예요", 11: "받는 분이 주문과 달라요",
        12: "하나로 정하지 못했어요", 13: "하나로 정하지 못했어요", 14: "택배사를 알 수 없어요",
    ]

    @MainActor
    func testFileRowsAreSortedIntoCleanWarnedAndBlocked() async throws {
        let app = try readFile()
        let summary = named("invoice.import.summary", in: app)
        XCTAssertTrue(summary.label.contains("송장번호 15개를 읽었어요"), summary.label)
        XCTAssertTrue(app.buttons["invoice.import.approve"].exists, "a file with clean rows has no approval")
        try capture(app, "import-read")
        for offset in [3, 4] {
            XCTAssertTrue(scrollTo(app.switches["invoice.import.accept.\(offset)"], in: app), "row \(offset) lost its switch")
        }
        XCTAssertTrue(element(labelled: "알려진 송장번호 자릿수와 달라요", in: app).exists, "the warning is not stated")
        try capture(app, "import-warned")
        for (offset, reason) in Self.held.sorted(by: { $0.key < $1.key }) {
            XCTAssertTrue(scrollTo(element(labelled: reason, in: app), in: app), "row \(offset) does not say ‘\(reason)’")
            XCTAssertFalse(app.switches["invoice.import.accept.\(offset)"].exists, "row \(offset) has no format to accept")
            XCTAssertFalse(app.buttons["invoice.import.approve.\(offset)"].exists, "row \(offset) has an approval of its own")
        }
        try capture(app, "import-blocked")
        let after = try await state()
        XCTAssertEqual(Set(Self.clean.map { after.orders[$0] }), [Self.waiting], "reading a file registered a number")
    }

    @MainActor
    private func approve(in app: XCUIApplication) async throws {
        let button = app.buttons["invoice.import.approve"]
        for _ in 0..<8 where !(button.exists && button.isHittable) { app.swipeDown() }
        button.tap()
        XCTAssertTrue(named("invoice.import.approved", in: app).waitForExistence(timeout: 30), "the approval was not confirmed")
        let sent = try await approvals()
        XCTAssertEqual(sent.count, 1)
    }

    @MainActor
    func testOneApprovalCoversTheCleanRowsOnly() async throws {
        let app = try readFile()
        try await approve(in: app)
        XCTAssertFalse(app.buttons["invoice.import.approve"].exists, "the file can be approved twice")
        let after = try await state()
        XCTAssertEqual(Self.clean.map { after.orders[$0] }, [Self.sent, Self.sent, Self.sent])
        for order in ["1047", "1048", "1049", "1050", "1051", "1052", "1053", "1054"] {
            XCTAssertEqual(after.orders[order], Self.waiting, "one approval covered order \(order)")
        }
        XCTAssertEqual(after.orders["1040"], "packing")
        let query = try await approvalQuery()
        XCTAssertEqual(query["filename"], "송장-11월22일.csv")
        XCTAssertEqual(query["acceptFormat"] ?? "", "", "no row was accepted")
        try capture(app, "import-clean-approved")
    }

    @MainActor
    func testFormatWarningIsAcceptedRowByRow() async throws {
        let app = try readFile()
        let first = app.switches["invoice.import.accept.3"]
        XCTAssertTrue(scrollTo(first, in: app))
        XCTAssertEqual(first.value as? String, "0", "a format warning starts accepted")
        flip(first)
        expect(first, "value == '1'", "the warning cannot be accepted")
        flip(first)
        expect(first, "value == '0'", "the acceptance cannot be taken back")
        flip(first)
        expect(first, "value == '1'", "the warning cannot be accepted again")
        let second = app.switches["invoice.import.accept.4"]
        XCTAssertTrue(scrollTo(second, in: app))
        XCTAssertEqual(second.value as? String, "0", "accepting one row accepted another")
        try capture(app, "warning-accepted")

        try await approve(in: app)
        let after = try await state()
        XCTAssertEqual(after.orders["1047"], Self.sent, "the accepted row was not registered")
        XCTAssertEqual(after.orders["1048"], Self.waiting, "a row nobody accepted was registered")
        XCTAssertEqual(Self.clean.map { after.orders[$0] }, [Self.sent, Self.sent, Self.sent])
        let query = try await approvalQuery()
        XCTAssertEqual(query["acceptFormat"], "5")
        try capture(app, "warning-registered")
    }

    @MainActor
    func testSeveralAcceptedRowsGoInOneApproval() async throws {
        let app = try readFile()
        for offset in [3, 4] {
            let accept = app.switches["invoice.import.accept.\(offset)"]
            XCTAssertTrue(scrollTo(accept, in: app))
            flip(accept)
            expect(accept, "value == '1'", "row \(offset) was not accepted")
        }
        try await approve(in: app)
        let query = try await approvalQuery()
        XCTAssertEqual(Set((query["acceptFormat"] ?? "").split(separator: ",")), ["5", "6"])
        let after = try await state()
        XCTAssertEqual([after.orders["1047"], after.orders["1048"]], [Self.sent, Self.sent])
    }

    @MainActor
    func testCleanRowsThatChangedMeanwhileAreRefused() async throws {
        let app = try readFile()
        try await control("ship", Ship(order: 1044))
        app.buttons["invoice.import.approve"].tap()
        dismissFailure(saying: "파일을 올린 뒤에 등록할 송장이 달라졌어요", in: app)
        XCTAssertFalse(named("invoice.import.approved", in: app).exists, "a refused approval is shown as done")
        let after = try await state()
        XCTAssertEqual([after.orders["1045"], after.orders["1046"]], [Self.waiting, Self.waiting], "part of a refused file was registered")
        try capture(app, "import-changed-meanwhile")
    }

    @MainActor
    func testFileWithoutAnyCleanRowHasNoApproval() async throws {
        try await control("reset", Scenario(rows: "blocked"))
        let app = try readFile()
        XCTAssertTrue(named("invoice.import.summary", in: app).exists)
        XCTAssertFalse(app.buttons["invoice.import.approve"].exists, "the server sent no proposal to approve")
        try capture(app, "import-no-proposal")
    }

    @MainActor
    func testFileOfWarnedRowsIsApprovedOnlyForWhatWasAccepted() async throws {
        try await control("reset", Scenario(rows: "warned"))
        let app = try readFile()
        let first = app.switches["invoice.import.accept.0"]
        XCTAssertTrue(scrollTo(first, in: app), "the first warned row has no switch")
        flip(first)
        expect(first, "value == '1'", "the warning cannot be accepted")
        try await approve(in: app)
        let after = try await state()
        XCTAssertEqual([after.orders["1047"], after.orders["1048"]], [Self.sent, Self.waiting])
    }

    @MainActor
    func testRefusedApprovalSaysWhyAndCanBeTriedAgain() async throws {
        let app = try readFile()
        try await fail("POST", "/agent/invoices/proposal-", 409, "처음에 올린 파일과 달라요.")
        let approve = app.buttons["invoice.import.approve"]
        approve.tap()
        dismissFailure(saying: "처음에 올린 파일과 달라요", in: app)
        let refused = try await state()
        XCTAssertEqual(refused.orders["1044"], Self.waiting)
        try await mend()
        XCTAssertTrue(approve.waitForExistence(timeout: 10), "a refused approval cannot be tried again")
        approve.tap()
        XCTAssertTrue(named("invoice.import.approved", in: app).waitForExistence(timeout: 30))
    }

    @MainActor
    func testFileTheServerCannotReadSaysWhyAndCanBeRetried() async throws {
        try await fail("POST", "/agent/invoices/import", 422, "수식이 든 파일은 읽지 않아요. 값으로 저장해 주세요.")
        let app = try importFile(try file())
        let retry = app.buttons["screen.retry"]
        XCTAssertTrue(retry.waitForExistence(timeout: 30))
        XCTAssertTrue(element(labelled: "수식이 든 파일은 읽지 않아요", in: app).exists, "the server's reason is missing")
        XCTAssertFalse(app.buttons["invoice.import.approve"].exists)
        try capture(app, "import-unreadable")

        try await mend()
        retry.tap()
        XCTAssertTrue(named("invoice.import.summary", in: app).waitForExistence(timeout: 30))
    }

    @MainActor
    func testFilesOfAnotherKindOrTooLargeAreNotSent() async throws {
        let cases = [("송장.pdf", Int?.none, "CSV나 XLSX 파일만 읽을 수 있어요"), ("큰파일.csv", 2 * 1024 * 1024 + 1, "파일이 너무 커요")]
        for (name, bytes, reason) in cases {
            let app = try importFile(try file(named: name, bytes: bytes))
            let alert = app.alerts["파일을 불러오지 못했어요"]
            XCTAssertTrue(alert.waitForExistence(timeout: 20), "\(name) was accepted")
            XCTAssertTrue(element(labelled: reason, in: app).exists, "\(name) gives no reason")
            try capture(app, "import-rejected-\(bytes == nil ? "kind" : "size")")
            alert.buttons["확인"].tap()
            app.terminate()
        }
        let log = try await read("log", as: StubLog.self).requests
        XCTAssertFalse(log.contains { $0.path.hasPrefix("/agent/invoices/") }, "a refused file left the phone")
    }

    @MainActor
    func testFileWithoutNumbersOffersNothingToApprove() async throws {
        try await control("reset", Scenario(rows: "none"))
        let app = try readFile()
        let summary = named("invoice.import.summary", in: app)
        XCTAssertTrue(summary.label.contains("송장번호 0개를 읽었어요"), summary.label)
        XCTAssertFalse(app.buttons["invoice.import.approve"].exists)
        try capture(app, "import-empty")
    }

    @MainActor
    func testImportReconnectsByItselfAndApprovalWaitsForTheServer() async throws {
        let app = try open(file: try file())
        openAssistant(in: app)
        try await control("down", Scenario(down: true))
        app.buttons["assistant.import"].tap()
        XCTAssertTrue(named("screen.reconnecting", in: app).waitForExistence(timeout: 30), "an unreachable server said nothing")
        try capture(app, "import-offline")
        try await control("down", Scenario(down: false))
        XCTAssertTrue(named("invoice.import.summary", in: app).waitForExistence(timeout: 60), "the import did not reconnect")

        try await control("down", Scenario(down: true))
        app.buttons["invoice.import.approve"].tap()
        dismissFailure(saying: "서버에 연결하지 못했어요", in: app)
        XCTAssertFalse(named("invoice.import.approved", in: app).exists)
        try await control("down", Scenario(down: false))
        let after = try await state()
        XCTAssertEqual(after.orders["1044"], Self.waiting)
        app.buttons["invoice.import.approve"].tap()
        XCTAssertTrue(named("invoice.import.approved", in: app).waitForExistence(timeout: 30))
    }

    // MARK: Settings

    /// Opens a tool's menu and takes one of its choices; the mode picker above names the same choices.
    @MainActor
    private func choose(_ title: String, for tool: String, in app: XCUIApplication) throws {
        let row = named("agent.settings.tool.\(tool)", in: app)
        XCTAssertTrue(scrollTo(row, in: app), "\(tool) has no row")
        row.tap()
        let choices = app.buttons.matching(NSPredicate(format: "label == %@", title))
        XCTAssertTrue(choices.firstMatch.waitForExistence(timeout: 10), "the choices of \(tool) did not open")
        try XCTUnwrap(choices.allElementsBoundByIndex.last { $0.isHittable }, "\(title) is out of reach").tap()
    }

    @MainActor
    func testEverySettingIsSavedAndReadBack() async throws {
        var app = try open()
        openSettingsRow("settings.delegation", in: app)
        let mode = app.segmentedControls.buttons["물어보고"]
        XCTAssertTrue(mode.waitForExistence(timeout: 30))
        mode.tap()
        try await arrival("PUT", "/agent/settings", count: 1)
        let proactive = app.switches["agent.settings.proactive"]
        XCTAssertTrue(scrollTo(proactive, in: app))
        flip(proactive)
        try await arrival("PUT", "/agent/settings", count: 2)
        try choose("알아서", for: "complete_task", in: app)
        try await arrival("PUT", "/agent/settings", count: 3)
        let cap = app.steppers["agent.settings.cap"]
        XCTAssertTrue(scrollTo(cap, in: app))
        cap.buttons.element(boundBy: 0).tap()
        try await arrival("PUT", "/agent/settings", count: 4)
        let quiet = app.switches["agent.settings.quiet"]
        XCTAssertTrue(scrollTo(quiet, in: app))
        flip(quiet)
        try await arrival("PUT", "/agent/settings", count: 5)
        XCTAssertTrue(named("agent.settings.quiet.start", in: app).waitForNonExistence(timeout: 10))
        try capture(app, "settings-changed")

        let saved = try await state().settings
        XCTAssertEqual(saved.mode, "ask")
        XCTAssertFalse(saved.proactive)
        XCTAssertEqual(saved.tools.first { $0.tool == "complete_task" }?.mode, "auto")
        XCTAssertEqual(saved.tools.first { $0.tool == "register_invoice" }?.mode, "ask")
        XCTAssertEqual(saved.dailyCap, 19)
        XCTAssertNil(saved.quietHours)

        app.terminate()
        app = try open()
        openSettingsRow("settings.delegation", in: app)
        XCTAssertTrue(app.segmentedControls.buttons["물어보고"].waitForExistence(timeout: 30))
        XCTAssertTrue(app.segmentedControls.buttons["물어보고"].isSelected, "the mode was not read back")
        let proactiveAgain = app.switches["agent.settings.proactive"]
        XCTAssertTrue(scrollTo(proactiveAgain, in: app))
        XCTAssertEqual(proactiveAgain.value as? String, "0")
        let task = named("agent.settings.tool.complete_task", in: app)
        XCTAssertTrue(scrollTo(task, in: app))
        let shown = "\(task.label) \(task.value as? String ?? "")"
        XCTAssertTrue(shown.contains("알아서"), shown)
        XCTAssertTrue(scrollTo(element(labelled: "최대 19건", in: app), in: app))
        let quietAgain = app.switches["agent.settings.quiet"]
        XCTAssertTrue(scrollTo(quietAgain, in: app))
        XCTAssertEqual(quietAgain.value as? String, "0")
        try capture(app, "settings-read-back")

        flip(quietAgain)
        try await arrival("PUT", "/agent/settings", count: 6)
        let restored = try await state().settings
        XCTAssertEqual(restored.quietHours, StubState.Settings.QuietHours(start: "22:00", end: "08:00"))
    }

    @MainActor
    func testRefusedSettingIsTakenBackWithTheReason() async throws {
        let app = try open()
        openSettingsRow("settings.delegation", in: app)
        let ask = app.segmentedControls.buttons["물어보고"]
        XCTAssertTrue(ask.waitForExistence(timeout: 30))
        try await fail("PUT", "/agent/settings", 409, "그사이에 설정이 바뀌었어요. 다시 불러온 뒤 저장해 주세요.")
        ask.tap()
        let warning = named("agent.settings.warning", in: app)
        XCTAssertTrue(warning.waitForExistence(timeout: 20), "a refused change said nothing")
        XCTAssertTrue(warning.label.contains("그사이에 설정이 바뀌었어요"), warning.label)
        expect(app.segmentedControls.buttons["알아서"], "isSelected == true", "the refused mode stayed selected")
        try capture(app, "settings-refused")
    }

    @MainActor
    func testKillSwitchStopsARunningJobAndHandsBackAsAsk() async throws {
        let app = try open()
        openAssistant(in: app)
        ask("1040 1042 포장 끝났어", in: app)
        try await arrival("POST", "/agent/run")
        try await control("advance", Scenario())
        XCTAssertTrue(steps(in: app).firstMatch.waitForExistence(timeout: 30))
        closeAssistant(in: app)

        openSettingsRow("settings.delegation", in: app)
        let stop = app.buttons["agent.settings.stop"]
        XCTAssertTrue(stop.waitForExistence(timeout: 30))
        stop.tap()
        try await arrival("PUT", "/agent/settings")
        let resume = app.buttons["agent.settings.resume"]
        XCTAssertTrue(resume.waitForExistence(timeout: 10))
        try capture(app, "settings-stopped")
        try await control("advance", Scenario())
        let stopped = try await state()
        XCTAssertEqual(stopped.settings.mode, "off")
        XCTAssertEqual(stopped.runs.first?.status, "stopped")
        XCTAssertEqual(stopped.orders["1040"], Self.waiting)
        XCTAssertEqual(stopped.orders["1042"], "packing", "the job went on after the stop")

        openAssistant(in: app, startingNew: false)
        let notice = element(labelled: "멈춰서 남은 일은 하지 않았어요", in: app)
        XCTAssertTrue(notice.waitForExistence(timeout: 30), "the conversation does not say the job was stopped")
        XCTAssertEqual(steps(in: app).count, 1)
        try capture(app, "chat-stopped-job")
        closeAssistant(in: app)

        XCTAssertTrue(resume.waitForExistence(timeout: 10))
        resume.tap()
        try await arrival("PUT", "/agent/settings", count: 2)
        XCTAssertTrue(stop.waitForExistence(timeout: 10))
        let resumed = try await state()
        XCTAssertEqual(resumed.settings.mode, "ask", "handing back did not start at ‘물어보고’")
    }

    @MainActor
    func testSettingsThatCannotBeReadOfferARetry() async throws {
        try await fail("GET", "/agent/settings", 500, "x")
        let app = try open()
        openSettingsRow("settings.delegation", in: app)
        let retry = app.buttons["screen.retry"]
        XCTAssertTrue(retry.waitForExistence(timeout: 30))
        XCTAssertFalse(app.buttons["agent.settings.stop"].exists)
        try capture(app, "settings-error")
        try await mend()
        retry.tap()
        XCTAssertTrue(app.buttons["agent.settings.stop"].waitForExistence(timeout: 30))
    }

    // MARK: Memory

    @MainActor
    func testMemoryStaysOnCancelAndGoesOnConfirm() async throws {
        let app = try open()
        openMemories(in: app)
        let memory = named("agent.memory.mem-1", in: app)
        XCTAssertTrue(memory.waitForExistence(timeout: 30))
        let forget = app.buttons["agent.memory.forget.mem-1"]
        forget.tap()
        let keep = app.buttons["그대로 두기"]
        if keep.waitForExistence(timeout: 10) {
            keep.tap()
        } else {
            // A confirmation shown as a popover has no cancel button; a tap outside keeps the memory.
            XCTAssertTrue(app.buttons["지우기"].firstMatch.exists, "forgetting did not ask first")
            app.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.1)).tap()
        }
        XCTAssertTrue(app.buttons["지우기"].firstMatch.waitForNonExistence(timeout: 10))
        let kept = try await state()
        XCTAssertEqual(Set(kept.memories), ["mem-1", "mem-2"])

        forget.tap()
        let confirm = app.buttons["지우기"].firstMatch
        XCTAssertTrue(confirm.waitForExistence(timeout: 10))
        try capture(app, "memory-confirm")
        confirm.tap()
        XCTAssertTrue(memory.waitForNonExistence(timeout: 20))
        XCTAssertTrue(named("agent.memory.mem-2", in: app).exists)
        let after = try await state()
        XCTAssertEqual(after.memories, ["mem-2"])
        try capture(app, "memory-forgotten")
    }

    @MainActor
    func testMemoryThatCouldNotBeForgottenStays() async throws {
        let app = try open()
        openMemories(in: app)
        let memory = named("agent.memory.mem-1", in: app)
        XCTAssertTrue(memory.waitForExistence(timeout: 30))
        try await control("down", Scenario(down: true))
        app.buttons["agent.memory.forget.mem-1"].tap()
        let confirm = app.buttons["지우기"].firstMatch
        XCTAssertTrue(confirm.waitForExistence(timeout: 10))
        confirm.tap()
        dismissFailure(saying: "서버에 연결하지 못했어요", in: app)
        XCTAssertTrue(memory.exists, "a memory that was not forgotten left the list")
        try capture(app, "memory-offline")
        try await control("down", Scenario(down: false))
        let after = try await state()
        XCTAssertEqual(Set(after.memories), ["mem-1", "mem-2"])
    }

    @MainActor
    func testEmptyMemorySaysWhatBelongsThere() async throws {
        try await control("reset", Scenario(empty: true))
        let app = try open()
        openMemories(in: app)
        XCTAssertTrue(named("agent.memories.empty", in: app).waitForExistence(timeout: 30))
        try capture(app, "memory-empty")
    }

    // MARK: History

    @MainActor
    private func openHistory(in app: XCUIApplication) -> XCUIElement {
        openSettingsRow("settings.activities", in: app)
        let chat = element(labelled: "내일 10시에 가마 청소 넣어 줘", in: app)
        XCTAssertTrue(chat.waitForExistence(timeout: 30), "the history is empty")
        return chat
    }

    @MainActor
    func testHistoryFiltersBySourceAndUndoesAStep() async throws {
        let app = try open()
        let chat = openHistory(in: app)
        app.segmentedControls.buttons["음성"].tap()
        XCTAssertTrue(scrollTo(element(labelled: "1039 포장 끝났어", in: app), in: app))
        XCTAssertFalse(chat.exists, "a chat run stayed under the voice filter")
        try capture(app, "history-voice")
        app.segmentedControls.buttons["먼저 챙김"].tap()
        XCTAssertTrue(scrollTo(element(labelled: "먼저 살펴보기", in: app), in: app))
        app.segmentedControls.buttons["채팅"].tap()
        XCTAssertTrue(chat.waitForExistence(timeout: 10))

        let undo = undoButton(in: app)
        XCTAssertTrue(scrollTo(undo, in: app))
        undo.tap()
        XCTAssertTrue(undo.waitForNonExistence(timeout: 20))
        XCTAssertTrue(element(labelled: "되돌림", in: app).waitForExistence(timeout: 10))
        try capture(app, "history-undone")
    }

    @MainActor
    func testUndoTheServerRefusesSaysWhy() async throws {
        let app = try open()
        _ = openHistory(in: app)
        try await fail("POST", "/agent/steps/", 409, "그사이 바뀌어서 되돌릴 수 없어요.")
        let undo = undoButton(in: app)
        XCTAssertTrue(scrollTo(undo, in: app))
        undo.tap()
        dismissFailure(saying: "그사이 바뀌어서 되돌릴 수 없어요", in: app)
        XCTAssertFalse(element(labelled: "되돌림", in: app).exists, "a refused undo is shown as done")
        try capture(app, "history-undo-refused")
    }

    /// The same history against the run list agent_run.recent_runs sends.
    @MainActor
    func testHistoryShowsStepsFromTheServersRunList() async throws {
        try await control("reset", Scenario(serverShapes: true))
        let app = try open()
        _ = openHistory(in: app)
        app.segmentedControls.buttons["채팅"].tap()
        let found = scrollTo(undoButton(in: app), in: app)
        try capture(app, "server-run-list")
        XCTAssertTrue(found, "the server's run list carries no steps, so the history shows none and offers no undo")
    }

    @MainActor
    func testFilterWithNothingToShowLeadsBackToEverything() async throws {
        try await control("reset", Scenario(onlyChat: true))
        let app = try open()
        let chat = openHistory(in: app)
        app.segmentedControls.buttons["음성"].tap()
        XCTAssertTrue(named("activity.filter.empty", in: app).waitForExistence(timeout: 10))
        try capture(app, "history-filter-empty")
        app.buttons["전체 보기"].firstMatch.tap()
        XCTAssertTrue(chat.waitForExistence(timeout: 10))
    }

    @MainActor
    func testEmptyHistorySaysSo() async throws {
        try await control("reset", Scenario(empty: true))
        let app = try open()
        openSettingsRow("settings.activities", in: app)
        XCTAssertTrue(named("activity.empty", in: app).waitForExistence(timeout: 30))
        try capture(app, "history-empty")
    }

    // MARK: Runs left to the server

    @MainActor
    func testRunLeftToTheServerGoesOnAcrossARelaunch() async throws {
        var app = try open()
        openAssistant(in: app)
        ask("1040 1042 포장 끝났어", in: app)
        let working = named("assistant.generating", in: app)
        XCTAssertTrue(working.waitForExistence(timeout: 30))
        try await arrival("POST", "/agent/run")
        try await control("advance", Scenario())
        expect(working, "label CONTAINS '1건 끝냈어요'", "the progress line does not count what finished")
        XCTAssertEqual(steps(in: app).count, 1)
        try capture(app, "run-progress")

        app.terminate()
        try await control("advance", Scenario())
        try await control("advance", Scenario())
        app = try open()
        openAssistant(in: app, startingNew: false)
        XCTAssertTrue(element(labelled: "주문 2건을 포장 완료로 바꿨어요", in: app).waitForExistence(timeout: 30),
                      "the run's answer did not arrive after the relaunch")
        XCTAssertEqual(steps(in: app).count, 2)
        XCTAssertFalse(working.exists)
        try capture(app, "run-done-after-relaunch")
    }

    @MainActor
    func testRunThatFailsSaysHowFarItGot() async throws {
        let app = try open()
        openAssistant(in: app)
        ask("1040 1042 포장 끝났어", in: app)
        try await arrival("POST", "/agent/run")
        try await control("advance", Scenario())
        XCTAssertTrue(steps(in: app).firstMatch.waitForExistence(timeout: 30))
        try await control("finish", Scenario(status: "failed"))
        XCTAssertTrue(element(labelled: "끝까지 처리하지 못했어요", in: app).waitForExistence(timeout: 30))
        XCTAssertEqual(steps(in: app).count, 1)
        let after = try await state()
        XCTAssertEqual([after.orders["1040"], after.orders["1042"]], [Self.waiting, "packing"])
        try capture(app, "run-failed")
    }
}

/// The import and the approval against the real server code, started by evidence/agent/ui-invoice/real-server.sh, which
/// seeds the parcels, reads the database before and after, and undoes one parcel. Skipped without that server.
final class AgentInvoiceServerUITests: RoundupUITestCase {
    @MainActor
    func testApprovedRowsReachTheRealServer() throws {
        continueAfterFailure = false
        let environment = ProcessInfo.processInfo.environment
        guard environment["ROUNDUP_UITEST_AGENT_INVOICE_REAL"] == "1" else {
            throw XCTSkip("Set TEST_RUNNER_ROUNDUP_UITEST_AGENT_INVOICE_REAL=1 and the address of the real server")
        }
        let file = FileManager.default.temporaryDirectory.appendingPathComponent("송장-실서버.csv")
        let text = """
        주문번호,택배사,송장번호
        1041,CJ대한통운,682100042841
        1038,CJ대한통운,682100042852
        1039,CJ대한통운,68210004
        1021,CJ대한통운,68210005
        1040,CJ대한통운,682100042863
        1022,CJ대한통운,682100042874

        """
        try Data(text.utf8).write(to: file)
        addTeardownBlock { try? FileManager.default.removeItem(at: file) }
        let app = XCUIApplication()
        app.launchEnvironment["ROUNDUP_API_URL"] = try XCTUnwrap(environment["ROUNDUP_UITEST_API_URL"])
        app.launchEnvironment["ROUNDUP_API_KEY"] = try XCTUnwrap(environment["ROUNDUP_UITEST_API_KEY"])
        app.launchEnvironment["ROUNDUP_UITEST_INVOICE_FILE"] = file.path
        app.launch()

        let accessory = app.buttons["assistant.accessory"]
        XCTAssertTrue(accessory.waitForExistence(timeout: 60))
        accessory.tap()
        app.buttons["assistant.import"].tap()
        let summary = app.descendants(matching: .any)["invoice.import.summary"].firstMatch
        XCTAssertTrue(summary.waitForExistence(timeout: 30), "the server did not read the file")
        try capture(app, "real-import")
        // Row 3 of the file is the third row: its number is too short, and the owner accepts it.
        let accept = app.switches["invoice.import.accept.2"]
        XCTAssertTrue(scrollTo(accept, in: app), "the row with a short number has no switch")
        let inner = accept.switches.firstMatch
        (inner.exists ? inner : accept).tap()
        let approve = app.buttons["invoice.import.approve"]
        for _ in 0..<8 where !(approve.exists && approve.isHittable) { app.swipeDown() }
        approve.tap()
        XCTAssertTrue(app.descendants(matching: .any)["invoice.import.approved"].firstMatch.waitForExistence(timeout: 30),
                      "the server refused the approval")
        try capture(app, "real-approved")
    }

    @MainActor
    private func capture(_ app: XCUIApplication, _ name: String) throws {
        let screenshot = app.screenshot()
        let attachment = XCTAttachment(screenshot: screenshot)
        attachment.name = name
        attachment.lifetime = .keepAlways
        add(attachment)
        guard let directory = ProcessInfo.processInfo.environment["AGENT_UITEST_SHOT_DIR"] else { return }
        try screenshot.pngRepresentation.write(to: URL(fileURLWithPath: directory).appendingPathComponent("\(name).png"))
    }
}
