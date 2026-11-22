import SwiftUI

/// The first-launch flow over the tabs: a bar with back, progress and the ways out, and one step below it.
/// Each step draws its own primary button at the bottom.
struct OnboardingFlow: View {
    private let state = OnboardingState.shared
    @Environment(AppModel.self) private var app
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        VStack(spacing: 0) {
            OnboardingBar()
            step
                .frame(maxWidth: .infinity, maxHeight: .infinity)
                .id(state.step)
                .transition(transition)
        }
        .background(AppPalette.listBackground)
        // The tabs' own notice is behind this cover, and deleting a saved service offers its undo there.
        .overlay { ToastHost().allowsHitTesting(app.toast != nil) }
        .animation(reduceMotion ? .easeInOut(duration: 0.2) : .snappy, value: state.step)
    }

    @ViewBuilder
    private var step: some View {
        let next = { state.next() }
        let skip = { state.skipStep() }
        switch state.step {
        case .welcome: WelcomeStep(next: next, skip: skip)
        case .workshop: WorkshopStep(next: next, skip: skip)
        case .services: ServicesStep(next: next, skip: skip)
        case .basics: BasicsStep(next: next, skip: skip)
        case .plan: PlanStep(next: next, skip: skip)
        case .tutorial: TutorialStep(next: next, skip: skip)
        }
    }

    private var transition: AnyTransition {
        guard !reduceMotion else { return .opacity }
        return .asymmetric(
            insertion: .move(edge: state.movesForward ? .trailing : .leading).combined(with: .opacity),
            removal: .opacity
        )
    }
}

private struct OnboardingBar: View {
    private let state = OnboardingState.shared
    private var page: Int { state.step.rawValue + 1 }
    private var isFirst: Bool { state.step == .welcome }
    private var isLast: Bool { state.step == .tutorial }

    var body: some View {
        HStack(spacing: 4) {
            Button("뒤로", systemImage: "chevron.left") { state.back() }
                .labelStyle(.iconOnly)
                .frame(minWidth: 44, minHeight: 44)
                .opacity(isFirst ? 0 : 1)
                .disabled(isFirst)
                .accessibilityHidden(isFirst)
                .accessibilityIdentifier("onboarding.back")
            progress
            // The last page has its own 나중에, and the first has nothing to put off.
            if !isFirst && !isLast {
                Button("나중에 하기") { state.skipStep() }
                    .font(.subheadline)
                    .frame(minHeight: 44)
                    .accessibilityIdentifier("onboarding.later")
            }
            Button("건너뛰기", systemImage: "xmark") { state.skipAll() }
                .labelStyle(.iconOnly)
                .frame(minWidth: 44, minHeight: 44)
                .accessibilityHint("안내 건너뛰고 바로 쓰기")
                .accessibilityIdentifier("onboarding.skipAll")
        }
        .padding(.horizontal, 12)
        .tint(.primary)
    }

    private var progress: some View {
        HStack(spacing: 6) {
            ForEach(OnboardingStep.allCases, id: \.self) { step in
                Capsule()
                    .fill(step.rawValue <= state.step.rawValue ? AnyShapeStyle(.primary) : AnyShapeStyle(.quaternary))
                    .frame(height: 4)
            }
        }
        .frame(maxWidth: .infinity)
        .accessibilityElement()
        .accessibilityLabel("\(page)/\(OnboardingStep.allCases.count)단계")
        .accessibilityIdentifier("onboarding.progress.\(page)")
    }
}
