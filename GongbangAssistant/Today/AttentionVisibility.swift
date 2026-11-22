import Foundation
import Observation

/// What the owner cleared from the 오늘 tab. Rows come back with the next workshop day; the metric strip stays
/// cleared until it is restored. It only hides on screen and never reaches the server.
nonisolated struct AttentionHidden: Equatable {
    static let metricsID = "metrics"

    private(set) var day: String
    private(set) var rows: Set<String>
    private(set) var hidesMetrics: Bool

    init(day: String = "", rows: Set<String> = [], hidesMetrics: Bool = false) {
        self.day = day
        self.rows = rows
        self.hidesMetrics = hidesMetrics
    }

    func rows(on today: String) -> Set<String> { day == today ? rows : [] }

    func contains(_ id: String, on today: String) -> Bool {
        id == Self.metricsID ? hidesMetrics : rows(on: today).contains(id)
    }

    mutating func hide(_ id: String, on today: String) {
        guard id != Self.metricsID else { return hidesMetrics = true }
        rows = rows(on: today).union([id])
        day = today
    }

    mutating func restore(_ id: String, on today: String) {
        guard id != Self.metricsID else { return hidesMetrics = false }
        rows = rows(on: today).subtracting([id])
        day = today
    }

    /// Brings every row back. The metric strip has its own restore.
    mutating func restoreRows() { rows = [] }
}

@MainActor
@Observable
final class AttentionVisibility {
    static let shared = AttentionVisibility()

    private enum Key {
        static let day = "attention.hidden.day"
        static let rows = "attention.hidden.rows"
        static let metrics = "attention.hidden.metrics"
    }

    private var hidden: AttentionHidden
    @ObservationIgnored private let defaults: UserDefaults
    @ObservationIgnored private let now: () -> Date

    init(defaults: UserDefaults = .standard, now: @escaping () -> Date = { .now }) {
        self.defaults = defaults
        self.now = now
        hidden = AttentionHidden(day: defaults.string(forKey: Key.day) ?? "",
                                 rows: Set(defaults.stringArray(forKey: Key.rows) ?? []),
                                 hidesMetrics: defaults.bool(forKey: Key.metrics))
    }

    /// Cleared rows, without the metric strip.
    var hiddenCount: Int { hidden.rows(on: today).count }

    func isHidden(_ id: String) -> Bool { hidden.contains(id, on: today) }

    func hide(_ id: String) {
        hidden.hide(id, on: today)
        save()
    }

    func restore(_ id: String) {
        hidden.restore(id, on: today)
        save()
    }

    func restoreAll() {
        hidden.restoreRows()
        save()
    }

    private var today: String { now().dayKey }

    private func save() {
        defaults.set(hidden.day, forKey: Key.day)
        defaults.set(hidden.rows.sorted(), forKey: Key.rows)
        defaults.set(hidden.hidesMetrics, forKey: Key.metrics)
    }
}
