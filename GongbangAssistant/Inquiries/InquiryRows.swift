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
        case .approved: Status(text: "답변 승인", tone: .done)
        case .rejected: Status(text: "초안 반려", tone: .neutral)
        }
    }
}

extension [Metric] {
    func withPendingInquiries(_ count: Int) -> [Metric] {
        map { $0.label == "미답변 문의" ? Metric(value: "\(count)건", label: $0.label) : $0 }
    }
}

extension WorkItem {
    func withPendingInquiries(_ count: Int) -> WorkItem {
        var item = self
        item.lines = lines.map { $0.replacingOccurrences(of: "문의 3건", with: "문의 \(count)건") }
        if deadline?.contains("문의 3건") == true {
            item.deadline = count == 0 ? nil : "문의 \(count)건이 답을 기다려요"
        }
        return item
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
