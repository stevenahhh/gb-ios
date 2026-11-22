import XCTest

/// What the assistant agent's flow tests share; it has no tests of its own.
class AgentFlowCase: RoundupUITestCase {
    var server: URL!
    var apiKey = ""

    static let largestText = ["-UIPreferredContentSizeCategoryName", "UICTContentSizeCategoryAccessibilityXXXL"]

    /// Reads the server's address and key, or skips while `gate` is not 1.
    func connect(gate: String, address: String, key: String) throws {
        continueAfterFailure = false
        let environment = ProcessInfo.processInfo.environment
        guard environment[gate] == "1", let url = environment[address], let secret = environment[key] else {
            throw XCTSkip("Set TEST_RUNNER_\(gate)=1, TEST_RUNNER_\(address) and TEST_RUNNER_\(key)")
        }
        server = try XCTUnwrap(URL(string: url))
        apiKey = secret
    }

    override func tearDown() async throws {
        await MainActor.run { XCUIApplication().terminate() }
    }

    // MARK: The server's test controls

    @discardableResult
    func post(_ path: String, _ body: [String: Any] = [:]) async throws -> Data {
        var request = URLRequest(url: server.appending(path: path))
        request.httpMethod = "POST"
        request.httpBody = try JSONSerialization.data(withJSONObject: body)
        let (data, response) = try await URLSession.shared.data(for: request)
        XCTAssertEqual((response as? HTTPURLResponse)?.statusCode, 200, "the server refused \(path)")
        return data
    }

    func read<Value: Decodable>(_ path: String, as type: Value.Type) async throws -> Value {
        let (data, _) = try await URLSession.shared.data(from: server.appending(path: path))
        return try JSONDecoder().decode(type, from: data)
    }

    // MARK: The app

    @MainActor
    func open(arguments: [String] = [], dark: Bool = false) throws -> XCUIApplication {
        if dark { try requireDarkSimulator() }
        let app = XCUIApplication()
        app.launchEnvironment["ROUNDUP_API_URL"] = server.absoluteString
        app.launchEnvironment["ROUNDUP_API_KEY"] = apiKey
        app.skipOnboarding()
        app.launchArguments += arguments
        app.launch()
        XCTAssertTrue(app.buttons["assistant.accessory"].waitForExistence(timeout: 60), "the assistant bar is missing")
        return app
    }

    @MainActor
    func capture(_ app: XCUIApplication, _ name: String) throws {
        keepScreenshot(of: app, named: name)
        guard let directory = ProcessInfo.processInfo.environment["AGENT_UITEST_SHOT_DIR"] else { return }
        try app.screenshot().pngRepresentation.write(to: URL(fileURLWithPath: directory).appendingPathComponent("\(name).png"))
    }

    /// Mean brightness of a screenshot, 0 for black and 1 for white.
    @MainActor
    func brightness(of app: XCUIApplication) throws -> Double {
        let image = try XCTUnwrap(app.screenshot().image.cgImage)
        var pixels = [UInt8](repeating: 0, count: 32 * 32)
        let context = try XCTUnwrap(CGContext(
            data: &pixels, width: 32, height: 32, bitsPerComponent: 8, bytesPerRow: 32,
            space: CGColorSpaceCreateDeviceGray(), bitmapInfo: CGImageAlphaInfo.none.rawValue))
        context.draw(image, in: CGRect(x: 0, y: 0, width: 32, height: 32))
        return Double(pixels.reduce(0) { $0 + Int($1) }) / Double(pixels.count * 255)
    }

    @MainActor
    func checkAppearance(of app: XCUIApplication, dark: Bool) throws {
        let mean = try brightness(of: app)
        XCTAssertTrue(dark ? mean < 0.35 : mean > 0.6, "the \(dark ? "dark" : "light") appearance did not apply: \(mean)")
    }

    @MainActor
    func expect(_ element: XCUIElement, _ format: String, _ message: String) {
        let reached = XCTNSPredicateExpectation(predicate: NSPredicate(format: format), object: element)
        XCTAssertEqual(XCTWaiter().wait(for: [reached], timeout: 30), .completed, message)
    }

