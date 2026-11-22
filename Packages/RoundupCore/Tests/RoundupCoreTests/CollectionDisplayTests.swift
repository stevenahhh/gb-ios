import XCTest
@testable import RoundupCore

final class CollectionDisplayTests: XCTestCase {
    func testNoUsableAnswerShowsTheSample() {
        XCTAssertEqual(CollectionDisplay.choose(states: nil), .sampleWithoutStatus)
        XCTAssertEqual(CollectionDisplay.choose(states: []), .sampleWithoutStatus)
    }

    func testNothingConnectedShowsTheSampleAndSaysWhy() {
        XCTAssertEqual(CollectionDisplay.choose(states: [.needsConnection]), .sampleBeforeConnection)
        XCTAssertEqual(
            CollectionDisplay.choose(states: Array(repeating: .needsConnection, count: 5)), .sampleBeforeConnection)
    }

    func testOneConnectedSourceShowsTheRealRows() {
        for state in [CollectorState.collecting, .idle, .error] {
            XCTAssertEqual(
                CollectionDisplay.choose(states: [.needsConnection, state, .needsConnection]), .live, "\(state)")
            XCTAssertEqual(CollectionDisplay.choose(states: [state]), .live, "\(state)")
        }
    }

    func testStatesDecodeFromTheServerCodes() throws {
        let codes = Data(#"["collecting", "idle", "needs_connection", "error"]"#.utf8)
        XCTAssertEqual(
            try JSONDecoder().decode([CollectorState].self, from: codes), [.collecting, .idle, .needsConnection, .error])
        XCTAssertThrowsError(try JSONDecoder().decode([CollectorState].self, from: Data(#"["paused"]"#.utf8)))
    }
}
