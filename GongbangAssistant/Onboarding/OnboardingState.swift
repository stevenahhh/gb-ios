import Foundation
import Observation

/// The first-launch flow's pages, in the order the owner sees them.
enum OnboardingStep: Int, CaseIterable {
    case welcome, workshop, services, basics, plan, tutorial
}

/// UserDefaults keys the flow reads and writes. `done` and `tutorialDone` are read as Bool, so the launch
/// arguments `-onboarding.done YES -tutorial.done YES` start the app straight on 오늘.
enum OnboardingKeys {
    static let done = "onboarding.done"
    static let tutorialDone = "tutorial.done"
    /// Raw value of the page to resume on. Written on every page change, removed when the flow ends.
    static let step = "onboarding.step"
    /// `-onboarding.reset YES` clears the three keys above at launch, so a UI test starts as a first launch.
    static let reset = "onboarding.reset"
}

/// Where the owner is in the first-launch flow. One shared instance, so the root cover, the steps, 설정 and the
/// tutorial agree.
@MainActor
@Observable
final class OnboardingState {
    static let shared = OnboardingState()

    /// The page on screen. Saved on every change, so a relaunch resumes here.
    var step: OnboardingStep {
        didSet { defaults.set(step.rawValue, forKey: OnboardingKeys.step) }
    }

    /// Drives the full-screen cover over the tabs.
    var isPresented: Bool

    /// False after `back()`, so the container slides the page the right way.
    private(set) var movesForward = true

    /// True from the moment the flow ends on its last page's button until the coach marks end.
    private(set) var isTutorialPending: Bool

    /// The coach marks run over the real screens, so they wait until the cover is gone.
    var isTutorialActive: Bool { !isPresented && isTutorialPending }

    private let defaults: UserDefaults

    init(defaults: UserDefaults = .standard) {
        if defaults.bool(forKey: OnboardingKeys.reset) {
            for key in [OnboardingKeys.done, OnboardingKeys.tutorialDone, OnboardingKeys.step] {
                defaults.removeObject(forKey: key)
            }
        }
        self.defaults = defaults
        let isDone = defaults.bool(forKey: OnboardingKeys.done)
        let saved = OnboardingStep(rawValue: defaults.integer(forKey: OnboardingKeys.step)) ?? .welcome
        step = isDone ? .welcome : saved
        isPresented = !isDone
        isTutorialPending = !defaults.bool(forKey: OnboardingKeys.tutorialDone)
    }

    /// Moves on. From the last page it ends the flow and starts the tutorial.
    func next() {
        guard let following = OnboardingStep(rawValue: step.rawValue + 1) else {
            finish(startingTutorial: true)
            return
        }
        movesForward = true
        step = following
    }

    func back() {
        guard let previous = OnboardingStep(rawValue: step.rawValue - 1) else { return }
        movesForward = false
        step = previous
    }

    /// 나중에 하기. Putting off the last page also puts off the tour it offers.
    func skipStep() {
        guard let following = OnboardingStep(rawValue: step.rawValue + 1) else {
            finish(startingTutorial: false)
            return
        }
        movesForward = true
        step = following
    }

    /// 건너뛰기. Ends the flow at once; 설정 can replay it.
    func skipAll() {
        finish(startingTutorial: false)
    }

    /// 설정 > 처음 안내 다시 보기. A replay lives in memory only, so quitting halfway never brings it back at launch.
    func restart() {
        movesForward = true
        step = .welcome
        isPresented = true
    }

    /// The tutorial calls this when its last mark is passed or the owner closes it.
    func finishTutorial() {
        defaults.set(true, forKey: OnboardingKeys.tutorialDone)
        isTutorialPending = false
    }

    private func finish(startingTutorial: Bool) {
        defaults.set(true, forKey: OnboardingKeys.done)
        defaults.set(!startingTutorial, forKey: OnboardingKeys.tutorialDone)
        defaults.removeObject(forKey: OnboardingKeys.step)
        isTutorialPending = startingTutorial
        isPresented = false
    }
}
