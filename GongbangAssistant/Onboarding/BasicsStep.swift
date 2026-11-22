import SwiftUI

struct BasicsStep: View {
    let next: () -> Void
    let skip: () -> Void

    @State private var policies = Loader<[BK06PolicyVersion]>()
    @State private var costs = Loader<OutreachCostSettings>()
    @State private var cards = Loader<[BK25FactCardSummary]>()
    @State private var opened: BasicsItem?
    @Environment(AppModel.self) private var app

    var body: some View {
        List {
            OnboardingStepTitleRow(title: "\(AssistantIdentity.name)가 일하려면 필요한 것")
            CardSection {
                ForEach(BasicsItem.allCases) { item in
                    row(item)
                }
            } footer: {
                Text("지금 하지 않아도 돼요. 설정에서 같은 화면을 다시 열 수 있어요.")
            }
        }
        .cardList()
        .refreshable { await load() }
        .task(id: app.dataVersion) { await load() }
        // The fact card screen saves without bumping dataVersion, so closing a screen always reloads.
        .sheet(item: $opened, onDismiss: { Task { await load() } }) { item in
            NavigationStack {
                screen(item)
                    .toolbar {
                        ToolbarItem(placement: .cancellationAction) { Button("닫기") { opened = nil } }
                    }
            }
        }
        .onboardingStepPrimaryButton(title: "다음", identifier: "onboarding.basics.next", action: next)
    }

    @ViewBuilder
    private func screen(_ item: BasicsItem) -> some View {
        switch item {
        case .policy: BK06PolicyView()
        case .costs: ClassCostListView()
        case .factCards: BK25FactCardListView()
        }
    }

    private func row(_ item: BasicsItem) -> some View {
        let state = progress(of: item)
        return Button {
            opened = item
        } label: {
            HStack(alignment: .top, spacing: 12) {
                DoneMark(isDone: state?.isDone ?? false)
                    .accessibilityHidden(true)
                VStack(alignment: .leading, spacing: 4) {
                    Text(item.title)
                        .font(.headline)
                    Text(item.reason)
                        .font(.subheadline)
                        .foregroundStyle(Color.secondaryText)
                    if let state {
                        StatusBadge(state.status, isPlain: true)
                    } else if hasFailed(item) {
                        StatusBadge(Status(text: "확인하지 못했어요", tone: .neutral), isPlain: true)
                    } else {
                        ProgressView()
                            .controlSize(.small)
                    }
                }
                Spacer(minLength: 8)
                Image(systemName: "chevron.forward")
                    .font(.footnote.weight(.semibold))
                    .foregroundStyle(.tertiary)
                    .accessibilityHidden(true)
            }
            .contentShape(.rect)
            .padding(.vertical, 4)
        }
        .buttonStyle(.plain)
        .accessibilityIdentifier("onboarding.basics.\(item.rawValue)")
    }

    private func load() async {
        await policies.load { try await RoundupAPI.k06Policies() }
        await costs.load { try await RoundupAPI.outreachCosts() }
        await cards.load { try await BK25API.factCards() }
    }

    private func hasFailed(_ item: BasicsItem) -> Bool {
        switch item {
        case .policy: policies.errorMessage != nil
        case .costs: costs.errorMessage != nil
        case .factCards: cards.errorMessage != nil
        }
    }

    /// Nil until the server has answered for that row.
    private func progress(of item: BasicsItem) -> BasicsProgress? {
        switch item {
        case .policy:
            guard let versions = policies.value else { return nil }
            guard let current = versions.first else { return .todo("아직 없음") }
            return .done("\(current.version)판 저장됨")
        case .costs:
            guard let data = costs.value else { return nil }
            if data.classes.isEmpty { return .waiting("수업 먼저 필요") }
            let filled = data.classes.filter { !$0.isMissing }.count
            if filled < data.classes.count { return .todo("수업 \(data.classes.count)개 중 \(filled)개 입력") }
            // The defaults screen stores an empty minimum as 0.
            if (data.defaults?.minimumFeeKrw ?? 0) <= 0 { return .todo("최소 금액 없음") }
            return .done("모두 입력")
        case .factCards:
            guard let list = cards.value else { return nil }
            if list.isEmpty { return .waiting("수업 먼저 필요") }
            let full = list.filter { $0.filledCount >= BK25FactField.allCases.count }.count
            if full < list.count { return .todo("수업 \(list.count)개 중 \(full)개 채움") }
            return .done("모두 채움")
        }
    }
}

private struct BasicsProgress {
    let isDone: Bool
    let status: Status

    static func done(_ text: String) -> BasicsProgress {
        BasicsProgress(isDone: true, status: Status(text: text, tone: .done))
    }

    static func todo(_ text: String) -> BasicsProgress {
        BasicsProgress(isDone: false, status: Status(text: text, tone: .attention))
    }

    /// Nothing to fill in yet: both class screens list the calendar's classes.
    static func waiting(_ text: String) -> BasicsProgress {
        BasicsProgress(isDone: false, status: Status(text: text, tone: .neutral))
    }
}

private enum BasicsItem: String, CaseIterable, Identifiable {
    case policy
    case costs
    case factCards

    var id: Self { self }

    var title: String {
        switch self {
        case .policy: "취소 규정"
        case .costs: "수업별 원가와 최소 금액"
        case .factCards: "수업 사실 카드"
        }
    }

    /// One sentence: what the assistant cannot do without it.
    var reason: String {
        switch self {
        case .policy: "없으면 취소 문자가 와도 환불액을 계산하지 못해요."
        case .costs: "없으면 출강 문의에 견적을 내지 못해요."
        case .factCards: "없으면 답장 초안에 소요 시간, 정원, 주차 같은 사실을 쓰지 못해요."
        }
    }
}