    @MainActor
    func named(_ identifier: String, in app: XCUIApplication) -> XCUIElement {
        app.descendants(matching: .any)[identifier].firstMatch
    }

    @MainActor
    func step(saying text: String, in app: XCUIApplication) -> XCUIElement {
        app.descendants(matching: .any).matching(NSPredicate(
            format: "identifier BEGINSWITH 'agent.step.' AND NOT (identifier BEGINSWITH 'agent.step.undo.') AND label CONTAINS %@", text
        )).firstMatch
    }

    @MainActor
    func button(_ prefix: String, in app: XCUIApplication) -> XCUIElement {
        app.buttons.matching(NSPredicate(format: "identifier BEGINSWITH %@", prefix)).firstMatch
    }

    @MainActor
    func openAssistant(in app: XCUIApplication) {
        app.buttons["assistant.accessory"].tap()
        let bar = app.navigationBars["비서"]
        XCTAssertTrue(bar.waitForExistence(timeout: 20))
        // An earlier test's conversation is recent enough to reopen, so each test starts its own.
        let new = app.buttons["assistant.new"]
        if new.exists { new.tap() }
        XCTAssertTrue(new.waitForNonExistence(timeout: 10), "an earlier conversation stayed open")
        let top = app.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.08))
        bar.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.1)).press(forDuration: 0.1, thenDragTo: top)
    }

    @MainActor
    func ask(_ question: String, in app: XCUIApplication) {
        let field = named("assistant.field", in: app)
        XCTAssertTrue(field.waitForExistence(timeout: 20))
        field.tap()
        field.typeText(question)
        let send = app.buttons["assistant.send"]
        expect(send, "isEnabled == true", "the question cannot be sent")
        send.tap()
    }

    /// Step rows and cards show once the answer's text has been written out.
    @MainActor
    func waitForAnswerToSettle(in app: XCUIApplication) {
        XCTAssertTrue(named("assistant.writing", in: app).waitForNonExistence(timeout: 30), "the answer never settled")
    }

    /// Scrolls back to something in an earlier exchange of the conversation.
    @MainActor
    func scrollBack(to target: XCUIElement, in app: XCUIApplication) -> Bool {
        for _ in 0..<6 {
            // One that slid under the bar still counts as hittable.
            if target.waitForExistence(timeout: 2), target.isHittable, target.frame.minY > 150 { return true }
            let start = app.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.3))
            start.press(forDuration: 0.05, thenDragTo: app.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.5)))
        }
        return target.exists && target.isHittable
    }

    @MainActor
    func checkFits(_ control: XCUIElement, in app: XCUIApplication, _ name: String) {
        XCTAssertGreaterThanOrEqual(control.frame.height, 44, "\(name) is under 44 points tall")
        XCTAssertGreaterThanOrEqual(control.frame.width, 44, "\(name) is under 44 points wide")
        XCTAssertGreaterThanOrEqual(control.frame.minX, app.frame.minX, "\(name) is cut off")
        XCTAssertLessThanOrEqual(control.frame.maxX, app.frame.maxX, "\(name) is cut off")
    }
}

/// The agent's actions, proposals, undo, and history against the server's own code in `Server/`, with a scripted
/// chat model and a scratch database. Skipped unless ROUNDUP_UITEST_AGENT_REAL is 1.
///
/// Two paid orders, 1042 and 1043, are in play with the same tool, so an undo that takes back the wrong one shows.
final class AgentRealServerUITests: AgentFlowCase {
    private struct State: Decodable {
        struct Order: Decodable {
            let number: Int
            let status: String
            let shipment: String?
        }

        struct Step: Decodable {
            let id: String
            let targetId: String?
            let undone: Bool
        }

        struct Proposal: Decodable {
            let id: String
            let stepId: String
            let state: String
            let targetId: String?
        }

        let orders: [Order]
        let steps: [Step]
        let proposals: [Proposal]
    }

    override func setUp() async throws {
        try connect(gate: "ROUNDUP_UITEST_AGENT_REAL", address: "ROUNDUP_UITEST_REAL_URL", key: "ROUNDUP_UITEST_REAL_KEY")
        try await post("__flows/reset")
    }

