import SwiftUI

struct WelcomeStep: View {
    let next: () -> Void
    let skip: () -> Void

    private let lines = [
        WelcomeLine(symbol: "bubble.left.and.bubble.right",
                    text: "손님 질문이 들어오면 비서가 답장 초안을 미리 마련해요. 보내는 건 사장님이 결정하세요."),
        WelcomeLine(symbol: "checklist",
                    text: "입금 들어왔는지 보기, 포장하기, 송장 등록하기처럼 그날 챙길 일을 한 화면에 모아 드려요."),
        WelcomeLine(symbol: "wonsign.circle",
                    text: "손님 취소 문자가 들어오면 미리 정한 규정대로 돌려드릴 금액을 계산하고 출장 수업 문의엔 견적을 뽑아 드려요."),
    ]

    var body: some View {
        List {
            OnboardingStepTitleRow(title: "공도리가 해 드리는 일", showsMark: true)
            CardSection {
                ForEach(lines) { line in
                    Label { Text(line.text) } icon: { MenuIcon(systemName: line.symbol) }
                        .padding(.vertical, 4)
                }
            } footer: {
                Text("어느 단계든 건너뛰셔도 괜찮아요. 나중에 설정 메뉴에서 언제든 꺼내 볼 수 있어요.")
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
