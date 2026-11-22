import SwiftUI

/// Onboarding step 요금제: pick an option and keep it on this device. Nothing is charged. The step pins its
/// own primary button in the bottom safe area; skipping is the container's 나중에 하기.
struct PlanStep: View {
    let next: () -> Void
    let skip: () -> Void
    @State private var pickedID = PlanSelection.shared.chosen?.id ?? PlanCatalog.defaultPlanID

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 20) {
                Text("요금제 하나만 미리 정해 두세요")
                    .font(.title2.bold())
                    .accessibilityAddTraits(.isHeader)
                PlanOptions(pickedID: $pickedID)
            }
            .padding(.horizontal, 16)
            .padding(.vertical, 12)
        }
        .safeAreaInset(edge: .bottom, spacing: 0) {
            PlanChooseBar(title: "이걸로 할게요", isEnabled: true) {
                if let plan = PlanCatalog.options.first(where: { $0.id == pickedID }) {
                    PlanSelection.shared.choose(plan)
                }
                next()
            }
            .accessibilityIdentifier("onboarding.plan.bar")
        }
    }
}