    private func state() async throws -> State { try await read("__flows/state", as: State.self) }

    private func step(on order: Int) async throws -> State.Step {
        let found = try await state().steps.first { $0.targetId == "order-\(order)" }
        return try XCTUnwrap(found, "the server has no step on order \(order)")
    }

    private func proposal(on order: Int) async throws -> State.Proposal {
        let found = try await state().proposals.first { $0.targetId == "order-\(order)" }
        return try XCTUnwrap(found, "the server has no proposal on order \(order)")
    }

    /// An order is `paid` with no parcel, or `processing` with a parcel once confirmed.
    private func expectOrders(_ expected: [Int: String], _ message: String) async throws {
        let orders = try await state().orders
        for (number, status) in expected {
            let order = try XCTUnwrap(orders.first { $0.number == number })
            XCTAssertEqual(order.status, status, "order \(number): \(message)")
            XCTAssertEqual(order.shipment == nil, status == "paid", "order \(number)'s parcel does not match: \(message)")
        }
    }

    @MainActor
    private func confirmOrders(_ numbers: [Int], in app: XCUIApplication) {
        for number in numbers {
            ask("\(number) 주문 확인했어", in: app)
            XCTAssertTrue(step(saying: "#\(number)", in: app).waitForExistence(timeout: 30), "no step on order \(number)")
            waitForAnswerToSettle(in: app)
        }
    }

    @MainActor
    private func askForBothOrders(in app: XCUIApplication) async throws -> (first: State.Proposal, second: State.Proposal) {
        for number in [1042, 1043] {
            ask("\(number) 주문 확인했어", in: app)
            XCTAssertTrue(button("agent.proposal.approve.", in: app).waitForExistence(timeout: 30), "no card for \(number)")
            waitForAnswerToSettle(in: app)
            let raised = try await proposal(on: number)
            XCTAssertTrue(scrollTo(app.buttons["agent.proposal.approve.\(raised.id)"], in: app))
        }
        try await expectOrders([1042: "paid", 1043: "paid"], "a proposal changed a row before any yes")
        return (try await proposal(on: 1042), try await proposal(on: 1043))
    }

    @MainActor
    func testUndoOfAnAutoStepChangesOnlyTheOrderOnItsCard() async throws {
        let app = try open()
        openAssistant(in: app)
        confirmOrders([1042, 1043], in: app)
        try await expectOrders([1042: "processing", 1043: "processing", 1044: "paid"], "after two auto steps")
        try capture(app, "real-auto-two-orders")

        let older = try await step(on: 1042)
        let undo = app.buttons["agent.step.undo.\(older.id)"]
        XCTAssertTrue(scrollBack(to: undo, in: app), "the older step offers no undo")
        undo.tap()
        XCTAssertTrue(undo.waitForNonExistence(timeout: 20), "an undone step still offers its undo")
        try await expectOrders([1042: "paid", 1043: "processing"], "undo of 1042")
        let after = try await state().steps.filter(\.undone).map(\.id)
        XCTAssertEqual(after, [older.id])
        XCTAssertTrue(named("agent.step.\(older.id)", in: app).label.contains("되돌림"))
        try capture(app, "real-auto-undone-one")
    }

    @MainActor
    func testClarifyAsksAndTheOwnersAnswerIsThenDone() async throws {
        let app = try open()
        openAssistant(in: app)
        ask("주문 확인했어", in: app)
        XCTAssertTrue(step(saying: "확인 필요", in: app).waitForExistence(timeout: 30))
        XCTAssertFalse(button("agent.step.undo.", in: app).exists, "a question offers an undo")
        try await expectOrders([1042: "paid", 1043: "paid", 1044: "paid"], "a question changed a row")
        waitForAnswerToSettle(in: app)
        try capture(app, "real-clarify")
        confirmOrders([1042], in: app)
        try await expectOrders([1042: "processing", 1043: "paid"], "the clarified request")
        try capture(app, "real-clarify-answered")
    }

