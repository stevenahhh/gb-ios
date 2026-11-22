import Foundation
import Observation

/// The plan the owner picked, kept on this device only. The app has no App Store product, so a pick is a
/// stored preference: it charges nothing and unlocks nothing.
@MainActor
@Observable
final class PlanSelection {
    static let shared = PlanSelection()
    private static let storageKey = "plan.chosenID"

    private(set) var chosenID: String?

    private init() {
        chosenID = UserDefaults.standard.string(forKey: Self.storageKey)
    }

    /// Nil until the owner picks, and again if the picked plan has left the catalogue.
    var chosen: Plan? {
        PlanCatalog.options.first { $0.id == chosenID }
    }

    func choose(_ plan: Plan) {
        chosenID = plan.id
        UserDefaults.standard.set(plan.id, forKey: Self.storageKey)
    }
}
