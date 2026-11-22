import XCTest

/// The assistant agent against `agent-stub.py`, a scripted stand-in for the server. Skipped unless
/// ROUNDUP_UITEST_AGENT is 1, so the other suites never need the stub.
///
/// Every check of what the server holds reads the stub's own state, and every wait is for a named element or
/// for a request the stub reports as arrived, never for a length of time.
final class AgentUITests: RoundupUITestCase {
    private struct StubState: Decodable {
        struct Proposal: Decodable {
            let id: String
            let title: String
            let state: String
        }

        struct Settings: Decodable {
            struct Tool: Decodable {
                let tool: String
                let mode: String
            }

            let mode: String
            let tools: [Tool]
            let dailyCap: Int
        }

        let orders: [String: String]
        let invoices: [String: String]
        let depositConfirmed: Bool
        let settings: Settings
        let memories: [String]
        let questions: [String]
        let proposals: [Proposal]
    }

    private struct StubRequest: Decodable {
        let method: String
        let path: String
        let query: [String: String]
        let bytes: Int
    }

    private struct StubLog: Decodable {
        let requests: [StubRequest]
    }

    private struct Scenario: Encodable {
        var mode: String?
        var expired: Bool?
        var empty: Bool?
        var down: Bool?
        var needsValue: Bool?
        var loseReply: Bool?
        var noAgent: Bool?
        var dirtyFile: Bool?
    }

    private var stubURL: URL!

    override func setUp() async throws {
        continueAfterFailure = false
        let environment = ProcessInfo.processInfo.environment
        guard environment["ROUNDUP_UITEST_AGENT"] == "1", let address = environment["ROUNDUP_UITEST_API_URL"] else {
            throw XCTSkip("Set TEST_RUNNER_ROUNDUP_UITEST_AGENT=1 and the stub's address to run against agent-stub.py")
        }
        stubURL = try XCTUnwrap(URL(string: address))
        try await control("reset")
    }

    // MARK: The stub

    @discardableResult
    private func control(_ command: String, _ scenario: Scenario = Scenario(), query: [URLQueryItem] = []) async throws
        -> Data {
        let address = stubURL.appending(path: "__stub").appending(path: command)
        var request = URLRequest(url: query.isEmpty ? address : address.appending(queryItems: query))
        if query.isEmpty {
            request.httpMethod = "POST"
            request.httpBody = try JSONEncoder().encode(scenario)
        }
        let (data, response) = try await URLSession.shared.data(for: request)
        XCTAssertEqual((response as? HTTPURLResponse)?.statusCode, 200, "the stub refused \(command)")
        return data
    }

    private func read<Value: Decodable>(_ command: String, as type: Value.Type) async throws -> Value {
        let (data, _) = try await URLSession.shared.data(from: stubURL.appending(path: "__stub").appending(path: command))
        return try JSONDecoder().decode(type, from: data)
    }

    private func state() async throws -> StubState { try await read("state", as: StubState.self) }
    private func requests() async throws -> [StubRequest] { try await read("log", as: StubLog.self).requests }

    private func proposal(titled title: String) async throws -> StubState.Proposal {
        let raised = try await state().proposals.first { $0.title == title }
        return try XCTUnwrap(raised, "the stub raised no ‘\(title)’")
    }

    /// Answers once the app's request has reached the stub, so nothing that follows depends on timing.
    private func arrival(_ method: String, _ path: String, count: Int = 1) async throws {
        try await control("wait", query: [
            URLQueryItem(name: "method", value: method), URLQueryItem(name: "path", value: path),
            URLQueryItem(name: "count", value: String(count)),
        ])
    }

    // MARK: The app