    @MainActor
    func testStepQuotesTheOwnerOnce() async throws {
        let app = try open()
        openAssistant(in: app)
        confirmOrders([1042], in: app)
        let label = step(saying: "#1042", in: app).label
        XCTAssertEqual(label.components(separatedBy: "사장님 말씀").count - 1, 1, "the same words are quoted twice: \(label)")
    }

    @MainActor
    func testUndoAfterApprovalChangesOnlyTheOrderOnItsCard() async throws {
        try await post("__flows/reset", ["mode": "ask"])
        let app = try open()
        openAssistant(in: app)
        let (first, second) = try await askForBothOrders(in: app)
        app.buttons["agent.proposal.approve.\(second.id)"].tap()
        let newerUndo = app.buttons["agent.step.undo.\(second.stepId)"]
        XCTAssertTrue(app.buttons["agent.proposal.approve.\(second.id)"].waitForNonExistence(timeout: 30))
        try await expectOrders([1042: "paid", 1043: "processing"], "approval of 1043")
        try capture(app, "real-approved-newer")
        XCTAssertTrue(newerUndo.waitForExistence(timeout: 10), "the approved card offers no undo of its own step")

        let approve = app.buttons["agent.proposal.approve.\(first.id)"]
        XCTAssertTrue(scrollBack(to: approve, in: app))
        approve.tap()
        let undo = app.buttons["agent.step.undo.\(first.stepId)"]
        XCTAssertTrue(undo.waitForExistence(timeout: 30), "the approved card offers no undo of its own step")
        try await expectOrders([1042: "processing", 1043: "processing"], "both approvals")
        XCTAssertTrue(scrollBack(to: undo, in: app))
        undo.tap()
        XCTAssertTrue(undo.waitForNonExistence(timeout: 20))
        try await expectOrders([1042: "paid", 1043: "processing"], "undo of 1042")
        let undone = try await state().steps.filter(\.undone).map(\.id)
        XCTAssertEqual(undone, [first.stepId])
        try capture(app, "real-approved-undone-one")
    }

    @MainActor
    func testDismissChangesNothingAndLeavesTheOtherProposalOpen() async throws {
        try await post("__flows/reset", ["mode": "ask"])
        let app = try open()
        openAssistant(in: app)
        let (first, second) = try await askForBothOrders(in: app)
        let dismiss = app.buttons["agent.proposal.dismiss.\(second.id)"]
        XCTAssertTrue(scrollTo(dismiss, in: app))
        dismiss.tap()
        XCTAssertTrue(dismiss.waitForNonExistence(timeout: 20))
        XCTAssertTrue(element(labelled: "거절하신 요청이에요. 바꾼 건 없어요.", in: app).waitForExistence(timeout: 10))
        try await expectOrders([1042: "paid", 1043: "paid"], "a dismissal")
        let states = try await state().proposals.reduce(into: [String: String]()) { $0[$1.id] = $1.state }
        XCTAssertEqual(states, [first.id: "open", second.id: "dismissed"])
        try capture(app, "real-dismissed")
        XCTAssertTrue(scrollBack(to: app.buttons["agent.proposal.approve.\(first.id)"], in: app), "the other card closed too")
    }

    @MainActor
    func testHistoryShowsEachStepAndUndoesOnlyTheOneTapped() async throws {
        let app = try open()
        openAssistant(in: app)
        confirmOrders([1042, 1043], in: app)
        try openHistory(in: app)
        let older = try await step(on: 1042)
        let newer = try await step(on: 1043)
        let undo = app.buttons["agent.step.undo.\(older.id)"]
        XCTAssertTrue(scrollTo(undo, in: app), "the history shows no undo for the older step")
        XCTAssertTrue(named("agent.step.\(newer.id)", in: app).exists, "the history does not show the newer step")
        try capture(app, "real-history")
        undo.tap()
        XCTAssertTrue(undo.waitForNonExistence(timeout: 20))
        try await expectOrders([1042: "paid", 1043: "processing"], "undo in the history")
        XCTAssertTrue(app.buttons["agent.step.undo.\(newer.id)"].waitForExistence(timeout: 10), "the other step lost its undo")
        try capture(app, "real-history-undone-one")
    }

