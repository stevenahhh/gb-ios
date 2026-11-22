import Foundation
import SwiftUI

extension Plan {
    /// "월 14,900원", or "0원" for the option without a subscription.
    var priceText: String {
        monthlyPriceKRW > 0 ? "월 \(OutreachFormat.won(monthlyPriceKRW))" : OutreachFormat.won(monthlyPriceKRW)
    }
}

extension PlanAllowance {
    /// "월 100건" for an allowance that refills each month, "1곳" for a fixed one.
    var text: String {
        let count = "\(amount.formatted(.number.grouping(.automatic)))\(unit)"
        return isMonthly ? "월 \(count)" : count
    }
}

/// One option as a drawn card: a header that picks it, then what it includes. The pick is marked by the
/// check in the header, never by an outline or a color.
struct PlanCard: View {
    let plan: Plan
    let isPicked: Bool
    let pick: () -> Void
    @Environment(\.dynamicTypeSize) private var dynamicTypeSize

    private var spokenTitle: String {
        plan.monthlyPriceKRW > 0 ? "\(plan.name), \(plan.priceText), 부가세 포함" : "\(plan.name), \(plan.priceText)"
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Button(action: pick) { header }
                .buttonStyle(.plain)
                .accessibilityLabel(spokenTitle)
                .accessibilityAddTraits(isPicked ? .isSelected : [])
                .accessibilityIdentifier("plan.option.\(plan.id)")
            details
        }
        .padding(16)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(AppPalette.card, in: RoundedRectangle.card)
        // The whole card picks; VoiceOver uses the header button.
        .contentShape(RoundedRectangle.card)
        .onTapGesture(perform: pick)
    }

    private var header: some View {
        // At accessibility sizes the price moves under the name, so neither is squeezed.
        let layout = dynamicTypeSize.isAccessibilitySize
            ? AnyLayout(VStackLayout(alignment: .leading, spacing: 4))
            : AnyLayout(HStackLayout(alignment: .firstTextBaseline, spacing: 12))
        return layout {
            HStack(alignment: .firstTextBaseline, spacing: 8) {
                Image(systemName: isPicked ? "checkmark.circle.fill" : "circle")
                    .font(.title3)
                    .foregroundStyle(isPicked ? Color.primary : Color.secondaryText)
                Text(verbatim: plan.name)
                    .font(.headline)
            }
            if !dynamicTypeSize.isAccessibilitySize {
                Spacer(minLength: 8)
            }
            VStack(alignment: dynamicTypeSize.isAccessibilitySize ? .leading : .trailing, spacing: 2) {
                Text(verbatim: plan.priceText)
                    .font(.title3.bold())
                    .monospacedDigit()
                if plan.monthlyPriceKRW > 0 {
                    Text("부가세 포함")
                        .font(.subheadline)
                        .foregroundStyle(Color.secondaryText)
                }
            }
        }
        .frame(maxWidth: .infinity, minHeight: 44, alignment: .leading)
        .contentShape(.rect)
    }

    private var details: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(verbatim: plan.summary)
                .font(.subheadline)
                .foregroundStyle(Color.secondaryText)
            ForEach(plan.items) { item in
                PlanItemRow(item: item)
            }
        }
    }
}

struct PlanItemRow: View {
    let item: PlanItem
    @Environment(\.dynamicTypeSize) private var dynamicTypeSize

    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: 8) {
            Image(systemName: "checkmark")
                .font(.subheadline.weight(.semibold))
                .foregroundStyle(Color.secondaryText)
                .accessibilityHidden(true)
            let layout = dynamicTypeSize.isAccessibilitySize
                ? AnyLayout(VStackLayout(alignment: .leading, spacing: 2))
                : AnyLayout(HStackLayout(alignment: .firstTextBaseline, spacing: 8))
            layout {
                Text(verbatim: item.label)
                if let allowance = item.allowance {
                    if !dynamicTypeSize.isAccessibilitySize {
                        Spacer(minLength: 8)
                    }
                    Text(verbatim: allowance.text)
                        .fontWeight(.semibold)
                        .monospacedDigit()
                }
            }
        }
        .accessibilityElement(children: .combine)
    }
}
