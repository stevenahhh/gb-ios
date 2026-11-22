import SwiftUI

/// The 요금제 row for 설정: the picked plan at the trailing edge, and under the title that no payment has
/// happened. Place it directly inside a `CardSection`.
struct CurrentPlanRow: View {
    private let selection = PlanSelection.shared

    var body: some View {
        NavigationLink { PlanView() } label: {
            LabeledContent {
                if let plan = selection.chosen { Text(verbatim: plan.name) }
            } label: {
                Label {
                    Text("요금제")
                    Text(verbatim: selection.chosen == nil ? "아직 고르지 않았어요" : PlanCatalog.paymentNotice)
                        .foregroundStyle(Color.secondaryText)
                } icon: { MenuIcon(systemName: "creditcard") }
            }
        }
        .accessibilityIdentifier("settings.plan")
    }
}
