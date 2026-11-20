import XCTest
@testable import RoundupCore

final class TodayHeadlineTests: XCTestCase {
    private let now = Date(timeIntervalSince1970: 1_800_000_000)

    private func session(_ title: String, inMinutes offset: Int, minutes: Int = 120, done: Bool = false)
        -> TodayHeadlineFacts.Session {
        .init(title: title, start: now.addingTimeInterval(TimeInterval(offset * 60)), minutes: minutes, isDone: done)
    }

    func testOverdueParcelsComeBeforeEverythingElse() {
        var facts = TodayHeadlineFacts()
        facts.overdueShipments = 2
        facts.overdueTasks = 1
        facts.sessions = [session("나만의 머그컵 만들기", inMinutes: 30)]
        facts.pendingInquiries = 3
        XCTAssertEqual(TodayHeadline.make(facts, now: now), "못 보낸 택배 2건")
        facts.overdueShipments = 0
        XCTAssertEqual(TodayHeadline.make(facts, now: now), "놓친 할 일 1개")
    }

    func testClassWithinTwoHoursOrRunningUsesAShortName() {
        var facts = TodayHeadlineFacts()
        facts.pendingInquiries = 3
        facts.sessions = [session("나만의 머그컵 만들기", inMinutes: 30)]
        XCTAssertEqual(TodayHeadline.make(facts, now: now), "30분 뒤 머그컵 수업")
        facts.sessions = [session("나만의 머그컵 만들기", inMinutes: -10)]
        XCTAssertEqual(TodayHeadline.make(facts, now: now), "머그컵 수업 진행 중")
        facts.sessions = [session("물레 체험", inMinutes: 80)]
        XCTAssertEqual(TodayHeadline.make(facts, now: now), "1시간 20분 뒤 수업")
    }

    func testClassBeyondTwoHoursFallsThroughToWaitingWork() {
        var facts = TodayHeadlineFacts()
        facts.sessions = [session("나만의 머그컵 만들기", inMinutes: 121)]
        facts.pendingInquiries = 3
        XCTAssertEqual(TodayHeadline.make(facts, now: now), "답변 기다리는 문의 3건")
        facts.pendingInquiries = 0
        facts.depositPending = 2
        XCTAssertEqual(TodayHeadline.make(facts, now: now), "입금 확인할 예약 2건")
        facts.depositPending = 0
        facts.pendingDrafts = 1
        XCTAssertEqual(TodayHeadline.make(facts, now: now), "검토할 초안 1건")
    }

    func testRemainingTodayCountsClassesTasksAndParcels() {
        var facts = TodayHeadlineFacts()
        facts.sessions = [session("나만의 머그컵 만들기", inMinutes: 300), session("오전 수업", inMinutes: -300, done: true)]
        facts.openTasksToday = 1
        facts.openShipmentsToday = 1
        XCTAssertEqual(TodayHeadline.make(facts, now: now), "오늘 남은 일정 3개")
    }

    func testFinishedDaySaysSo() {
        var facts = TodayHeadlineFacts()
        facts.sessions = [session("오전 수업", inMinutes: -300, done: true)]
        facts.tasksToday = 2
        XCTAssertEqual(TodayHeadline.make(facts, now: now), "오늘 일 다 끝났어요")
    }

    func testEmptyDayLooksAhead() {
        var facts = TodayHeadlineFacts()
        facts.tomorrowClasses = 2
        facts.weekClassesLeft = 4
        XCTAssertEqual(TodayHeadline.make(facts, now: now), "내일은 수업 2개")
        facts.tomorrowClasses = 0
        XCTAssertEqual(TodayHeadline.make(facts, now: now), "이번 주 남은 수업 4개")
        facts.weekClassesLeft = 0
        XCTAssertEqual(TodayHeadline.make(facts, now: now), "오늘은 여유로운 날")
    }

    func testEveryHeadlineFitsTheLengthLimit() {
        var facts = TodayHeadlineFacts()
        facts.sessions = [session("도자기 원데이 클래스 체험반", inMinutes: 95)]
        let headline = TodayHeadline.make(facts, now: now)
        XCTAssertTrue(TodayHeadline.fits(headline), headline)
        XCTAssertEqual(headline, "1시간 35분 뒤 수업")
    }
}