    @MainActor
    func testHistoryShowsAnApprovedStepWithItsUndo() async throws {
        try await post("__flows/reset", ["mode": "ask"])
        let app = try open()
        openAssistant(in: app)
        let (_, second) = try await askForBothOrders(in: app)
        let approve = app.buttons["agent.proposal.approve.\(second.id)"]
        approve.tap()
        XCTAssertTrue(approve.waitForNonExistence(timeout: 30))
        try openHistory(in: app)
        let row = named("agent.step.\(second.stepId)", in: app)
        XCTAssertTrue(scrollTo(row, in: app), "the history does not show the approved step")
        try capture(app, "real-history-approved")
        XCTAssertTrue(row.label.contains("수락했어요") || row.label.contains("완료"), "the step does not say it ran: \(row.label)")
        let undo = app.buttons["agent.step.undo.\(second.stepId)"]
        XCTAssertTrue(undo.waitForExistence(timeout: 10), "the approved step has no undo in the history")
        undo.tap()
        XCTAssertTrue(undo.waitForNonExistence(timeout: 20))
        try await expectOrders([1042: "paid", 1043: "paid"], "undo of the approved step")
    }

    @MainActor
    private func openHistory(in app: XCUIApplication) throws {
        app.navigationBars["비서"].buttons["닫기"].tap()
        XCTAssertTrue(app.navigationBars["비서"].waitForNonExistence(timeout: 20))
        let history = app.buttons["today.activities"]
        XCTAssertTrue(history.waitForExistence(timeout: 20))
        history.tap()
        XCTAssertTrue(app.navigationBars["비서가 한 일"].waitForExistence(timeout: 20))
    }

    @MainActor
    func testLightAppearance() async throws { try await walk("light") }

    @MainActor
    func testDarkAppearance() async throws { try await walk("dark", dark: true) }

    @MainActor
    func testLargestText() async throws { try await walk("largest", arguments: Self.largestText) }

    @MainActor
    private func walk(_ prefix: String, dark: Bool = false, arguments: [String] = []) async throws {
        try await post("__flows/reset", ["perTool": ["confirm_order": "ask"]])
        let app = try open(arguments: arguments, dark: dark)
        if arguments.isEmpty { try checkAppearance(of: app, dark: dark) }
        openAssistant(in: app)
        ask("1040 포장 끝났어", in: app)
        let undo = button("agent.step.undo.", in: app)
        XCTAssertTrue(undo.waitForExistence(timeout: 30))
        waitForAnswerToSettle(in: app)
        XCTAssertTrue(scrollTo(undo, in: app), "the undo is out of reach")
        checkFits(undo, in: app, "undo")
        try capture(app, "real-\(prefix)-auto-step")

        ask("주문 확인했어", in: app)
        let question = step(saying: "확인 필요", in: app)
        XCTAssertTrue(question.waitForExistence(timeout: 30))
        waitForAnswerToSettle(in: app)
        XCTAssertTrue(scrollTo(question, in: app), "the question is out of reach")
        try capture(app, "real-\(prefix)-clarify")

        ask("1042 주문 확인했어", in: app)
        waitForAnswerToSettle(in: app)
        for answer in ["approve", "dismiss"] {
            let control = button("agent.proposal.\(answer).", in: app)
            XCTAssertTrue(scrollTo(control, in: app), "\(answer) is out of reach")
            checkFits(control, in: app, answer)
        }
        try capture(app, "real-\(prefix)-proposal")

        app.navigationBars["비서"].buttons["닫기"].tap()
        XCTAssertTrue(scrollTo(button("agent.proposal.row.", in: app), in: app), "Today does not list the proposal")
        try capture(app, "real-\(prefix)-today")
    }
}

/// States the real server cannot be put into on demand: no connection, a lost answer, a passed deadline, and the
/// wording of a refusal. Against `agent-stub-flows.py`; skipped unless ROUNDUP_UITEST_AGENT_FLOWS is 1.
final class AgentFlowsUITests: AgentFlowCase {
    private struct State: Decodable {
        struct Proposal: Decodable {
            let id: String
            let title: String
            let state: String
        }

