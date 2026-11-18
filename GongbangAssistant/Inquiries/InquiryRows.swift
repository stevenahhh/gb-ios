import SwiftUI
import RoundupCore

// Value navigation keeps the detail open when a decision changes list order.
struct InquiryRoute: Hashable {
    let id: String
}

extension View {
    func inquiryDestination() -> some View {
        navigationDestination(for: InquiryRoute.self) { route in
            InquiryDetailView(id: route.id)
        }
    }
}

extension ReplyStatus {
    var badge: Status {
        switch self {
        case .pending: Status(text: "답변 대기", tone: .attention)
        case .approved: Status(text: "답변 완료", tone: .done)
        }
    }
}

struct InquiryRow: View {
    let inquiry: Inquiry
    @Environment(\.dynamicTypeSize) private var dynamicTypeSize

    var body: some View {
        NavigationLink(value: InquiryRoute(id: inquiry.id)) {
            VStack(alignment: .leading, spacing: 6) {
                let header = dynamicTypeSize.isAccessibilitySize
                    ? AnyLayout(VStackLayout(alignment: .leading, spacing: 4))
                    : AnyLayout(HStackLayout(alignment: .firstTextBaseline))
                header {
                    Text(keepingWords: inquiry.subject).font(.headline)
                    if !dynamicTypeSize.isAccessibilitySize { Spacer(minLength: 8) }
                    StatusBadge(inquiry.status.badge)
                }
                Text(inquiry.customer).font(.subheadline).foregroundStyle(.secondary)
                Text(inquiry.question).font(.subheadline).foregroundStyle(.secondary).lineLimit(2)
            }
            .padding(.vertical, 4)
        }
        .accessibilityIdentifier("inquiry.\(inquiry.id)")
    }
}
