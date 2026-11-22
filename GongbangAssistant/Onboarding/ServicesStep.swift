import SwiftUI

/// Onboarding step: the rows of 설정 > 채널 연결, with the services this kind of workshop uses first on top.
/// Nothing here is required; the owner may go on with nothing saved.
struct ServicesStep: View {
    let next: () -> Void
    let skip: () -> Void
    /// BusinessType's raw value as the workshop step stored it; empty or unknown keeps the catalogue order.
    @AppStorage("onboarding.businessType") private var businessType = ""

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            VStack(alignment: .leading, spacing: 8) {
                Text("요즘 쓰시는 채널에 체크해 주세요")
                    .font(.title2.weight(.bold))
                    .accessibilityAddTraits(.isHeader)
                Text("링크랑 계정 이름만 갖고 있어요. 그 서비스에 로그인하는 일은 없어요.")
                    .font(.body)
                    .foregroundStyle(Color.secondaryText)
            }
            .padding(.horizontal, 20)
            .padding(.top, 8)
            .padding(.bottom, 12)
            ConnectionsList(order: ConnectionCatalog.ordered(forBusinessType: businessType))
        }
        .safeAreaInset(edge: .bottom) {
            Button(action: next) {
                Text("다음")
                    .frame(maxWidth: .infinity)
            }
            .buttonStyle(.borderedProminent)
            .controlSize(.large)
            .padding(.horizontal, 20)
            .padding(.vertical, 12)
            .accessibilityIdentifier("onboarding.services.next")
        }
    }
}