        let orders: [String: String]
        let proposals: [Proposal]
    }

    private struct Log: Decodable {
        struct Request: Decodable {
            let method: String
            let path: String
        }

        let requests: [Request]
    }

    private struct Raised: Decodable { let id: String }

    override func setUp() async throws {
        try connect(gate: "ROUNDUP_UITEST_AGENT_FLOWS", address: "ROUNDUP_UITEST_API_URL", key: "ROUNDUP_UITEST_API_KEY")
        try await post("__stub/reset")
    }

    private func state() async throws -> State { try await read("__stub/state", as: State.self) }

    private func writes() async throws -> [String] {
        try await read("__stub/log", as: Log.self).requests.filter { $0.method != "GET" }.map(\.path)
    }

    private func proposal(titled title: String) async throws -> State.Proposal {
        let raised = try await state().proposals.first { $0.title == title }
        return try XCTUnwrap(raised, "the stub raised no ‘\(title)’")
    }

    /// Raises one more proposal at the server, unknown to the app until it reads the list.
    private func raise(lasting seconds: Int) async throws -> String {
        try JSONDecoder().decode(Raised.self, from: try await post("__stub/raise", ["seconds": seconds])).id
    }

    private func drop(_ isDropped: Bool) async throws { try await post("__stub/drop", ["drop": isDropped]) }

    @MainActor
    private func openProposal(_ id: String, in app: XCUIApplication) {
        let row = app.buttons["agent.proposal.row.\(id)"]
        XCTAssertTrue(scrollTo(row, in: app), "Today does not list the proposal")
        row.tap()
        XCTAssertTrue(named("agent.proposal.\(id)", in: app).waitForExistence(timeout: 20))
    }

    @MainActor
    private func dismissFailure(in app: XCUIApplication) -> String {
        let alert = app.alerts["이번엔 마무리하지 못했어요"]
        XCTAssertTrue(alert.waitForExistence(timeout: 30), "a failed write said nothing")
        let said = alert.staticTexts.allElementsBoundByIndex.map(\.label).joined(separator: " ")
        alert.buttons["확인"].tap()
        XCTAssertTrue(alert.waitForNonExistence(timeout: 10))
        return said
    }

    // MARK: Refused and expired

    @MainActor
    func testRefusedRequestChangesNothingAndOffersNothing() async throws {
        let app = try open()
        openAssistant(in: app)
        ask("김지은 님 예약 취소 처리해 줘", in: app)
        XCTAssertTrue(step(saying: "건너뜀", in: app).waitForExistence(timeout: 30))
        for prefix in ["agent.step.undo.", "agent.proposal.approve.", "agent.proposal.dismiss."] {
            XCTAssertFalse(button(prefix, in: app).exists, "a refusal offers \(prefix)")
        }
        let sent = try await writes()
        XCTAssertEqual(sent, ["/agent/run"])
        waitForAnswerToSettle(in: app)
        try capture(app, "refused")
    }

    /// The deadline itself is under test: the card is open on screen while its time passes.
    @MainActor
    func testProposalExpiresOnScreen() async throws {
        let id = try await raise(lasting: 45)
        let app = try open()
        openProposal(id, in: app)
        let approve = app.buttons["agent.proposal.approve.\(id)"]
        XCTAssertTrue(approve.waitForExistence(timeout: 10), "the proposal was not open to begin with")
        XCTAssertTrue(approve.waitForNonExistence(timeout: 110), "an expired proposal can still be approved")
        XCTAssertFalse(app.buttons["agent.proposal.dismiss.\(id)"].exists)
        XCTAssertTrue(element(labelled: "기간이 지난 확인 요청이에요", in: app).exists)
        let after = try await state()
        XCTAssertEqual(after.orders["1042"], "packing")
        try capture(app, "proposal-expired-on-screen")
    }

