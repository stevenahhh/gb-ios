import XCTest
@testable import RoundupCore

final class SpokenTurnTests: XCTestCase {
    func testNumbersDisagreeOnlyWhenEachSideHasOneTheOtherLacks() {
        XCTAssertFalse(SpokenTurn.numbersAgree("1040 포장 끝났어", "1041 포장 끝났어"))
        XCTAssertFalse(SpokenTurn.numbersAgree("송장 689012345678", "송장 689012345679"))
        XCTAssertTrue(SpokenTurn.numbersAgree("1040 포장 끝났어", "1040 포장 끝났어요"))
        XCTAssertTrue(SpokenTurn.numbersAgree("천사십 포장 끝났어", "1040 포장 끝났어"))
        XCTAssertTrue(SpokenTurn.numbersAgree("세 명 예약", "3명 예약"))
        XCTAssertTrue(SpokenTurn.numbersAgree("1040번 3만 원", "1040번 30,000원"))
        XCTAssertTrue(SpokenTurn.numbersAgree("6890-1234-5678", "6890 1234 5678"))
    }

    func testOnlyABareRequestUndoes() {
        for text in ["되돌려 줘", "되돌려.", "방금 거 되돌려 줘", "방금 한 일을 되돌려 주세요", "그거 되돌려줘요"] {
            XCTAssertTrue(SpokenTurn.isUndoRequest(text), text)
        }
        for text in ["취소해 줘", "1040 되돌려 줘", "되돌려 놓지 마", "되돌릴 수 있어?", "되돌려 줬어", ""] {
            XCTAssertFalse(SpokenTurn.isUndoRequest(text), text)
        }
    }

    func testALongAnswerIsShortenedAndAReportIsNot() {
        let long = (1...8).map { "\($0)번째 주문을 확인했어요." }.joined(separator: " ")
        let spoken = SpokenTurn.spoken(long, reportsWork: false, waiting: 0)
        XCTAssertTrue(spoken.contains("5번째"))
        XCTAssertFalse(spoken.contains("6번째"))
        XCTAssertEqual(SpokenTurn.spoken(long, reportsWork: true, waiting: 0), long)
        XCTAssertEqual(SpokenTurn.spoken("짧아요.", reportsWork: false, waiting: 0), "짧아요.")
        let one = String(repeating: "가", count: 400)
        XCTAssertEqual(SpokenTurn.spoken(one, reportsWork: false, waiting: 0), one)
    }

    func testAWaitingProposalIsAnnouncedEvenWithoutAnAnswer() {
        for waiting in [1, 2] {
            let spoken = SpokenTurn.spoken("올렸어요.", reportsWork: true, waiting: waiting)
            XCTAssertTrue(spoken.hasPrefix("올렸어요.\n"))
            XCTAssertGreaterThan(spoken.count, "올렸어요.\n".count)
        }
        XCTAssertFalse(SpokenTurn.spoken("", reportsWork: true, waiting: 1).isEmpty)
    }

    func testMaskedNamesSurviveInlineMarkdown() throws {
        let options = AttributedString.MarkdownParsingOptions(interpretedSyntax: .inlineOnlyPreservingWhitespace)
        func rendered(_ text: String) throws -> String {
            String(try AttributedString(markdown: SpokenTurn.escapingMaskedNames(text), options: options).characters)
        }
        XCTAssertEqual(try rendered("박*은 님과 최*우 님"), "박*은 님과 최*우 님")
        XCTAssertEqual(try rendered("남**수, 김* 님"), "남**수, 김* 님")
        XCTAssertEqual(try rendered("#1040 머그컵 · 박*은, 이*"), "#1040 머그컵 · 박*은, 이*")
        XCTAssertEqual(try rendered("**중요** 안내"), "중요 안내")
    }

    func testATurnOverTheServersLimitIsTooLong() {
        XCTAssertFalse(SpokenTurn.isTooLong(String(repeating: "가", count: 1000)))
        XCTAssertTrue(SpokenTurn.isTooLong(String(repeating: "가", count: 1001)))
    }

    func testRecentWindowKeepsJustEnoughToCoverItsSeconds() {
        var window = RecentWindow<Int>(seconds: 1)
        for element in 1...20 { window.append(element, duration: 0.25) }
        XCTAssertEqual(window.elements, [17, 18, 19, 20])
        window.removeAll()
        XCTAssertTrue(window.elements.isEmpty)
    }
}
