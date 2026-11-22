import SwiftUI

/// The real elements a coach mark can point at. One case per `.tutorialAnchor(_:)` in the screens.
nonisolated enum TutorialAnchorID: String, Hashable, Sendable, CaseIterable {
    case approvals
    case cancellations
    case remainingWork
    /// 일정 추가 pinned under a day that has a timeline.
    case calendarAdd
    /// The + in the calendar's toolbar, used on a day with no timeline.
    case calendarAddToolbar
    case assistantBar
    case settingsReplay
}

/// Bounds of the anchored elements that share a view tree with the overlay.
nonisolated struct TutorialAnchorKey: PreferenceKey {
    static var defaultValue: [TutorialAnchorID: Anchor<CGRect>] { [:] }

    static func reduce(value: inout [TutorialAnchorID: Anchor<CGRect>],
                       nextValue: () -> [TutorialAnchorID: Anchor<CGRect>]) {
        value.merge(nextValue()) { first, _ in first }
    }
}

extension View {
    /// Marks the element a tutorial stop points at. On a section it marks every row, and the cut-out covers them all.
    func tutorialAnchor(_ id: TutorialAnchorID) -> some View {
        modifier(TutorialAnchorModifier(id: id))
    }
}

private struct TutorialAnchorModifier: ViewModifier {
    let id: TutorialAnchorID
    @State private var piece = AnchorPiece()

    func body(content: Content) -> some View {
        let state = TutorialState.shared
        content
            .anchorPreference(key: TutorialAnchorKey.self, value: .bounds) { [id] anchor in [id: anchor] }
            // The assistant bar and toolbar buttons are hosted by the system outside the root's view tree, so a
            // preference never leaves them. Their window frame travels this way instead, as `accessorySlot` does.
            .onGeometryChange(for: CGRect.self) { $0.frame(in: .global) } action: { frame in
                piece.frame = frame
                state.report(frame, for: id, from: piece.token)
            }
            // A tab that comes back with the same layout reports no geometry change, so the last frame is sent again.
            .onAppear {
                if let frame = piece.frame { state.report(frame, for: id, from: piece.token) }
            }
            .onDisappear { state.forget(id, from: piece.token) }
            // The owner may do the real thing instead of pressing 다음. The element's own action still runs, and
            // the gesture exists only while this element's stop is showing.
            .simultaneousGesture(TapGesture().onEnded { state.ownerUsed(id) },
                                 isEnabled: state.stop?.anchors.contains(id) == true)
    }
}

/// One anchored view's identity and last frame. A reference, so a scroll does not redraw the row to store them.
private final class AnchorPiece {
    let token = UUID()
    var frame: CGRect?
}