    @MainActor
    func testApprovingAfterTheServersDeadlineSaysSoAndChangesNothing() async throws {
        let app = try open()
        let confirm = try await proposal(titled: "주문 1041을 확인할까요?")
        openProposal(confirm.id, in: app)
        try await post("__stub/expire", ["id": confirm.id])
        let approve = app.buttons["agent.proposal.approve.\(confirm.id)"]
        XCTAssertTrue(approve.waitForExistence(timeout: 10))
        approve.tap()

        let said = dismissFailure(in: app)
        XCTAssertTrue(said.contains("수락 기간이 끝난 요청이에요"), said)
        XCTAssertTrue(approve.waitForNonExistence(timeout: 20), "an expired proposal can still be approved")
        let after = try await state()
        XCTAssertEqual(after.orders["1041"], "paid")
        XCTAssertEqual(after.proposals.first { $0.id == confirm.id }?.state, "expired")
        try capture(app, "proposal-expired-at-approval")
    }

    // MARK: Offline, and back without a tap

    @MainActor
    func testTodayReconnectsWithoutATapAndShowsANewProposal() async throws {
        let app = try open()
        let header = named("agent.proposals.header", in: app)
        XCTAssertTrue(header.waitForExistence(timeout: 60))
        XCTAssertEqual(header.label, "비서의 확인 요청 2건")

        try await drop(true)
        pullDown(app)
        let notice = named("connection.notice", in: app)
        XCTAssertTrue(notice.waitForExistence(timeout: 30), "a refresh that failed says nothing")
        XCTAssertTrue(header.exists, "the last proposals were thrown away")
        try capture(app, "offline-today")
        let id = try await raise(lasting: 3600)

        try await drop(false)
        XCTAssertTrue(notice.waitForNonExistence(timeout: 60), "Today did not reconnect by itself")
        XCTAssertTrue(app.buttons["agent.proposal.row.\(id)"].waitForExistence(timeout: 20), "the proposal raised meanwhile is missing")
        XCTAssertEqual(header.label, "비서의 확인 요청 3건")
        try capture(app, "reconnected-today")
    }

    @MainActor
    func testProposalListReconnectsWithoutATap() async throws {
        let app = try open()
        let confirm = try await proposal(titled: "주문 1041을 확인할까요?")
        openProposal(confirm.id, in: app)
        let approve = app.buttons["agent.proposal.approve.\(confirm.id)"]
        XCTAssertTrue(approve.waitForExistence(timeout: 10))

        try await drop(true)
        approve.tap()
        let said = dismissFailure(in: app)
        XCTAssertTrue(said.contains("지금 연결이 안 돼요"), said)
        XCTAssertTrue(approve.exists, "a proposal that was not approved lost its approval")
        let untouched = try await state()
        XCTAssertEqual(untouched.orders["1041"], "paid")
        try capture(app, "offline-proposal-list")
        let id = try await raise(lasting: 3600)

        let notice = named("connection.notice", in: app)
        XCTAssertTrue(notice.waitForExistence(timeout: 20), "the list does not say the server is out of reach")
        try await drop(false)
        XCTAssertTrue(notice.waitForNonExistence(timeout: 60), "the proposal list did not reconnect by itself")
        XCTAssertTrue(scrollTo(named("agent.proposal.\(id)", in: app), in: app), "the reconnected list misses what came meanwhile")
        try capture(app, "reconnected-proposal-list")
    }

    @MainActor
    func testRunLeftToTheServerFinishesAfterAnOutageWithoutATap() async throws {
        let app = try open()
        openAssistant(in: app)
        ask("1040 1042 포장 끝났어", in: app)
        XCTAssertTrue(named("assistant.generating", in: app).waitForExistence(timeout: 30))
        try await post("__stub/advance")
        XCTAssertTrue(step(saying: "주문 1040", in: app).waitForExistence(timeout: 30))

        try await drop(true)
        try await post("__stub/advance")
        try await post("__stub/advance")
        try capture(app, "offline-run")
        try await drop(false)
        XCTAssertTrue(element(labelled: "주문 2건을 포장 완료로 바꿨어요", in: app).waitForExistence(timeout: 60),
                      "the run's end never reached the chat")
        XCTAssertTrue(step(saying: "주문 1042", in: app).waitForExistence(timeout: 10))
        XCTAssertFalse(app.buttons["assistant.retry"].exists, "the owner is asked to send a finished job again")
        let sent = try await writes()
        XCTAssertEqual(sent, ["/agent/run"], "the job was sent again")
        waitForAnswerToSettle(in: app)
        try capture(app, "reconnected-run")
    }

