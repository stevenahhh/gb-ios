import SwiftUI

/// 설정 > 요금제: the plan in use, every option with what it includes, and one button that keeps the pick on
/// this device. No usage numbers are shown, because the app keeps no local count of drafts or voice minutes.
struct PlanView: View {
    private let selection = PlanSelection.shared
    @State private var pickedID = PlanSelection.shared.chosen?.id ?? PlanCatalog.defaultPlanID
    @State private var storedCount = 0
    @Environment(\.dynamicTypeSize) private var dynamicTypeSize

    private var isStored: Bool { selection.chosenID == pickedID }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 20) {
                current
                PlanOptions(pickedID: $pickedID)
            }
            .padding(.horizontal, 16)
            .padding(.vertical, 12)
        }
        .background(AppPalette.listBackground)
        .navigationTitle("요금제")
        .navigationBarTitleDisplayMode(.inline)
        .safeAreaInset(edge: .bottom, spacing: 0) {
            // One box in both states: the title changes, the button keeps its size.
            PlanChooseBar(title: isStored ? "골라 두신 요금제" : "이걸로 할게요",
                          isEnabled: !isStored, action: choose)
        }
        .sensoryFeedback(.success, trigger: storedCount)
    }

    private var current: some View {
        let layout = dynamicTypeSize.isAccessibilitySize
            ? AnyLayout(VStackLayout(alignment: .leading, spacing: 4))
            : AnyLayout(HStackLayout(alignment: .firstTextBaseline, spacing: 12))
        return layout {
            Text("현재 요금제")
                .foregroundStyle(Color.secondaryText)
            if !dynamicTypeSize.isAccessibilitySize {
                Spacer(minLength: 8)
            }
            Text(verbatim: selection.chosen?.name ?? "고른 요금제 없음")
                .font(.body.weight(.semibold))
        }
        .padding(16)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(AppPalette.card, in: RoundedRectangle.card)
        .accessibilityElement(children: .combine)
        .accessibilityIdentifier("plan.current")
    }

    private func choose() {
        guard let plan = PlanCatalog.options.first(where: { $0.id == pickedID }) else { return }
        selection.choose(plan)
        storedCount += 1
        AccessibilityNotification.Announcement("지금 고르신 요금제: \(plan.name). \(PlanCatalog.paymentNotice)").post()
    }
}

/// The option cards, what happens at a limit, and the closing notes. Shared by 설정 and the onboarding step.
struct PlanOptions: View {
    @Binding var pickedID: Plan.ID

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            ForEach(PlanCatalog.options) { plan in
                PlanCard(plan: plan, isPicked: plan.id == pickedID) { pickedID = plan.id }
            }
            VStack(alignment: .leading, spacing: 8) {
                Text("횟수를 다 쓰면")
                    .font(.headline)
                    .accessibilityAddTraits(.isHeader)
                ForEach(PlanCatalog.atLimitLines, id: \.self) { line in
                    Text(verbatim: line)
                }
            }
            .padding(16)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(AppPalette.card, in: RoundedRectangle.card)
            VStack(alignment: .leading, spacing: 4) {
                ForEach(PlanCatalog.footnotes, id: \.self) { line in
                    Text(verbatim: line)
                }
            }
            .font(.subheadline)
            .foregroundStyle(Color.secondaryText)
            .padding(.horizontal, 16)
        }
    }
}

/// The screen's one prominent button, pinned in the bottom safe area under the line that says no money moves.
struct PlanChooseBar: View {
    let title: String
    let isEnabled: Bool
    let action: () -> Void

    var body: some View {
        VStack(spacing: 0) {
            Rectangle().fill(CalendarTokens.separator).frame(height: 1)
            VStack(alignment: .leading, spacing: 8) {
                VStack(alignment: .leading, spacing: 2) {
                    Text(verbatim: PlanCatalog.paymentNotice)
                        .font(.subheadline.weight(.semibold))
                    Text(verbatim: PlanCatalog.paymentDetail)
                        .font(.subheadline)
                        .foregroundStyle(Color.secondaryText)
                }
                .accessibilityElement(children: .combine)
                .accessibilityIdentifier("plan.notice")
                Button(action: action) {
                    BusyLabel(title: title, isBusy: false, isProminent: true)
                        .font(.subheadline.weight(.semibold))
                        .frame(maxWidth: .infinity, minHeight: 30)
                }
                .buttonStyle(.borderedProminent)
                .controlSize(.large)
                .disabled(!isEnabled)
                .accessibilityIdentifier("plan.choose")
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(.horizontal, 16)
            .padding(.vertical, 12)
        }
        .background(AppPalette.listBackground)
    }
}
