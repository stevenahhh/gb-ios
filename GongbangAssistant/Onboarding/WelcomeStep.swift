import SwiftUI

struct WelcomeStep: View {
    let next: () -> Void
    let skip: () -> Void

    private let lines = [
        WelcomeLine(symbol: "bubble.left.and.bubble.right",
                    text: "손님 문의에 답장 초안을 써 둬요. 보낼지는 사장님이 정해요."),
        WelcomeLine(symbol: "checklist",
                    text: "예약금 확인, 포장, 송장 등록처럼 오늘 처리할 일을 모아서 보여 줘요."),
        WelcomeLine(symbol: "wonsign.circle",
                    text: "취소 문자가 오면 정해 둔 규정으로 환불액을 계산하고 출강 문의에는 견적을 내요."),
    ]

    var body: some View {
        List {
            OnboardingStepTitleRow(title: "공도리가 하는 일", showsMark: true)
            CardSection {
                ForEach(lines) { line in
                    Label { Text(line.text) } icon: { MenuIcon(systemName: line.symbol) }
                        .padding(.vertical, 4)
                }
            } footer: {
                Text("모든 단계는 건너뛸 수 있고 설정에서 다시 볼 수 있어요.")
            }
        }
        .cardList()
        .onboardingStepPrimaryButton(title: "시작하기", identifier: "onboarding.welcome.next", action: next)
    }
}

private struct WelcomeLine: Identifiable {
    let symbol: String
    let text: String
    var id: String { symbol }
}

/// The title a step starts with, drawn on the page above its first card.
struct OnboardingStepTitleRow: View {
    let title: String
    var showsMark = false

    var body: some View {
        Section {
            VStack(alignment: .leading, spacing: 12) {
                if showsMark { AssistantFace(size: .sheet) }
                Text(title)
                    .font(.title2.bold())
                    .accessibilityAddTraits(.isHeader)
            }
            .listRowBackground(Color.clear)
            .listRowSeparator(.hidden)
            .listRowInsets(EdgeInsets(top: 8, leading: 4, bottom: 0, trailing: 4))
        }
        .listSectionSeparator(.hidden)
    }
}

extension View {
    /// A step's one prominent button, pinned to the bottom. The flow lane had no chrome when this was written,
    /// so the three steps of this lane share this one place to rewire.
    func onboardingStepPrimaryButton(title: String, isBusy: Bool = false, isEnabled: Bool = true,
                                     identifier: String, action: @escaping () -> Void) -> some View {
        safeAreaInset(edge: .bottom) {
            BK06PrimaryButton(title: title, isBusy: isBusy, identifier: identifier, action: action)
                .disabled(!isEnabled)
                .padding(.horizontal, 20)
                .padding(.vertical, 12)
                .background(AppPalette.listBackground)
        }
    }
}
