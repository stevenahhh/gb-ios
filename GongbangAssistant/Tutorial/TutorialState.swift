import SwiftUI

/// Runs the coach marks: the stop on screen, and the window frames the real elements report.
/// It only moves between stops. It never calls an element's action.
@MainActor @Observable
final class TutorialState {
    static let shared = TutorialState()
    /// Read as Bool, so the launch argument `-tutorial.done YES` counts as seen.
    static let doneKey = "tutorial.done"

    private(set) var stop: TutorialStop?
    /// Stops shown in this run, the current one included.
    private(set) var position = 0
    /// The stop already counted in `position`; also means its coach mark is on screen.
    private var counted: TutorialStop?
    /// Bumped when a frame changes during a run, so the overlay follows the element.
    private var frameVersion = 0
    @ObservationIgnored private var frames: [TutorialAnchorID: [UUID: CGRect]] = [:]

    var isRunning: Bool { stop != nil }

    /// Shown stops plus the ones still ahead. A later stop with no element drops out, so this can shrink.
    var total: Int {
        guard let stop else { return 0 }
        return position + TutorialStop.allCases.count - 1 - stop.rawValue
    }

    func start() {
        position = 0
        counted = nil
        stop = TutorialStop.allCases.first
    }

    /// 다음, or the owner using the element.
    func advance() {
        guard let stop else { return }
        guard let next = TutorialStop(rawValue: stop.rawValue + 1) else { return finish() }
        self.stop = next
    }

    /// 건너뛰기, Escape, or the end of the last stop.
    func finish() {
        stop = nil
        counted = nil
        UserDefaults.standard.set(true, forKey: Self.doneKey)
    }

    /// The stop's element never came on screen, so the run moves on without counting it.
    func skipMissing(_ missing: TutorialStop) {
        guard stop == missing else { return }
        advance()
    }

    /// The stop's coach mark is on screen.
    func confirmShown(_ shown: TutorialStop) {
        guard stop == shown, counted != shown else { return }
        counted = shown
        position += 1
    }

    /// The owner tapped the element itself while its coach mark was showing.
    func ownerUsed(_ id: TutorialAnchorID) {
        guard let stop, counted == stop, stop.anchors.contains(id) else { return }
        advance()
    }

    func report(_ frame: CGRect, for id: TutorialAnchorID, from token: UUID) {
        guard frames[id]?[token] != frame else { return }
        frames[id, default: [:]][token] = frame
        if isRunning { frameVersion += 1 }
    }

    func forget(_ id: TutorialAnchorID, from token: UUID) {
        guard frames[id]?.removeValue(forKey: token) != nil else { return }
        if isRunning { frameVersion += 1 }
    }

    /// The window frame around every piece of the element, or nil when none is on screen.
    func frame(for id: TutorialAnchorID) -> CGRect? {
        _ = frameVersion
        guard let pieces = frames[id]?.values, let first = pieces.first else { return nil }
        return pieces.dropFirst().reduce(first) { $0.union($1) }
    }
}
