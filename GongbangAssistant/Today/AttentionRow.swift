import SwiftUI

/// One low row of 확인해 주실 일: the title over its detail at the left, small buttons at the right.
/// At accessibility sizes the buttons move under the text. With a `route` the text opens the detail.
struct AttentionRow<Trailing: View>: View {
    private let title: String
    private let detail: String?
    private let isOverdue: Bool
    private let route: AppRoute?
    private let identifier: String
    private let trailing: Trailing
    @Environment(\.dynamicTypeSize) private var dynamicTypeSize

    init(title: String, detail: String?, isOverdue: Bool = false, route: AppRoute? = nil, identifier: String = "",
         @ViewBuilder trailing: () -> Trailing) {
        self.title = title
        self.detail = detail
        self.isOverdue = isOverdue
        self.route = route
        self.identifier = identifier
        self.trailing = trailing()
    }

    var body: some View {
        let layout = dynamicTypeSize.isAccessibilitySize
            ? AnyLayout(VStackLayout(alignment: .leading, spacing: 4))
            : AnyLayout(HStackLayout(spacing: 8))
        layout {
            if let route {
                NavigationLink(value: route) { text }
                    .buttonStyle(.plain)
                    .navigationLinkIndicatorVisibility(.hidden)
                    .accessibilityIdentifier(identifier)
            } else {
                text
            }
            if Trailing.self != EmptyView.self {
                buttons
            }
        }
    }

    @ViewBuilder
    private var buttons: some View {
        if dynamicTypeSize.isAccessibilitySize {
            ViewThatFits(in: .horizontal) {
                HStack(spacing: 6) { trailing }
                VStack(alignment: .leading, spacing: 0) { trailing }
            }
        } else {
            HStack(spacing: 6) { trailing }
                .fixedSize(horizontal: true, vertical: false)
        }
    }

    private var text: some View {
        // Larger text keeps wrapping instead of losing its end.
        let lines = dynamicTypeSize > .large ? nil : 2
        return VStack(alignment: .leading, spacing: 2) {
            HStack(alignment: .firstTextBaseline, spacing: 5) {
                if isOverdue { OverdueMark() }
                Text(verbatim: title)
                    .lineLimit(lines)
            }
            .font(.subheadline.weight(.semibold))
            if let detail {
                Text(verbatim: detail)
                    .font(.subheadline)
                    .foregroundStyle(Color.secondaryText)
                    .lineLimit(lines)
            }
        }
        .fixedSize(horizontal: false, vertical: true)
        .frame(maxWidth: .infinity, minHeight: 44, alignment: .leading)
        .contentShape(.rect)
        .accessibilityElement(children: .combine)
    }
}

/// A small button that looks 32pt tall and takes taps over 44pt. The style is explicit because a list row
/// otherwise fires all of its plain buttons at once.
struct AttentionButton: View {
    let title: String
    var isProminent = false
    var isBusy = false
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            BusyLabel(title: title, isBusy: isBusy, isProminent: isProminent)
        }
        .buttonStyle(AttentionButtonStyle(isProminent: isProminent))
        .disabled(isBusy)
    }
}

struct AttentionButtonStyle: ButtonStyle {
    var isProminent = false
    @Environment(\.isEnabled) private var isEnabled

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.subheadline.weight(.semibold))
            .foregroundStyle(isEnabled ? Color.primary : Color.secondaryText)
            .padding(.horizontal, 12)
            .padding(.vertical, 4)
            .frame(minHeight: 32)
            .background(isProminent && isEnabled ? AnyShapeStyle(Color.primary) : AnyShapeStyle(.fill.tertiary),
                        in: .rect(cornerRadius: 8, style: .continuous))
            .opacity(configuration.isPressed ? 0.6 : 1)
            .frame(minWidth: 44, minHeight: 44)
            .contentShape(.rect)
    }
}
