import SwiftUI

/// The last onboarding step: names the places the tour points at, then starts it over the real screens.
struct TutorialStep: View {
    let next: () -> Void
    let skip: () -> Void

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 20) {
                VStack(alignment: .leading, spacing: 8) {
                    Text("화면을 같이 둘러봐요")
                        .font(.title2.bold())
                        .accessibilityAddTraits(.isHeader)
                    Text("자주 쓰는 곳을 실제 화면에서 하나씩 짚어 드려요. 아직 내용이 없는 곳은 지나가요.")
                        .font(.body)
                        .foregroundStyle(Color.secondaryText)
                }
                VStack(alignment: .leading, spacing: 0) {
                    ForEach(TutorialStop.allCases) { stop in
                        Label {
                            Text(stop.title)
                        } icon: {
                            MenuIcon(systemName: stop.symbol)
                        }
                        .frame(maxWidth: .infinity, minHeight: 44, alignment: .leading)
                        .padding(.horizontal, 16)
                        .padding(.vertical, 4)
                    }
                }
                .padding(.vertical, 8)
                .background(AppPalette.card, in: .card)
            }
            .padding(.horizontal, 20)
            .padding(.top, 8)
        }
        .scrollBounceBehavior(.basedOnSize)
        .safeAreaInset(edge: .bottom) {
            VStack(spacing: 8) {
                Button {
                    TutorialState.shared.start()
                    next()
                } label: {
                    Text("시작하기").frame(maxWidth: .infinity)
                }
                .buttonStyle(.borderedProminent)
                .accessibilityIdentifier("onboarding.tutorial.start")
                Button(action: skip) {
                    Text("나중에").frame(maxWidth: .infinity)
                }
                .buttonStyle(.bordered)
                .accessibilityIdentifier("onboarding.tutorial.later")
            }
            .controlSize(.large)
            .padding(.horizontal, 20)
            .padding(.vertical, 8)
            .background(AppPalette.listBackground)
        }
        .background(AppPalette.listBackground)
    }
}
