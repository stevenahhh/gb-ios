import Foundation
import XCTest
@testable import RoundupCore

final class TodayGreetingTests: XCTestCase {
    func testTitleUsesOwnerNameFirst() {
        XCTAssertEqual(TodayGreeting.title(ownerName: "김사장", workshopName: "공방"), "김사장님 반갑습니다.")
    }

    func testTitleFallsBackToWorkshopName() {
        XCTAssertEqual(TodayGreeting.title(ownerName: nil, workshopName: "공방"), "공방님 반갑습니다.")
        XCTAssertEqual(TodayGreeting.title(ownerName: "  ", workshopName: " 공방 "), "공방님 반갑습니다.")
    }

    func testTitleDoesNotDoubleHonorific() {
        XCTAssertEqual(TodayGreeting.title(ownerName: "가연님", workshopName: nil), "가연님 반갑습니다.")
    }

    func testGenericOwnerTitleFallsBackToWorkshopName() {
        XCTAssertEqual(TodayGreeting.title(ownerName: "사장님", workshopName: "오롯 공방"), "오롯 공방님 반갑습니다.")
        XCTAssertEqual(TodayGreeting.title(ownerName: "사장", workshopName: nil), "반갑습니다.")
    }

    func testTitleWithoutNamesIsPlainGreeting() {
        XCTAssertEqual(TodayGreeting.title(ownerName: nil, workshopName: nil), "반갑습니다.")
        XCTAssertEqual(TodayGreeting.title(ownerName: "", workshopName: "\n"), "반갑습니다.")
    }

    func testLineGreetingFollowsSeoulHour() {
        XCTAssertEqual(TodayGreeting.line(pendingCount: 0, now: seoul(hour: 4, minute: 59)), "좋은 저녁입니다. 확인할 요청이 없어요.")
        XCTAssertEqual(TodayGreeting.line(pendingCount: 0, now: seoul(hour: 5, minute: 0)), "좋은 아침입니다. 확인할 요청이 없어요.")
        XCTAssertEqual(TodayGreeting.line(pendingCount: 0, now: seoul(hour: 11, minute: 59)), "좋은 아침입니다. 확인할 요청이 없어요.")
        XCTAssertEqual(TodayGreeting.line(pendingCount: 0, now: seoul(hour: 12, minute: 0)), "좋은 오후입니다. 확인할 요청이 없어요.")
        XCTAssertEqual(TodayGreeting.line(pendingCount: 0, now: seoul(hour: 17, minute: 59)), "좋은 오후입니다. 확인할 요청이 없어요.")
        XCTAssertEqual(TodayGreeting.line(pendingCount: 0, now: seoul(hour: 18, minute: 0)), "좋은 저녁입니다. 확인할 요청이 없어요.")
    }

    func testLineCountsPendingRequests() {
        XCTAssertEqual(TodayGreeting.line(pendingCount: 3, now: seoul(hour: 9, minute: 0)), "좋은 아침입니다. 확인할 요청이 3건 있어요!")
    }

    private func seoul(hour: Int, minute: Int) -> Date {
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = TimeZone(identifier: "Asia/Seoul")!
        return calendar.date(from: DateComponents(year: 2026, month: 11, day: 22, hour: hour, minute: minute))!
    }
}
