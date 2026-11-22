import Foundation

/// What the workshop sells. A local choice kept on this device: the server has no field for it,
/// so nothing here is sent anywhere. Later onboarding steps read `BusinessType.saved`.
enum BusinessType: String, CaseIterable, Identifiable, Codable, Hashable, Sendable {
    case oneDayClass
    case customOrder
    case onlineSales
    case outreach

    var id: Self { self }

    var title: String {
        switch self {
        case .oneDayClass: "원데이 클래스"
        case .customOrder: "주문 제작"
        case .onlineSales: "온라인 판매"
        case .outreach: "출장 수업"
        }
    }
}

extension BusinessType {
    static let storageKey = "onboarding.businessTypes"

    /// The saved choice, empty until the owner picks something. A stored value this build does not know is ignored.
    static var saved: Set<BusinessType> {
        get {
            let stored = UserDefaults.standard.stringArray(forKey: storageKey) ?? []
            return Set(stored.compactMap { BusinessType(rawValue: $0) })
        }
        set {
            // Written in declaration order, so the stored list does not change with the set's hashing.
            let ordered = allCases.filter { newValue.contains($0) }.map(\.rawValue)
            UserDefaults.standard.set(ordered, forKey: storageKey)
        }
    }
}