    @MainActor
    func testAnswerLostOnTheWayIsFoundWithoutATapOrASecondRun() async throws {
        let app = try open()
        openAssistant(in: app)
        try await post("__stub/lose")
        ask("1040 포장 끝났어", in: app)
        XCTAssertTrue(step(saying: "주문 1040", in: app).waitForExistence(timeout: 60), "the lost answer was not found")
        let sent = try await writes()
        // The send whose answer was lost is repeated once under the same request id; the server runs it once.
        XCTAssertEqual(Set(sent), ["/agent/run"], "a job that was done was asked elsewhere")
        XCTAssertLessThanOrEqual(sent.count, 2, "a job that was done was sent again and again")
        let after = try await state()
        XCTAssertEqual(after.orders["1040"], "invoice_pending")
        waitForAnswerToSettle(in: app)
        try capture(app, "lost-answer-found")
    }

    /// A question that never reached the server is not sent again by itself; the owner keeps it and a way to send it.
    @MainActor
    func testQuestionAskedOfflineKeepsItsWayOn() async throws {
        let app = try open()
        openAssistant(in: app)
        try await drop(true)
        ask("1040 포장 끝났어", in: app)
        let retry = app.buttons["assistant.retry"]
        XCTAssertTrue(retry.waitForExistence(timeout: 60), "an unreachable server left the question without a way on")
        try capture(app, "offline-chat")
        let untouched = try await state()
        XCTAssertEqual(untouched.orders["1040"], "packing")

        try await drop(false)
        retry.tap()
        XCTAssertTrue(step(saying: "주문 1040", in: app).waitForExistence(timeout: 30))
        waitForAnswerToSettle(in: app)
        try capture(app, "reconnected-chat")
    }

    // MARK: Appearance and text size

    @MainActor
    func testLightAppearance() async throws { try await walk("light") }

    @MainActor
    func testDarkAppearance() async throws { try await walk("dark", dark: true) }

    @MainActor
    func testLargestText() async throws { try await walk("largest", arguments: Self.largestText) }

    /// An expired proposal, a refusal, and a lost connection.
    @MainActor
    private func walk(_ prefix: String, dark: Bool = false, arguments: [String] = []) async throws {
        try await post("__stub/reset", ["expired": true])
        let app = try open(arguments: arguments, dark: dark)
        if arguments.isEmpty { try checkAppearance(of: app, dark: dark) }
        let expired = try await proposal(titled: "주문 1038을 배송 완료로 바꿀까요?")
        openProposal(expired.id, in: app)
        XCTAssertTrue(scrollTo(element(labelled: "기간이 지난 확인 요청이에요", in: app), in: app))
        XCTAssertFalse(app.buttons["agent.proposal.approve.\(expired.id)"].exists)
        try capture(app, "\(prefix)-expired")
        app.navigationBars.buttons.element(boundBy: 0).tap()

        openAssistant(in: app)
        ask("김지은 님 예약 취소 처리해 줘", in: app)
        let row = step(saying: "건너뜀", in: app)
        XCTAssertTrue(row.waitForExistence(timeout: 30))
        waitForAnswerToSettle(in: app)
        XCTAssertTrue(scrollTo(row, in: app), "the refusal is out of reach")
        XCTAssertLessThanOrEqual(row.frame.maxX, app.frame.maxX, "the refusal is cut off")
        try capture(app, "\(prefix)-refused")

        try await drop(true)
        ask("1040 포장 끝났어", in: app)
        let retry = app.buttons["assistant.retry"]
        XCTAssertTrue(retry.waitForExistence(timeout: 60))
        XCTAssertTrue(scrollTo(retry, in: app), "the way on is out of reach")
        checkFits(retry, in: app, "retry")
        try capture(app, "\(prefix)-offline")
    }
}
