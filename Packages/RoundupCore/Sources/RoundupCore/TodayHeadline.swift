import Foundation

/// What the today headline needs; the server counts rows, the device picks the words.
public struct TodayHeadlineFacts: Sendable, Equatable {
    public struct Session: Sendable, Equatable {
        public let title: String
        public let start: Date
        public let minutes: Int
        public let isDone: Bool

        public init(title: String, start: Date, minutes: Int, isDone: Bool) {
            self.title = title
            self.start = start
            self.minutes = minutes
            self.isDone = isDone
        }

        var end: Date { start.addingTimeInterval(TimeInterval(minutes * 60)) }
    }

    public var overdueShipments = 0
    public var overdueTasks = 0
    public var sessions: [Session] = []
    public var pendingInquiries = 0
    public var depositPending = 0
    public var pendingDrafts = 0
    public var openTasksToday = 0
    public var tasksToday = 0
    public var openShipmentsToday = 0
    public var shipmentsToday = 0
    public var tomorrowClasses = 0
    public var weekClassesLeft = 0

    public init() {}
}

/// The today tab's one-line headline: the first matching rule wins, and it stays within
/// 10 Hangul syllables and 14 characters.
public enum TodayHeadline {
    public static let maxSyllables = 10
    public static let maxLength = 14

    public static func make(_ facts: TodayHeadlineFacts, now: Date) -> String {
        // 1. Overdue work: parcels, then tasks. Inquiries carry no deadline.
        if facts.overdueShipments > 0 { return "못 보낸 택배 \(facts.overdueShipments)건" }
        if facts.overdueTasks > 0 { return "놓친 할 일 \(facts.overdueTasks)개" }

        // 2. A class running now or starting within two hours.
        let open = facts.sessions.filter { !$0.isDone }
        if let running = open.first(where: { $0.start <= now && now < $0.end }) {
            return fitted(running.title) { "\($0) 진행 중" }
        }
        if let soon = open.filter({ $0.start > now }).min(by: { $0.start < $1.start }) {
            let minutes = Int((soon.start.timeIntervalSince(now) / 60).rounded(.up))
            if minutes <= 120 {
                return fitted(soon.title) { "\(wait(minutes)) \($0)" }
            }
        }

        // 3. Work waiting on the owner.
        if facts.pendingInquiries > 0 { return "답변 기다리는 문의 \(facts.pendingInquiries)건" }
        if facts.depositPending > 0 { return "입금 확인할 예약 \(facts.depositPending)건" }
        if facts.pendingDrafts > 0 { return "검토할 초안 \(facts.pendingDrafts)건" }

        // 4. Anything left today.
        let remaining = open.filter { $0.end > now }.count + facts.openTasksToday + facts.openShipmentsToday
        if remaining > 0 { return "오늘 남은 일정 \(remaining)개" }

        // 5. Everything today is done.
        if facts.sessions.count + facts.tasksToday + facts.shipmentsToday > 0 { return "오늘 일 다 끝났어요" }

        // 6. Nothing today: look ahead.
        if facts.tomorrowClasses > 0 { return "내일은 수업 \(facts.tomorrowClasses)개" }
        if facts.weekClassesLeft > 0 { return "이번 주 남은 수업 \(facts.weekClassesLeft)개" }
        return "오늘은 여유로운 날"
    }

    static func wait(_ minutes: Int) -> String {
        guard minutes >= 60 else { return "\(minutes)분 뒤" }
        let rest = minutes % 60
        return rest == 0 ? "\(minutes / 60)시간 뒤" : "\(minutes / 60)시간 \(rest)분 뒤"
    }

    /// Shortens a class name until the headline fits: "나만의 머그컵 만들기" → "머그컵 수업".
    static func fitted(_ title: String, _ headline: (String) -> String) -> String {
        let words = title.split(separator: " ").map(String.init)
        var names: [String] = []
        if words.count >= 2 {
            names.append("\(words[0]) \(words[1]) 수업")
            names.append("\(words[1]) 수업")
        }
        if let first = words.first { names.append("\(first) 수업") }
        names.append("수업")
        return names.lazy.map(headline).first(where: fits) ?? headline("수업")
    }

    static func fits(_ text: String) -> Bool {
        let syllables = text.unicodeScalars.filter { (0xAC00...0xD7A3).contains($0.value) }.count
        return syllables <= maxSyllables && text.count <= maxLength
    }
}
