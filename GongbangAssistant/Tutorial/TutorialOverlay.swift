import SwiftUI

/// The tutorial's own measures. Its colors come from `AppPalette` and `ColorRoles`.
enum TutorialTokens {
    /// Dims the screen around the cut-out, the same in light and dark mode.
    static let scrim = Color.black.opacity(0.55)
    /// A neutral hairline, so the cut-out's edge still shows on the black page in dark mode.
    static let ring = Color.white.opacity(0.4)
    /// Space between an element and the edge of its cut-out.
    static let outset: CGFloat = 6
    /// Space between the cut-out and the coach mark.
    static let gap: CGFloat = 12
    static let margin: CGFloat = 16
    /// Keeps the coach mark a readable width on iPad.
    static let maxCardWidth: CGFloat = 420
    /// A cut-out taller than this share of the screen is trimmed, so the coach mark keeps its room.
    static let maxHoleShare: CGFloat = 0.4
    /// How long a stop waits for its element before the run moves on without it.
    static let grace: Duration = .milliseconds(800)
}

extension View {
    /// Hosts the coach marks over the tab view. `selection` lets a stop bring its own tab forward.
    func tutorialOverlay(selection: Binding<AppTab>) -> some View {
        overlayPreferenceValue(TutorialAnchorKey.self) { anchors in
            TutorialOverlay(anchors: anchors, selection: selection)
        }
    }
}

/// One stop at a time: a dimmed screen with a cut-out around the real element and a coach mark beside it.
/// Stops only fade in and out, so Reduce Motion needs no separate path.
struct TutorialOverlay: View {
    let anchors: [TutorialAnchorID: Anchor<CGRect>]
    @Binding var selection: AppTab
    private let state = TutorialState.shared

    var body: some View {
        GeometryReader { proxy in
            if let stop = state.stop {
                let hole = hole(for: stop, in: proxy)
                let found = Found(stop: stop, isOnScreen: hole != nil)
                ZStack(alignment: .topLeading) {
                    scrim(around: hole, size: proxy.size)
                    if let hole {
                        ring(around: hole)
                        coachMark(for: stop, beside: hole, in: proxy)
                    }
                }
                .id(stop)
                .transition(.opacity)
                .onChange(of: found, initial: true) { _, found in
                    if found.isOnScreen { state.confirmShown(found.stop) }
                }
                // An element that is missing, or that leaves while its stop is up, ends the stop after a short wait.
                .task(id: found) {
                    guard !found.isOnScreen else { return }
                    try? await Task.sleep(for: TutorialTokens.grace)
                    if !Task.isCancelled { TutorialState.shared.skipMissing(found.stop) }
                }
            }
        }
        .ignoresSafeArea()
        .allowsHitTesting(state.isRunning)
        .animation(.easeInOut(duration: 0.2), value: state.stop)
        .onChange(of: state.stop, initial: true) { _, stop in
            if let tab = stop?.tab, tab != selection { selection = tab }
        }
    }

    /// The stop's cut-out in the overlay's own space, or nil while its element is not on screen.
    private func hole(for stop: TutorialStop, in proxy: GeometryProxy) -> CGRect? {
        let window = proxy.frame(in: .global)
        let screen = CGRect(origin: .zero, size: proxy.size)
        for id in stop.anchors {
            let reported = state.frame(for: id)?.offsetBy(dx: -window.minX, dy: -window.minY)
            guard let frame = reported ?? anchors[id].map({ proxy[$0] }) else { continue }
            // A tall group of cards is trimmed to the part on screen, and then to its top.
            var visible = frame.insetBy(dx: -TutorialTokens.outset, dy: -TutorialTokens.outset).intersection(screen)
            guard !visible.isNull, visible.width >= 44, visible.height >= 24 else { continue }
            visible.size.height = min(visible.height, screen.height * TutorialTokens.maxHoleShare)
            return visible
        }
        return nil
    }

    private func radius(of hole: CGRect) -> CGFloat {
        min(AppPalette.cardRadius, hole.height / 2)
    }

