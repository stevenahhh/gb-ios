import RoundupCore
import SwiftUI

/// One draft the assistant wrote that waits for the owner's yes: an inquiry reply or a post/suggestion draft.
struct ApprovalItem: Identifiable {
    enum Source {
        case inquiry(Inquiry)
        case draft(DraftKind, String)
    }

    let source: Source
    let title: String
    let preview: String
    let meta: String?

    var id: String {
        switch source {
        case .inquiry(let inquiry): "inquiry.\(inquiry.id)"
        case .draft(let kind, let id): "draft.\(kind.rawValue).\(id)"
        }
    }

    var isReply: Bool {
        if case .inquiry = source { return true }
        return false
    }

    var route: AppRoute {
        switch source {
        case .inquiry(let inquiry): .inquiry(inquiry.id)
        case .draft(let kind, let id): .draft(kind, id)
        }
    }

    /// The detail screen with its editor already open.
    @ViewBuilder
    var editor: some View {
        switch source {
        case .inquiry(let inquiry): InquiryDetailView(id: inquiry.id, startsEditing: true)
        case .draft(let kind, let id): AssistantDraftDetailView(kind: kind, id: id, startsEditing: true)
        }
    }

    var share: DraftShare? {
        switch source {
        case .inquiry: .inquiry
        case .draft(let kind, _): kind == .content ? .content : nil
        }
    }

    /// Pending inquiry replies first, then pending post and suggestion drafts from the today screen.
    static func collect(inquiries: [Inquiry], today: TodayScreenData) -> [ApprovalItem] {
        let replies = inquiries.filter { $0.status == .pending }.map {
            ApprovalItem(source: .inquiry($0), title: $0.subject, preview: $0.draft, meta: "\($0.customer) 님")
        }
        var seen = Set<String>()
        let drafts = (today.suggestions.items + today.channels.todos).compactMap { item -> ApprovalItem? in
            guard let draft = item.draft, draft.status == .pending, seen.insert(draft.id).inserted else { return nil }
            return ApprovalItem(source: .draft(draft.kind, draft.id), title: item.title, preview: draft.preview, meta: nil)
        }
        return replies + drafts
    }
}

/// "확인해 주실 일": the assistant's drafts the owner approves or fixes right here, newest decisions kept in place.
struct ApprovalSection: View {
    let items: [ApprovalItem]
    /// Cards approved here stay on top with their next step until the screen goes away.
    @State private var approvedHere: [ApprovalItem] = []
    @Environment(InquiryStore.self) private var store

    private var shown: [ApprovalItem] {
        approvedHere + items.filter { item in !approvedHere.contains { $0.id == item.id } }
    }

    var body: some View {
        if !shown.isEmpty {
            CardSection {
                ForEach(shown.prefix(3)) { card($0) }
                if shown.count > 3 {
                    NavigationLink("모두 보기") { ApprovalListView(items: items) }
                        .accessibilityIdentifier("approvals.all")
                }
            } header: {
                HStack(alignment: .firstTextBaseline) {
                    Text("확인해 주실 일 \(items.count)건")
                        .font(.headline)
                        .foregroundStyle(.primary)
                    Spacer(minLength: 8)
                    // Only inquiries failed: a small note instead of another box.
                    if store.inquiryLoadError != nil, let last = store.lastLoadedAt {
                        Text("마지막 확인 \(last.formatted(date: .omitted, time: .shortened))")
                            .font(.footnote)
                            .foregroundStyle(Color.secondaryText)
                    }
                }
                .textCase(nil)
                .accessibilityIdentifier("approvals.header")
            }
        }
    }

    private func card(_ item: ApprovalItem) -> some View {
        ApprovalCard(item: item) { approved in
            if approved {
                approvedHere.insert(item, at: 0)
            } else {
                approvedHere.removeAll { $0.id == item.id }
            }
        }
    }
}

struct ApprovalListView: View {
    let items: [ApprovalItem]

    var body: some View {
        List {
            CardSection {
                ForEach(items) { ApprovalCard(item: $0) }
            }
        }
        .cardList()
        .navigationTitle("확인해 주실 일")
        .navigationBarTitleDisplayMode(.inline)
    }
}