    @MainActor
    private func open(arguments: [String] = [], environment: [String: String] = [:]) throws -> XCUIApplication {
        let app = XCUIApplication()
        app.launchEnvironment["ROUNDUP_API_URL"] = stubURL.absoluteString
        app.launchEnvironment["ROUNDUP_API_KEY"] = try XCTUnwrap(ProcessInfo.processInfo.environment["ROUNDUP_UITEST_API_KEY"])
        app.launchEnvironment.merge(environment) { _, added in added }
        app.skipOnboarding()
        app.launchArguments += arguments
        app.launch()
        return app
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

    /// Mean brightness of a screenshot, 0 for black and 1 for white.
    @MainActor
    private func brightness(of app: XCUIApplication) throws -> Double {
        let image = try XCTUnwrap(app.screenshot().image.cgImage)
        var pixels = [UInt8](repeating: 0, count: 32 * 32)
        let context = try XCTUnwrap(CGContext(
            data: &pixels, width: 32, height: 32, bitsPerComponent: 8, bytesPerRow: 32,
            space: CGColorSpaceCreateDeviceGray(), bitmapInfo: CGImageAlphaInfo.none.rawValue))
        context.draw(image, in: CGRect(x: 0, y: 0, width: 32, height: 32))
        return Double(pixels.reduce(0) { $0 + Int($1) }) / Double(pixels.count * 255)
    }

    /// Waits for an element to reach a state; the assertion fails when it never does.
    @MainActor
    private func expect(_ element: XCUIElement, _ format: String, argument: String? = nil, _ message: String) {
        let predicate = argument.map { NSPredicate(format: format, $0) } ?? NSPredicate(format: format)
        let outcome = XCTWaiter().wait(for: [XCTNSPredicateExpectation(predicate: predicate, object: element)], timeout: 30)
        XCTAssertEqual(outcome, .completed, message)
    }

    @MainActor
    private func named(_ identifier: String, in app: XCUIApplication) -> XCUIElement {
        app.descendants(matching: .any)[identifier].firstMatch
    }

    @MainActor
    private func stepRow(in app: XCUIApplication) -> XCUIElement {
        app.descendants(matching: .any).matching(NSPredicate(
            format: "identifier BEGINSWITH %@ AND NOT (identifier BEGINSWITH %@)", "agent.step.", "agent.step.undo."
        )).firstMatch
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
    private func ask(_ question: String, in app: XCUIApplication) {
        let field = named("assistant.field", in: app)
        XCTAssertTrue(field.waitForExistence(timeout: 20))
        field.tap()
        field.typeText(question)
        let send = app.buttons["assistant.send"]
        expect(send, "isEnabled == true", "the question cannot be sent")
        send.tap()
    }

    /// The step rows and cards under an answer appear once its text has been written out.
    @MainActor
    private func waitForAnswerToSettle(in app: XCUIApplication) {
        XCTAssertTrue(named("assistant.writing", in: app).waitForNonExistence(timeout: 30), "the answer never settled")
    }

    /// Pulls the page down and waits for the request it starts.
    @MainActor
    private func pullToRefresh(_ app: XCUIApplication, asking path: String) async throws {
        let before = try await requests().filter { $0.method == "GET" && $0.path == path }.count
        pullDown(app)
        try await arrival("GET", path, count: before + 1)
    }

    @MainActor
    private func openSettingsRow(_ identifier: String, in app: XCUIApplication) {
        let settings = app.tabBars.buttons["설정"]
        // A page scrolled down folds the tab bar to the current tab; scrolling up unfolds it.
        if !settings.waitForExistence(timeout: 15) { app.swipeDown() }
        XCTAssertTrue(settings.waitForExistence(timeout: 60))
        settings.tap()
        let row = app.buttons[identifier]
        XCTAssertTrue(scrollTo(row, in: app), "settings row \(identifier) is missing")
        row.tap()
    }

    // MARK: Runs in the chat

    @MainActor
    func testStatedFactIsDoneAtOnceAndUndoTakesItBack() async throws {
        let app = try open()
        openAssistant(in: app)
        ask("1040 포장 끝났어", in: app)

        let step = stepRow(in: app)
        XCTAssertTrue(step.waitForExistence(timeout: 30), "the answer shows no step")
        for part in ["포장 완료", "완료", "주문 1040", "1040 포장 끝났어"] {
            XCTAssertTrue(step.label.contains(part), "‘\(part)’ is missing from the step: \(step.label)")
        }
        let packed = try await state()
        XCTAssertEqual(packed.orders["1040"], "invoice_pending")
        waitForAnswerToSettle(in: app)
        try capture(app, "chat-auto-step")
        let light = try brightness(of: app)
        XCTAssertGreaterThan(light, 0.6, "this capture is meant to be the light appearance")

        let undo = undoButton(in: app)
        XCTAssertTrue(undo.waitForExistence(timeout: 10), "a step that can be undone offers no undo")
        undo.tap()
        XCTAssertTrue(undo.waitForNonExistence(timeout: 20), "the undo did not finish")
        XCTAssertTrue(stepRow(in: app).label.contains("되돌림"), "the step does not say it was undone")
        let restored = try await state()
        XCTAssertEqual(restored.orders["1040"], "packing")
        try capture(app, "chat-step-undone")
    }

    @MainActor
    func testRequestWithoutATargetAsksInsteadOfActing() async throws {
        let app = try open()
        openAssistant(in: app)
        ask("포장 끝났어", in: app)

        let step = stepRow(in: app)
        XCTAssertTrue(step.waitForExistence(timeout: 30))
        XCTAssertTrue(step.label.contains("확인 필요"), step.label)
        XCTAssertTrue(step.label.contains("어느 주문인지"), step.label)
        XCTAssertFalse(undoButton(in: app).exists, "a question must not offer an undo")
        let untouched = try await state()
        XCTAssertEqual(untouched.orders["1040"], "packing")
        XCTAssertEqual(untouched.orders["1042"], "packing")
        waitForAnswerToSettle(in: app)
        try capture(app, "chat-clarify")
    }

    @MainActor
    func testRefusedRequestSaysItWasNotDoneAndNothingIsSent() async throws {
        let app = try open()
        openAssistant(in: app)
        ask("김지은 님 예약 취소 처리해 줘", in: app)

        let step = stepRow(in: app)
        XCTAssertTrue(step.waitForExistence(timeout: 30))
        XCTAssertTrue(step.label.contains("건너뜀"), step.label)
        XCTAssertTrue(step.label.contains("직접 정하셔야"), step.label)
        XCTAssertFalse(undoButton(in: app).exists, "nothing was done, so there is nothing to undo")
        waitForAnswerToSettle(in: app)
        try capture(app, "chat-refused")

        ask("김지은 님한테 안내 문자 보내 줘", in: app)
        XCTAssertTrue(element(labelled: "보내는 일은 비서가 하지 않아요", in: app).waitForExistence(timeout: 30))
        let writes = try await requests().filter { $0.method != "GET" }.map(\.path)
        XCTAssertEqual(writes, ["/agent/run", "/agent/run"], "asking to send a message reached another route")
    }

    @MainActor
    func testAskModeProposesInTheChatAndActsOnlyAfterApproval() async throws {
        try await control("reset", Scenario(mode: "ask"))
        let app = try open()
        openAssistant(in: app)
        ask("1040 포장 끝났어", in: app)

        let approve = app.buttons.matching(NSPredicate(format: "identifier BEGINSWITH %@", "agent.proposal.approve.")).firstMatch
        XCTAssertTrue(approve.waitForExistence(timeout: 30), "the chat shows no proposal card")
        XCTAssertFalse(stepRow(in: app).exists, "the proposed step is shown beside its own card")
        XCTAssertTrue(element(labelled: "아직 아무것도 건드리지 않았어요", in: app).exists)
        let waiting = try await state()
        XCTAssertEqual(waiting.orders["1040"], "packing", "a proposal changed a row before any yes")
        waitForAnswerToSettle(in: app)
        try capture(app, "chat-proposal")

        approve.tap()
        XCTAssertTrue(undoButton(in: app).waitForExistence(timeout: 30), "the approved step is missing")
        let approved = try await state()
        XCTAssertEqual(approved.orders["1040"], "invoice_pending")
        try capture(app, "chat-proposal-approved")
    }

    @MainActor
    func testStoppedAssistantOnlyAnswers() async throws {
        try await control("reset", Scenario(mode: "off"))
        let app = try open()
        openAssistant(in: app)
        ask("1040 포장 끝났어", in: app)

        XCTAssertTrue(element(labelled: "지금은 답만 드려요", in: app).waitForExistence(timeout: 30))
        XCTAssertFalse(stepRow(in: app).exists)
        let paths = try await requests().map(\.path)
        XCTAssertTrue(paths.contains("/ask"))
        XCTAssertFalse(paths.contains("/agent/run"), "the stopped assistant was still asked to act")
        let untouched = try await state()
        XCTAssertEqual(untouched.orders["1040"], "packing")
    }

    @MainActor
    func testRunTheServerFailedIsNotReplacedByAPlainAnswer() async throws {
        let app = try open()
        openAssistant(in: app)
        ask("실패 시험 해 줘", in: app)

        XCTAssertTrue(app.buttons["assistant.retry"].waitForExistence(timeout: 30), "a failed run left no way to ask again")
        XCTAssertFalse(element(labelled: "지금은 답만 드려요", in: app).exists, "a plain answer covered a run that may have started")
        let writes = try await requests().filter { $0.method == "POST" }.map(\.path)
        XCTAssertEqual(writes, ["/agent/run"])
    }

    @MainActor
    func testLostReplyIsAskedForAgainAndRunsOnce() async throws {
        try await control("reset", Scenario(loseReply: true))
        let app = try open()
        openAssistant(in: app)
        ask("1040 포장 끝났어", in: app)

        let step = stepRow(in: app)
        XCTAssertTrue(step.waitForExistence(timeout: 30), "the run whose reply was lost never showed what it did")
        XCTAssertTrue(undoButton(in: app).waitForExistence(timeout: 10), "the recovered step lost its undo")
        let after = try await state()
        XCTAssertEqual(after.orders["1040"], "invoice_pending")
        XCTAssertEqual(after.questions.filter { $0 == "1040 포장 끝났어" }.count, 1, "the lost reply made a second run")
        let writes = try await requests().filter { $0.method == "POST" }.map(\.path)
        XCTAssertEqual(writes, ["/agent/run", "/agent/run"], "the same send was not simply repeated")
    }

    @MainActor
    func testServerWithoutAnAgentAnswersThroughAsk() async throws {
        try await control("reset", Scenario(noAgent: true))
        let app = try open()
        openAssistant(in: app)
        ask("1040 포장 끝났어", in: app)

        XCTAssertTrue(element(labelled: "지금은 답만 드려요", in: app).waitForExistence(timeout: 30))
        let writes = try await requests().filter { $0.method == "POST" }.map(\.path)
        XCTAssertEqual(writes, ["/ask"])
    }

    @MainActor
    func testSeveralJobsGoOnWhileTheOwnerLeaves() async throws {
        let app = try open()
        openAssistant(in: app)
        ask("1040 1042 포장 끝났어", in: app)

        let working = named("assistant.generating", in: app)
        XCTAssertTrue(working.waitForExistence(timeout: 30), "a run left to the server shows no progress line")
        XCTAssertTrue(working.label.contains("하는 중"), working.label)
        XCTAssertTrue(element(labelled: "나가셔도 하던 일은 마저 끝내 둘게요.", in: app).exists)

        try await control("advance")
        XCTAssertTrue(stepRow(in: app).waitForExistence(timeout: 30), "the first finished step never showed")
        expect(working, "label CONTAINS %@", argument: "1건 마침", "the progress line does not count what finished")
        try capture(app, "chat-background-running")

        app.navigationBars["비서"].buttons["닫기"].tap()
        XCTAssertTrue(app.navigationBars["비서"].waitForNonExistence(timeout: 20))
        try await control("advance")
        try await control("advance")
        let toast = named("toast.message", in: app)
        XCTAssertTrue(toast.waitForExistence(timeout: 30), "nothing says the run ended while the sheet was closed")
        XCTAssertTrue(toast.label.contains("부탁하신 일을 모두 마쳤어요"), toast.label)
        try capture(app, "background-finished-toast")
        let finished = try await state()
        XCTAssertEqual(finished.orders["1040"], "invoice_pending")
        XCTAssertEqual(finished.orders["1042"], "invoice_pending")

        openAssistant(in: app, startingNew: false)
        XCTAssertTrue(element(labelled: "주문 2건을 포장 완료로 바꿨어요", in: app).waitForExistence(timeout: 30))
        let steps = app.descendants(matching: .any).matching(NSPredicate(
            format: "identifier BEGINSWITH %@ AND NOT (identifier BEGINSWITH %@)", "agent.step.", "agent.step.undo."))
        XCTAssertEqual(steps.count, 2)
        try capture(app, "chat-background-done")
    }

    @MainActor
    func testQuestionAskedOfflineCanBeSentAgainAfterReconnecting() async throws {
        let app = try open()
        openAssistant(in: app)
        try await control("down", Scenario(down: true))
        ask("1040 포장 끝났어", in: app)

        let retry = app.buttons["assistant.retry"]
        XCTAssertTrue(retry.waitForExistence(timeout: 60), "an unreachable server left the question without a way on")
        XCTAssertTrue(element(labelled: "지금 연결이 안 돼요", in: app).exists)
        let untouched = try await state()
        XCTAssertEqual(untouched.orders["1040"], "packing")
        try capture(app, "chat-offline")

        try await control("down", Scenario(down: false))
        retry.tap()
        XCTAssertTrue(stepRow(in: app).waitForExistence(timeout: 30), "the question was not answered after reconnecting")
        let packed = try await state()
        XCTAssertEqual(packed.orders["1040"], "invoice_pending")
    }

    // MARK: Proposals

    @MainActor
    func testProposalOnTodayIsApprovedAndItsStepCanBeUndone() async throws {
        let app = try open()
        let header = named("agent.proposals.header", in: app)
        XCTAssertTrue(header.waitForExistence(timeout: 60), "Today shows no proposals")
        XCTAssertEqual(header.label, "비서의 확인 요청 2건")
        let judgments = named("bk25.judgments.header", in: app)
        XCTAssertTrue(judgments.waitForExistence(timeout: 10), "the judgment cards are missing")
        XCTAssertLessThan(header.frame.minY, judgments.frame.minY, "proposals must sit above the judgment cards")
        try capture(app, "today-proposals")

        let confirm = try await proposal(titled: "주문 1041을 확인할까요?")
        app.buttons["agent.proposal.row.\(confirm.id)"].tap()
        let approve = app.buttons["agent.proposal.approve.\(confirm.id)"]
        XCTAssertTrue(approve.waitForExistence(timeout: 20))
        XCTAssertTrue(app.buttons["agent.proposal.dismiss.\(confirm.id)"].exists)
        XCTAssertTrue(element(labelled: "확인 전", in: app).exists)
        XCTAssertTrue(element(labelled: "아직 아무것도 건드리지 않았어요", in: app).exists)
        XCTAssertTrue(element(labelled: "필요한 것", in: app).exists)
        let waiting = try await state()
        XCTAssertEqual(waiting.orders["1041"], "paid", "a proposal changed a row before any yes")
        try capture(app, "proposal-open")

        approve.tap()
        let undo = undoButton(in: app)
        XCTAssertTrue(undo.waitForExistence(timeout: 30), "the result of the approval is missing")
        XCTAssertFalse(approve.exists, "an approved proposal can be approved again")
        XCTAssertTrue(element(labelled: "수락했어요", in: app).exists)
        let approved = try await state()
        XCTAssertEqual(approved.orders["1041"], "packing")
        try capture(app, "proposal-approved")

        undo.tap()
        XCTAssertTrue(undo.waitForNonExistence(timeout: 20))
        let restored = try await state()
        XCTAssertEqual(restored.orders["1041"], "paid")
    }

    @MainActor
    func testDismissedProposalChangesNothing() async throws {
        let app = try open()
        let deposit = try await proposal(titled: "김지은 님 예약금을 확인 처리할까요?")
        let row = app.buttons["agent.proposal.row.\(deposit.id)"]
        XCTAssertTrue(row.waitForExistence(timeout: 60))
        row.tap()
        let dismiss = app.buttons["agent.proposal.dismiss.\(deposit.id)"]
        XCTAssertTrue(dismiss.waitForExistence(timeout: 20))
        dismiss.tap()

        XCTAssertTrue(dismiss.waitForNonExistence(timeout: 20))
        XCTAssertTrue(element(labelled: "거절하신 요청이에요. 바꾼 건 없어요.", in: app).waitForExistence(timeout: 10))
        let after = try await state()
        XCTAssertFalse(after.depositConfirmed)
        XCTAssertEqual(after.proposals.first { $0.id == deposit.id }?.state, "dismissed")
        try capture(app, "proposal-dismissed")
    }

    @MainActor
    func testExpiredProposalOffersNoApproval() async throws {
        try await control("reset", Scenario(expired: true))
        let app = try open()
        let expired = try await proposal(titled: "주문 1038을 배송 완료로 바꿀까요?")
        let row = app.buttons["agent.proposal.row.\(expired.id)"]
        XCTAssertTrue(row.waitForExistence(timeout: 60))
        try capture(app, "today-proposal-expired")
        row.tap()

        XCTAssertTrue(named("agent.proposal.\(expired.id)", in: app).waitForExistence(timeout: 20))
        XCTAssertTrue(element(labelled: "기간이 지난 확인 요청이에요", in: app).exists)
        XCTAssertFalse(app.buttons["agent.proposal.approve.\(expired.id)"].exists, "an expired proposal can still be approved")
        XCTAssertFalse(app.buttons["agent.proposal.dismiss.\(expired.id)"].exists)
        let open = try await proposal(titled: "주문 1041을 확인할까요?")
        XCTAssertTrue(scrollTo(app.buttons["agent.proposal.approve.\(open.id)"], in: app), "a proposal still in time lost its approval")
        let untouched = try await state()
        XCTAssertEqual(untouched.orders["1038"], "in_transit")
        try capture(app, "proposal-expired")
    }

    @MainActor
    func testProposalListReconnectsByItself() async throws {
        let app = try open()
        let confirm = try await proposal(titled: "주문 1041을 확인할까요?")
        let row = app.buttons["agent.proposal.row.\(confirm.id)"]
        XCTAssertTrue(row.waitForExistence(timeout: 60))
        row.tap()
        let approve = app.buttons["agent.proposal.approve.\(confirm.id)"]
        XCTAssertTrue(approve.waitForExistence(timeout: 20))

        try await control("down", Scenario(down: true))
        try await pullToRefresh(app, asking: "/agent/proposals")
        let notice = named("connection.notice", in: app)
        XCTAssertTrue(notice.waitForExistence(timeout: 30), "a refresh that failed says nothing")
        XCTAssertTrue(approve.exists, "the last proposals were thrown away")
        try capture(app, "proposals-offline")

        try await control("down", Scenario(down: false))
        XCTAssertTrue(notice.waitForNonExistence(timeout: 60), "the proposal list did not reconnect by itself")
    }

    // MARK: History

    @MainActor
    func testHistoryFiltersBySourceAndUndoesAStep() async throws {
        let app = try open()
        openSettingsRow("settings.activities", in: app)
        let chat = element(labelled: "내일 10시에 가마 청소 넣어 줘", in: app)
        let voice = element(labelled: "1039 포장 끝났어", in: app)
        let draft = element(labelled: "주말 클래스 홍보 글 초안을 썼어요", in: app)
        XCTAssertTrue(chat.waitForExistence(timeout: 30), "the history is empty")
        try capture(app, "history")

        app.segmentedControls.buttons["음성"].tap()
        XCTAssertTrue(scrollTo(voice, in: app))
        XCTAssertFalse(chat.exists, "a chat run stayed under the voice filter")
        app.segmentedControls.buttons["먼저 챙긴 일"].tap()
        XCTAssertTrue(scrollTo(draft, in: app), "what the assistant wrote unasked is missing")
        XCTAssertFalse(voice.exists)
        app.segmentedControls.buttons["채팅"].tap()
        XCTAssertTrue(chat.waitForExistence(timeout: 10))
        XCTAssertFalse(draft.exists)

        let undo = undoButton(in: app)
        XCTAssertTrue(scrollTo(undo, in: app), "the step that can be undone offers no undo")
        undo.tap()
        XCTAssertTrue(undo.waitForNonExistence(timeout: 20))
        XCTAssertTrue(element(labelled: "되돌림", in: app).waitForExistence(timeout: 10))
        try capture(app, "history-undone")
    }

    @MainActor
    func testEmptyHistoryAndMemorySayWhatBelongsThere() async throws {
        try await control("reset", Scenario(empty: true))
        let app = try open()
        openSettingsRow("settings.activities", in: app)
        XCTAssertTrue(named("activity.empty", in: app).waitForExistence(timeout: 30))
        try capture(app, "history-empty")

        app.navigationBars.buttons.element(boundBy: 0).tap()
        openSettingsRow("settings.delegation", in: app)
        let memories = app.buttons["agent.settings.memories"]
        XCTAssertTrue(scrollTo(memories, in: app))
        memories.tap()
        XCTAssertTrue(named("agent.memories.empty", in: app).waitForExistence(timeout: 30))
        try capture(app, "memories-empty")
    }

    @MainActor
    func testOfflineKeepsTheLastHistoryAndReconnectsByItself() async throws {
        let app = try open()
        openSettingsRow("settings.activities", in: app)
        let run = element(labelled: "내일 10시에 가마 청소 넣어 줘", in: app)
        XCTAssertTrue(run.waitForExistence(timeout: 30))

        try await control("down", Scenario(down: true))
        try await pullToRefresh(app, asking: "/agent/runs")
        let notice = named("connection.notice", in: app)
        XCTAssertTrue(notice.waitForExistence(timeout: 30), "a refresh that failed says nothing")
        XCTAssertTrue(run.exists, "the last history was thrown away")
        try capture(app, "history-offline")

        let undo = undoButton(in: app)
        XCTAssertTrue(scrollTo(undo, in: app))
        undo.tap()
        let failure = app.alerts["이번엔 마무리하지 못했어요"]
        XCTAssertTrue(failure.waitForExistence(timeout: 20), "an undo that could not reach the server said nothing")
        failure.buttons["확인"].tap()
        XCTAssertTrue(undo.exists, "a step that was not undone lost its undo")

        try await control("down", Scenario(down: false))
        XCTAssertTrue(notice.waitForNonExistence(timeout: 60), "the screen did not reconnect by itself")
        try capture(app, "history-reconnected")
    }

    // MARK: Settings

    @MainActor
    func testAutonomySettingsAreSavedAndReadBack() async throws {
        var app = try open()
        openSettingsRow("settings.delegation", in: app)
        let ask = app.segmentedControls.buttons["물어보고 하기"]
        XCTAssertTrue(ask.waitForExistence(timeout: 30))
        try capture(app, "settings-autonomy")
        ask.tap()
        try await arrival("PUT", "/agent/settings", count: 1)
        XCTAssertTrue(element(labelled: "무언가 바꿔야 할 땐 확인 요청부터 보내요. 사장님이 수락하시면 그때 움직여요.", in: app).waitForExistence(timeout: 10))

        let invoice = named("agent.settings.tool.register_invoice", in: app)
        XCTAssertTrue(scrollTo(invoice, in: app), "the invoice tool has no row")
        XCTAssertTrue(element(labelled: "숫자 하나 바꾸지 않고 등록해요", in: app).exists, "nothing says invoice numbers are used as given")
        invoice.tap()
        let off = app.buttons["꺼 두기"]
        XCTAssertTrue(off.waitForExistence(timeout: 10), "the tool's choices did not open")
        off.tap()
        try await arrival("PUT", "/agent/settings", count: 2)

        let more = app.steppers["agent.settings.cap"].buttons.element(boundBy: 1)
        XCTAssertTrue(scrollTo(more, in: app))
        more.tap()
        try await arrival("PUT", "/agent/settings", count: 3)

        let saved = try await state()
        XCTAssertEqual(saved.settings.mode, "ask")
        XCTAssertEqual(saved.settings.tools.first { $0.tool == "register_invoice" }?.mode, "off")
        XCTAssertEqual(saved.settings.tools.first { $0.tool == "mark_packed" }?.mode, "ask")
        XCTAssertEqual(saved.settings.dailyCap, 21)

        app.terminate()
        app = try open()
        openSettingsRow("settings.delegation", in: app)
        XCTAssertTrue(app.segmentedControls.buttons["물어보고 하기"].waitForExistence(timeout: 30))
        XCTAssertTrue(app.segmentedControls.buttons["물어보고 하기"].isSelected, "the saved mode was not read back")
        let reopened = named("agent.settings.tool.register_invoice", in: app)
        XCTAssertTrue(scrollTo(reopened, in: app))
        let shown = "\(reopened.label) \(reopened.value as? String ?? "")"
        XCTAssertTrue(shown.contains("꺼 두기"), "the saved tool choice was not read back: \(shown)")
        XCTAssertTrue(scrollTo(app.steppers["agent.settings.cap"].buttons.element(boundBy: 1), in: app))
        XCTAssertTrue(element(labelled: "하루 21건까지", in: app).exists, "the saved daily cap was not read back")
        try capture(app, "settings-read-back")
    }

    @MainActor
    func testKillSwitchStopsEverythingAndNamesWhatCanNeverBeHandedOver() async throws {
        let app = try open()
        openSettingsRow("settings.delegation", in: app)
        let stop = app.buttons["agent.settings.stop"]
        XCTAssertTrue(stop.waitForExistence(timeout: 30))
        XCTAssertTrue(stop.isHittable, "the stop control is not in reach before any scrolling")
        stop.tap()
        try await arrival("PUT", "/agent/settings")
        XCTAssertTrue(app.buttons["agent.settings.resume"].waitForExistence(timeout: 10))
        let stopped = try await state()
        XCTAssertEqual(stopped.settings.mode, "off")
        XCTAssertEqual(Set(stopped.settings.tools.map(\.mode)), ["off"])
        try capture(app, "settings-stopped")

        XCTAssertTrue(scrollTo(element(labelled: "꺼 두신 동안엔 일마다 정할 수 없어요. 다시 켜시면 그때 하나하나 고르시면 돼요.", in: app), in: app))
        let never = element(labelled: "손님께 메시지 전송", in: app)
        XCTAssertTrue(scrollTo(never, in: app), "what can never be handed over is not listed")
        XCTAssertTrue(never.label.contains("맡기실 수 없어요"), never.label)
        try capture(app, "settings-never-delegated")
    }

    @MainActor
    func testRememberedThingsShowTheOwnersWordsAndCanBeForgotten() async throws {
        let app = try open()
        openSettingsRow("settings.delegation", in: app)
        let link = app.buttons["agent.settings.memories"]
        XCTAssertTrue(scrollTo(link, in: app))
        link.tap()

        let memory = named("agent.memory.mem-1", in: app)
        XCTAssertTrue(memory.waitForExistence(timeout: 30))
        XCTAssertTrue(memory.label.contains("택배는 주로 CJ대한통운으로 보내요"), memory.label)
        XCTAssertTrue(memory.label.contains("우리는 거의 CJ로 보내"), "the owner's own sentence is missing: \(memory.label)")
        try capture(app, "memories")

        app.buttons["agent.memory.forget.mem-1"].tap()
        let confirm = app.buttons["지우기"].firstMatch
        XCTAssertTrue(confirm.waitForExistence(timeout: 10), "forgetting did not ask first")
        confirm.tap()
        XCTAssertTrue(memory.waitForNonExistence(timeout: 20))
        let after = try await state()
        XCTAssertEqual(after.memories, ["mem-2"])
    }

    // MARK: Proposals that cannot run on a yes

    @MainActor
    func testProposalWithoutItsNumberTakesTheNumberAsTheOwnersOwnTurn() async throws {
        try await control("reset", Scenario(needsValue: true))
        let app = try open()
        let invoice = try await proposal(titled: "주문 1046 송장 등록")
        let row = app.buttons["agent.proposal.row.\(invoice.id)"]
        XCTAssertTrue(row.waitForExistence(timeout: 60))
        row.tap()

        let field = named("bk25.field", in: app)
        XCTAssertTrue(field.waitForExistence(timeout: 20), "a card that lacks its number has no place to give it")
        XCTAssertFalse(app.buttons["agent.proposal.approve.\(invoice.id)"].exists, "a plain approve is offered without the number")
        XCTAssertTrue(element(labelled: "손댄 건 아직 없어요. 번호만 알려 주시면 송장을 바로 넣어 둘게요.", in: app).exists)
        // Other cards on the page may say this; this one must not.
        let card = named("agent.proposal.\(invoice.id)", in: app)
        XCTAssertFalse(card.descendants(matching: .any).matching(NSPredicate(format: "label CONTAINS %@", "수락해 주시면 그때 시작할게요")).firstMatch.exists,
                       "the card promises what a yes cannot do")
        let send = app.buttons["agent.proposal.supply.\(invoice.id)"]
        XCTAssertFalse(send.isEnabled, "nothing was said yet")
        try capture(app, "proposal-needs-number")

        field.tap()
        field.typeText("682100042896")
        expect(send, "isEnabled == true", "the number was typed but cannot be sent")
        send.tap()
        XCTAssertTrue(undoButton(in: app).waitForExistence(timeout: 30), "the registered invoice shows no step")
        let after = try await state()
        XCTAssertEqual(after.orders["1046"], "in_transit")
        XCTAssertEqual(after.invoices["1046"], "682100042896", "the number was not used as given")
        XCTAssertTrue(after.questions.contains("주문 1046 · 서지안 님 송장 번호 682100042896"), "the number did not go out as the owner's own turn: \(after.questions)")
        let approvals = try await requests().filter { $0.path.hasSuffix("/approve") }
        XCTAssertTrue(approvals.isEmpty, "the number was sent through an approval")
        try capture(app, "proposal-number-given")

        // Taking a registered invoice back deletes its number, so the app asks once more first.
        let undo = undoButton(in: app)
        undo.tap()
        let confirm = app.buttons["송장을 지우고 되돌릴게요"]
        XCTAssertTrue(confirm.waitForExistence(timeout: 10), "the invoice is cleared without asking")
        let asked = try await state()
        XCTAssertEqual(asked.orders["1046"], "in_transit", "the step was undone before the owner confirmed")
        confirm.tap()
        XCTAssertTrue(undo.waitForNonExistence(timeout: 20), "the undo did not finish")
        let restored = try await state()
        XCTAssertEqual(restored.orders["1046"], "invoice_pending")
        XCTAssertNil(restored.invoices["1046"], "the undone step kept its number")
        try capture(app, "proposal-number-undone")
    }

    // MARK: Invoice files

    @MainActor
    private func invoiceFile() throws -> (url: URL, bytes: Int) {
        let file = FileManager.default.temporaryDirectory.appendingPathComponent("송장-11월22일.csv")
        let contents = """
        주문번호,택배사,송장번호
        1044,CJ대한통운,682100042841
        1045,CJ대한통운,682100042852
        1046,CJ대한통운,68210004
        1038,CJ대한통운,682100042863
        9999,CJ대한통운,682100042874

        """
        try Data(contents.utf8).write(to: file)
        addTeardownBlock { try? FileManager.default.removeItem(at: file) }
        return (file, Data(contents.utf8).count)
    }

    @MainActor
    func testInvoiceFileIsRegisteredByOneApprovalThatSendsTheFileAgain() async throws {
        let file = try invoiceFile()
        let app = try open(environment: ["ROUNDUP_UITEST_INVOICE_FILE": file.url.path])
        openAssistant(in: app)
        app.buttons["assistant.import"].tap()
        let summary = named("invoice.import.summary", in: app)
        XCTAssertTrue(summary.waitForExistence(timeout: 30), "the file was not read")
        XCTAssertTrue(summary.label.contains("파일에서 찾은 송장번호 5개"), summary.label)
        XCTAssertTrue(summary.label.contains("사장님이 수락하시기 전엔 한 건도 넣지 않아요."), summary.label)
        let read = try await state()
        XCTAssertEqual(read.orders["1044"], "invoice_pending", "reading a file registered a number")
        let raised = try await proposal(titled: "송장 파일로 한 번에 넣기")

        let approve = app.buttons["invoice.import.approve"]
        XCTAssertTrue(approve.waitForExistence(timeout: 10))
        XCTAssertTrue(approve.label.contains("2건"), "the approval does not start with the clean rows only: \(approve.label)")
        let accept = app.switches["invoice.import.accept.4"]
        XCTAssertTrue(scrollTo(accept, in: app), "the row with a format warning has no switch of its own")
        XCTAssertTrue(element(labelled: "택배사 송장번호 형식과 맞지 않아요", in: app).exists, "the warning is not stated")
        let blocked = named("invoice.import.leftOut.5", in: app)
        XCTAssertTrue(scrollTo(blocked, in: app), "the row that cannot be registered is not listed")
        XCTAssertTrue(blocked.label.contains("벌써 보낸 택배예요."), "a blocked row gives no reason: \(blocked.label)")
        let unclear = named("invoice.import.leftOut.6", in: app)
        XCTAssertTrue(scrollTo(unclear, in: app), "the row whose order is unclear is not listed")
        XCTAssertTrue(unclear.label.contains("이 줄이 어느 주문 건인지 딱 하나로 못 골랐어요."))
        XCTAssertEqual(app.buttons.matching(NSPredicate(format: "identifier BEGINSWITH %@", "invoice.import.approve")).count, 1,
                       "more than the one approval for the file is offered")
        try capture(app, "invoice-file-read")

        // A switch row answers a tap on its own inner switch; the row's middle is its label.
        let inner = accept.switches.firstMatch
        (inner.exists ? inner : accept).tap()
        // The approval sits above the rows just read. One that slid under the bar still counts as hittable.
        for _ in 0..<6 where approve.frame.minY < 150 { app.swipeDown() }
        XCTAssertTrue(approve.isHittable)
        expect(approve, "label CONTAINS %@", argument: "3건", "the switched row did not join the one approval")
        try capture(app, "invoice-file-warning-accepted")
        approve.tap()

        let done = named("invoice.import.registered", in: app)
        XCTAssertTrue(done.waitForExistence(timeout: 30), "nothing says what the approval registered")
        XCTAssertTrue(done.label.contains("송장 3건 등록 끝!"), done.label)
        XCTAssertTrue(done.label.contains("나머지 2건은 파일을 한 번 더 올리셔야"), done.label)
        XCTAssertFalse(approve.exists, "the same file can be approved twice")
        let after = try await state()
        XCTAssertEqual([after.orders["1044"], after.orders["1045"], after.orders["1046"]], ["in_transit", "in_transit", "in_transit"])
        XCTAssertEqual(after.invoices["1046"], "68210004", "the number was not used as the file gave it")
        try capture(app, "invoice-file-registered")

        let uploads = try await requests().filter { $0.path.hasPrefix("/agent/invoices/") }
        XCTAssertEqual(uploads.map(\.path), ["/agent/invoices/import", "/agent/invoices/\(raised.id)/approve"])
        XCTAssertEqual(Set(uploads.map(\.bytes)), [file.bytes], "the approval sent other bytes than the file read")
        XCTAssertEqual(uploads[1].query, ["filename": file.url.lastPathComponent, "acceptFormat": "4"])

        app.navigationBars.buttons.element(boundBy: 0).tap()
        XCTAssertTrue(element(labelled: "등록 수락", in: app).waitForExistence(timeout: 20), "the chat kept no record of the approval")
    }

    @MainActor
    func testFileProposalSeenLaterAsksForTheFileInsteadOfAYes() async throws {
        let file = try invoiceFile()
        let app = try open(environment: ["ROUNDUP_UITEST_INVOICE_FILE": file.url.path])
        openAssistant(in: app)
        app.buttons["assistant.import"].tap()
        XCTAssertTrue(named("invoice.import.summary", in: app).waitForExistence(timeout: 30))
        let left = try await proposal(titled: "송장 파일로 한 번에 넣기")
        app.navigationBars.buttons.element(boundBy: 0).tap()
        app.navigationBars["비서"].buttons["닫기"].tap()

        let row = app.buttons["agent.proposal.row.\(left.id)"]
        XCTAssertTrue(scrollTo(row, in: app), "the file left unapproved is not among Today's proposals")
        row.tap()
        let again = app.buttons["agent.proposal.repick.\(left.id)"]
        XCTAssertTrue(again.waitForExistence(timeout: 20), "the file card does not ask for the file")
        XCTAssertFalse(app.buttons["agent.proposal.approve.\(left.id)"].exists, "a file card offers a yes it cannot keep")
        XCTAssertTrue(element(labelled: "송장은 아직 한 건도 등록하지 않았어요. 휴대폰에 파일을 남겨 두지 않으니 같은 파일을 한 번 더 골라 주셔야 등록돼요.", in: app).exists)
        try capture(app, "proposal-file-again")

        again.tap()
        let approve = app.buttons["invoice.import.approve"]
        XCTAssertTrue(approve.waitForExistence(timeout: 30))
        approve.tap()
        XCTAssertTrue(named("invoice.import.registered", in: app).waitForExistence(timeout: 30))
        let after = try await state()
        XCTAssertEqual(after.orders["1044"], "in_transit")
        XCTAssertEqual(after.proposals.first { $0.id == left.id }?.state, "dismissed", "the card that asked for the file still waits")
        XCTAssertEqual(after.proposals.filter { $0.title == "송장 파일로 한 번에 넣기" && $0.state == "open" }.count, 0)
    }

    @MainActor
    func testFileWithNoCleanRowOffersNoApproval() async throws {
        try await control("reset", Scenario(dirtyFile: true))
        let file = try invoiceFile()
        let app = try open(environment: ["ROUNDUP_UITEST_INVOICE_FILE": file.url.path])
        openAssistant(in: app)
        app.buttons["assistant.import"].tap()
        XCTAssertTrue(named("invoice.import.nothing", in: app).waitForExistence(timeout: 30), "nothing says why there is no approval")
        XCTAssertFalse(app.buttons["invoice.import.approve"].exists)
        XCTAssertTrue(scrollTo(named("invoice.import.leftOut.5", in: app), in: app), "the rows do not show why")
        try capture(app, "invoice-file-nothing-clean")
    }

    // MARK: Appearance and text size

    @MainActor
    func testDarkAppearanceShowsTheSameStates() async throws {
        try requireDarkSimulator()
        let app = try open()
        let header = named("agent.proposals.header", in: app)
        XCTAssertTrue(header.waitForExistence(timeout: 60))
        let dark = try brightness(of: app)
        XCTAssertLessThan(dark, 0.35, "the dark appearance did not apply")
        try capture(app, "dark-today-proposals")

        let confirm = try await proposal(titled: "주문 1041을 확인할까요?")
        app.buttons["agent.proposal.row.\(confirm.id)"].tap()
        XCTAssertTrue(app.buttons["agent.proposal.approve.\(confirm.id)"].waitForExistence(timeout: 20))
        try capture(app, "dark-proposal-open")
        app.navigationBars.buttons.element(boundBy: 0).tap()

        openAssistant(in: app)
        ask("1040 포장 끝났어", in: app)
        XCTAssertTrue(stepRow(in: app).waitForExistence(timeout: 30))
        waitForAnswerToSettle(in: app)
        try capture(app, "dark-chat-auto-step")
        app.navigationBars["비서"].buttons["닫기"].tap()

        openSettingsRow("settings.delegation", in: app)
        XCTAssertTrue(app.buttons["agent.settings.stop"].waitForExistence(timeout: 30))
        try capture(app, "dark-settings-autonomy")
    }

    @MainActor
    func testLargestTextKeepsEveryControlInReach() async throws {
        let app = try open(arguments: ["-UIPreferredContentSizeCategoryName", "UICTContentSizeCategoryAccessibilityXL"])
        let confirm = try await proposal(titled: "주문 1041을 확인할까요?")
        let row = app.buttons["agent.proposal.row.\(confirm.id)"]
        XCTAssertTrue(scrollTo(row, in: app), "the proposal is out of reach at the largest text")
        try capture(app, "large-today-proposals")
        row.tap()
        let approve = app.buttons["agent.proposal.approve.\(confirm.id)"]
        let dismiss = app.buttons["agent.proposal.dismiss.\(confirm.id)"]
        XCTAssertTrue(scrollTo(approve, in: app))
        XCTAssertGreaterThanOrEqual(approve.frame.height, 44)
        try capture(app, "large-proposal-open")
        XCTAssertTrue(scrollTo(dismiss, in: app))
        XCTAssertGreaterThanOrEqual(dismiss.frame.height, 44)
        XCTAssertGreaterThan(dismiss.frame.minY, approve.frame.maxY - 1, "the two answers sit side by side at the largest text")
        app.navigationBars.buttons.element(boundBy: 0).tap()

        openAssistant(in: app)
        ask("1040 포장 끝났어", in: app)
        let undo = undoButton(in: app)
        XCTAssertTrue(undo.waitForExistence(timeout: 30))
        waitForAnswerToSettle(in: app)
        XCTAssertTrue(scrollTo(undo, in: app))
        XCTAssertGreaterThanOrEqual(undo.frame.height, 44)
        XCTAssertGreaterThan(undo.frame.width, 200, "the undo did not become a full-width button that names itself")
        try capture(app, "large-chat-auto-step")
        app.navigationBars["비서"].buttons["닫기"].tap()

        openSettingsRow("settings.delegation", in: app)
        let stop = app.buttons["agent.settings.stop"]
        XCTAssertTrue(scrollTo(stop, in: app))
        try capture(app, "large-settings-autonomy")
    }
}