    private func scrim(around hole: CGRect?, size: CGSize) -> some View {
        let shape = Path { path in
            path.addRect(CGRect(origin: .zero, size: size))
            if let hole {
                let radius = radius(of: hole)
                path.addRoundedRect(in: hole, cornerSize: CGSize(width: radius, height: radius), style: .continuous)
            }
        }
        // The even-odd fill leaves the hole empty for drawing and for touches, so the real element under it
        // takes the owner's tap. Everywhere else the empty tap keeps the dimmed screen from reacting.
        return shape
            .fill(TutorialTokens.scrim, style: FillStyle(eoFill: true))
            .contentShape(shape, eoFill: true)
            .onTapGesture {}
            .accessibilityHidden(true)
    }

    private func ring(around hole: CGRect) -> some View {
        RoundedRectangle(cornerRadius: radius(of: hole), style: .continuous)
            .strokeBorder(TutorialTokens.ring, lineWidth: 1)
            .frame(width: hole.width, height: hole.height)
            .offset(x: hole.minX, y: hole.minY)
            .allowsHitTesting(false)
            .accessibilityHidden(true)
    }

    /// Under the cut-out when there is more room below it, otherwise above.
    private func coachMark(for stop: TutorialStop, beside hole: CGRect, in proxy: GeometryProxy) -> some View {
        let size = proxy.size
        let safe = proxy.safeAreaInsets
        let width = min(size.width - TutorialTokens.margin * 2, TutorialTokens.maxCardWidth)
        let leading = min(max(hole.midX - width / 2, TutorialTokens.margin), size.width - TutorialTokens.margin - width)
        let isBelow = size.height - safe.bottom - hole.maxY >= hole.minY - safe.top
        return CoachMark(stop: stop, position: state.position, total: state.total,
                         next: state.advance, skip: state.finish)
            .frame(width: width)
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: isBelow ? .topLeading : .bottomLeading)
            .padding(.leading, leading)
            .padding(isBelow ? .top : .bottom, (isBelow ? hole.maxY : size.height - hole.minY) + TutorialTokens.gap)
    }
}

/// Changes when the stop changes or its element comes or goes.
private struct Found: Hashable {
    let stop: TutorialStop
    let isOnScreen: Bool
}

/// The sentence, the count, 건너뛰기 and 다음. The box keeps one shape on every stop; only the last label changes.
private struct CoachMark: View {
    let stop: TutorialStop
    let position: Int
    let total: Int
    let next: () -> Void
    let skip: () -> Void
    @Environment(\.dynamicTypeSize) private var dynamicTypeSize
    @AccessibilityFocusState private var isFocused: Bool

    var body: some View {
        let isStacked = dynamicTypeSize.isAccessibilitySize
        let row = isStacked ? AnyLayout(VStackLayout(alignment: .leading, spacing: 8)) : AnyLayout(HStackLayout(spacing: 8))
        VStack(alignment: .leading, spacing: TutorialTokens.gap) {
            Text(verbatim: stop.sentence)
                .font(.body)
                .foregroundStyle(Color.primary)
                .fixedSize(horizontal: false, vertical: true)
                .accessibilityLabel("\(stop.sentence) \(total)개 중 \(position)번째 안내")
                .accessibilityFocused($isFocused)
                .accessibilityIdentifier("tutorial.sentence")
            row {
                Text(verbatim: "\(position)/\(total)")
                    .font(.subheadline.weight(.semibold))
                    .monospacedDigit()
                    .foregroundStyle(Color.secondaryText)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .accessibilityHidden(true)
                    .accessibilityIdentifier("tutorial.count")
                // Escape on a keyboard closes the tour.
                Button("건너뛰기", action: skip)
                    .buttonStyle(.bordered)
                    .keyboardShortcut(.cancelAction)
                    .accessibilityIdentifier("tutorial.skip")
                Button(position >= total ? "마치기" : "다음", action: next)
                    .buttonStyle(.borderedProminent)
                    .keyboardShortcut(.defaultAction)
                    .accessibilityIdentifier("tutorial.next")
            }
            .controlSize(.large)
        }
        .padding(TutorialTokens.margin)
        .background(AppPalette.card, in: .card)
        .accessibilityElement(children: .contain)
        .accessibilityAction(.escape, skip)
        .accessibilityIdentifier("tutorial.coach")
        // Each stop is a new coach mark, so VoiceOver moves to its sentence and reads it.
        .task { isFocused = true }
    }
}
