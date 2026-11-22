import Foundation

public enum TodayGreeting {
    private static let seoul: Calendar = {
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = TimeZone(identifier: "Asia/Seoul") ?? .gmt
        return calendar
    }()

    private static let genericOwnerTitles: Set<String> = ["사장", "사장님"]

    public static func title(ownerName: String?, workshopName: String?) -> String {
        let owner = clean(ownerName)
        let usableOwner = genericOwnerTitles.contains(owner) ? "" : owner
        guard let name = [usableOwner, clean(workshopName)].first(where: { !$0.isEmpty }) else { return "반갑습니다." }
        return name.hasSuffix("님") ? "\(name) 반갑습니다." : "\(name)님 반갑습니다."
    }

    private static func clean(_ value: String?) -> String {
        value?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
    }

    public static func line(pendingCount: Int, now: Date) -> String {
        let hour = seoul.component(.hour, from: now)
        let greeting: String
        switch hour {
        case 5..<12: greeting = "좋은 아침입니다."
        case 12..<18: greeting = "좋은 오후입니다."
        default: greeting = "좋은 저녁입니다."
        }
        let pending = pendingCount > 0 ? " 확인할 요청이 \(pendingCount)건 있어요!" : " 확인할 요청이 없어요."
        return greeting + pending
    }
}
