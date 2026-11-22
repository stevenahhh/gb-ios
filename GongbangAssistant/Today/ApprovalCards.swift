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

    /// The detail screen with its editor already open; a reply's editor is always open.
    @ViewBuilder
    var editor: some View {
        switch source {
        case .inquiry(let inquiry): InquiryDetailView(id: inquiry.id)
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
                ForEach(shown.prefix(3)) { card($0).tutorialAnchor(.approvals) }
                if shown.count > 3 {
                    NavigationLink("모두 보기") { ApprovalListView(items: items) }
                        .accessibilityIdentifier("approvals.all")
                }
            } header: {
                HStack(alignment: .firstTextBaseline) {
                    // `Color.primary` is the label color; `.primary` alone would be the header's gray.
                    Text("확인해 주실 일 \(items.count)건")
                        .font(.headline)
                        .foregroundStyle(Color.primary)
                    Spacer(minLength: 8)
                    // Only inquiries failed: a small note instead of another box.
                    if store.inquiryLoadError != nil, let last = store.lastLoadedAt {
                        Text("마지막 확인 \(last.formatted(date: .omitted, time: .shortened))")
                            .font(.subheadline)
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

/// Head (face, who wrote it, customer), title, two preview lines, then 답변 완료 or 승인 · 고치기.
/// Once decided the card stays and shows the F6 next step: copy, open the channel, or undo.
struct ApprovalCard: View {
    let item: ApprovalItem
    var onDecision: (Bool) -> Void = { _ in }
    /// A post or suggestion approved here. Replies read their state from the inquiry store instead.
    @State private var approvedDraft: (text: String, revision: Int)?
    @State private var isWorking = false
    @State private var isEditing = false
    @Environment(InquiryStore.self) private var store
    @Environment(AppModel.self) private var app

    /// What was decided, read when it is used. A completed reply stays editable, so its text and revision
    /// come from the store, never from the moment it was completed.
    private var decision: (text: String, revision: Int)? {
        switch item.source {
        case .inquiry(let inquiry):
            guard let current = store.inquiry(id: inquiry.id), current.status == .approved else { return nil }
            return (current.draft, current.revision)
        case .draft:
            return approvedDraft
        }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            NavigationLink(value: item.route) {
                VStack(alignment: .leading, spacing: 6) {
                    // The customer moves under the label when the two no longer fit on one line.
                    ViewThatFits(in: .horizontal) {
                        HStack(spacing: 6) {
                            AssistantDraftLabel(isReply: item.isReply)
                            Spacer(minLength: 8)
                            meta
                        }
                        VStack(alignment: .leading, spacing: 4) {
                            AssistantDraftLabel(isReply: item.isReply)
                            meta
                        }
                    }
                    Text(verbatim: item.title)
                        .font(.headline)
                    Text(verbatim: item.preview)
                        .font(.subheadline)
                        .foregroundStyle(Color.secondaryText)
                        .lineLimit(2)
                }
                .contentShape(.rect)
            }
            .buttonStyle(.plain)
            .navigationLinkIndicatorVisibility(.hidden)
            .accessibilityIdentifier(item.id)

            if let decision {
                decided(decision)
            } else {
                HStack(spacing: 10) {
                    Button(action: approve) {
                        BusyLabel(title: item.isReply ? "답변 완료" : "승인", isBusy: isWorking, isProminent: true)
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

    @ViewBuilder
    private var meta: some View {
        if let meta = item.meta {
            Text(meta)
                .font(.subheadline)
                .foregroundStyle(Color.secondaryText)
        }
    }

    private func decided(_ decision: (text: String, revision: Int)) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                Label(item.isReply ? "답변을 완료했어요" : "승인했어요", systemImage: "checkmark")
                    .font(.subheadline.weight(.medium))
                Spacer(minLength: 8)
                Button("되돌리기", systemImage: "arrow.uturn.backward") { undo(revision: decision.revision) }
                    .font(.subheadline.weight(.semibold))
                    .buttonStyle(.bordered)
                    .disabled(isWorking)
                    .accessibilityIdentifier("approval.undo.\(item.id)")
            }
            if let share = item.share {
                DraftShareActions(share: share, text: decision.text)
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
                    try await BK25Approval.approve(inquiry, store: store)
                case .draft(let kind, let id):
                    let detail = try await RoundupAPI.assistantDraft(kind: kind, id: id)
                    let draft = InquiryDraft(draft: detail.text, expectedRevision: detail.revision)
                    try await RoundupAPI.decideAssistantDraft(kind: kind, id: id,
                                                             decision: InquiryDecision(decision: .approve, draft: draft))
                    approvedDraft = (detail.text, detail.revision + 1)
                }
                onDecision(true)
                // The headline and the tab badge count waiting work from the server.
                app.dataDidChange()
            } catch {
                app.failureMessage = error.localizedDescription
            }
        }
    }

    private func undo(revision: Int) {
        isWorking = true
        Task {
            defer { isWorking = false }
            do {
                switch item.source {
                case .inquiry(let inquiry):
                    try await store.undoCompletion(id: inquiry.id, expectedRevision: revision)
                case .draft(let kind, let id):
                    try await RoundupAPI.reopenAssistantDraft(kind: kind, id: id, revision: revision)
                    approvedDraft = nil
                }
                onDecision(false)
                app.dataDidChange()
            } catch {
                app.failureMessage = error.localizedDescription
                app.dataDidChange()
            }
        }
    }
}