/// Head (face, who wrote it, customer), title, two preview lines, then 승인 · 고치기.
/// After 승인 the card stays and shows the F6 next step: copy, open the channel, or undo.
struct ApprovalCard: View {
    let item: ApprovalItem
    var onDecision: (Bool) -> Void = { _ in }
    @State private var approved: (text: String, revision: Int)?
    @State private var isWorking = false
    @State private var isEditing = false
    @Environment(InquiryStore.self) private var store
    @Environment(AppModel.self) private var app

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            NavigationLink(value: item.route) {
                VStack(alignment: .leading, spacing: 6) {
                    HStack(spacing: 6) {
                        AssistantFace(size: .card)
                            .accessibilityHidden(true)
                        Text(item.isReply ? "\(AssistantIdentity.name)가 쓴 답변" : "\(AssistantIdentity.name)가 쓴 글")
                            .font(.system(size: 12, weight: .semibold))
                            .foregroundStyle(Color.assistantAccent)
                        Spacer(minLength: 8)
                        if let meta = item.meta {
                            Text(meta)
                                .font(.footnote)
                                .foregroundStyle(Color.secondaryText)
                        }
                    }
                    Text(keepingWords: item.title)
                        .font(.headline)
                    Text(keepingWords: item.preview)
                        .font(.subheadline)
                        .foregroundStyle(Color.secondaryText)
                        .lineLimit(2)
                }
                .contentShape(.rect)
            }
            .buttonStyle(.plain)
            .navigationLinkIndicatorVisibility(.hidden)
            .accessibilityIdentifier(item.id)

            if let approved {
                decided(approved)
            } else {
                HStack(spacing: 10) {
                    Button(action: approve) {
                        Group {
                            if isWorking { ProgressView() } else { Text("승인").foregroundStyle(Color(.systemBackground)) }
                        }
                        .font(.subheadline.weight(.semibold))
                        .frame(maxWidth: .infinity, minHeight: 40)
                    }
                    .buttonStyle(.borderedProminent)
                    .accessibilityIdentifier("approval.approve.\(item.id)")
                    Button {
                        isEditing = true
                    } label: {
                        Text("고치기")
                            .font(.subheadline.weight(.semibold))
                            .frame(maxWidth: .infinity, minHeight: 40)
                    }
                    .buttonStyle(.bordered)
                    .accessibilityIdentifier("approval.edit.\(item.id)")
                }
                .disabled(isWorking)
            }
        }
        .padding(.vertical, 6)
        .navigationDestination(isPresented: $isEditing) { item.editor }
    }

    private func decided(_ approved: (text: String, revision: Int)) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                Label("승인했어요", systemImage: "checkmark")
                    .font(.subheadline.weight(.medium))
                Spacer(minLength: 8)
                Button("되돌리기", systemImage: "arrow.uturn.backward", action: reopen)
                    .font(.subheadline.weight(.semibold))
                    .buttonStyle(.bordered)
                    .disabled(isWorking)
            }
            if let share = item.share {
                DraftShareActions(share: share, text: approved.text)
            }
        }
    }

    private func approve() {
        isWorking = true
        Task {
            defer { isWorking = false }
            do {
                switch item.source {
                case .inquiry(let inquiry):
                    let draft = InquiryDraft(draft: inquiry.draft, expectedRevision: inquiry.revision)
                    try await store.decide(id: inquiry.id, decision: InquiryDecision(decision: .approve, draft: draft))
                    approved = (inquiry.draft, inquiry.revision + 1)
                case .draft(let kind, let id):
                    let detail = try await RoundupAPI.assistantDraft(kind: kind, id: id)
                    let draft = InquiryDraft(draft: detail.text, expectedRevision: detail.revision)
                    try await RoundupAPI.decideAssistantDraft(kind: kind, id: id,
                                                             decision: InquiryDecision(decision: .approve, draft: draft))
                    approved = (detail.text, detail.revision + 1)
                }
                onDecision(true)
            } catch {
                app.failureMessage = error.localizedDescription
            }
        }
    }

    private func reopen() {
        guard let approved else { return }
        isWorking = true
        Task {
            defer { isWorking = false }
            do {
                switch item.source {
                case .inquiry(let inquiry):
                    try await store.reopen(id: inquiry.id, request: InquiryReopen(expectedRevision: approved.revision))
                case .draft(let kind, let id):
                    try await RoundupAPI.reopenAssistantDraft(kind: kind, id: id, revision: approved.revision)
                }
                self.approved = nil
                onDecision(false)
                app.dataDidChange()
            } catch {
                app.failureMessage = error.localizedDescription
                app.dataDidChange()
            }
        }
    }
}
