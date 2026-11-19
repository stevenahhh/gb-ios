import SwiftUI
import RoundupCore

extension ReplyStatus {
    var badge: Status {
        switch self {
        case .pending: Status(text: "검토 대기", tone: .attention)
        case .approved: Status(text: "승인함", tone: .done)
        case .rejected: Status(text: "반려함", tone: .neutral)
        }
    }
}

private struct AssistantDraftLabel: View {
    var body: some View {
        HStack(spacing: 5) {
            Image(systemName: "sparkles")
                .accessibilityHidden(true)
            Text("비서 초안")
        }
        .font(.footnote.weight(.semibold))
    }
}

struct AssistantDraftRow: View {
    let title: String
    let text: String
    let badge: Status
    let route: AppRoute
    let identifier: String

    init(title: String, reference: DraftReference) {
        self.title = title
        text = reference.preview
        badge = reference.status.badge
        route = .draft(reference.kind, reference.id)
        identifier = "draft.\(reference.kind.rawValue).\(reference.id)"
    }

    init(inquiry: Inquiry) {
        title = inquiry.subject
        text = inquiry.draft
        badge = inquiry.badge
        route = .inquiry(inquiry.id)
        identifier = "inquiry.\(inquiry.id)"
    }

    var body: some View {
        NavigationLink(value: route) {
            VStack(alignment: .leading, spacing: 6) {
                HStack {
                    AssistantDraftLabel()
                    Spacer(minLength: 8)
                    StatusBadge(badge)
                }
                Text(keepingWords: title)
                    .font(.headline)
                Text(text.isEmpty ? "내용을 비운 초안이에요." : text)
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
                    .lineLimit(2)
            }
            .padding(.vertical, 4)
        }
        .accessibilityIdentifier(identifier)
    }
}

struct DraftCardActions {
    let save: @MainActor (String, Int) async throws -> Void
    let decide: @MainActor (ReplyDecision, Int) async throws -> Void
    let reopen: @MainActor (Int) async throws -> Void
    let rewrite: @MainActor () async throws -> String
}

struct AssistantDraftCard: View {
    let text: String
    let status: ReplyStatus
    let revision: Int
    let canReopen: Bool
    let afterApproval: String
    let isOwnerEdited: Bool
    let isLocked: Bool
    let actions: DraftCardActions

    @State private var isEditing = false
    @State private var buffer = ""
    @State private var editRevision = 0
    @State private var isRewriting = false
    @State private var isSubmitting = false
    @State private var errorMessage: String?
    @Environment(AppModel.self) private var app

    private var isDisabled: Bool { isLocked || isRewriting || isSubmitting }

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                AssistantDraftLabel()
                Spacer(minLength: 8)
                StatusBadge(status.badge)
            }
            if isEditing {
                editor
            } else {
                draftText
                switch status {
                case .pending: pendingActions
                case .approved, .rejected: decidedActions
                }
            }
            if let errorMessage {
                Label {
                    PhraseText(text: errorMessage).foregroundStyle(.primary)
                } icon: {
                    Image(systemName: "exclamationmark.circle.fill").foregroundStyle(.orange)
                }
                .font(.subheadline.weight(.semibold))
                .accessibilityIdentifier("draft.error")
            }
            if isOwnerEdited && !isEditing {
                hint("사장님이 고친 내용이에요.")
            }
        }
        .padding(.vertical, 4)
        .sensoryFeedback(.success, trigger: status)
    }

    private var draftText: some View {
        Group {
            if text.isEmpty {
                Text(status == .pending ? "내용이 비어 있어요." : "내용을 비운 채 반려했어요.")
                    .foregroundStyle(.secondary)
            } else {
                Text(text).textSelection(.enabled)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(12)
        .background(.fill.tertiary, in: .rect(cornerRadius: 12))
        .accessibilityIdentifier("draft.text")
    }

    private var editor: some View {
        VStack(spacing: 10) {
            TextEditor(text: $buffer)
                .scrollContentBackground(.hidden)
                .frame(minHeight: 160)
                .padding(8)
                .background(.fill.tertiary, in: .rect(cornerRadius: 12))
                .accessibilityLabel("초안 수정")
                .accessibilityIdentifier("draft.editor")
            HStack(spacing: 8) {
                secondaryButton("취소", identifier: "draft.cancel") {
                    isEditing = false
                    errorMessage = nil
                }
                primaryButton("저장", identifier: "draft.save") {
                    run {
                        try await actions.save(buffer, editRevision)
                        isEditing = false
                    }
                }
            }
            .disabled(isDisabled)
        }
    }

    private var pendingActions: some View {
        VStack(alignment: .leading, spacing: 8) {
            primaryButton("승인하기", identifier: "draft.approve") {
                run {
                    guard !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
                        throw ReplyError.emptyDraft
                    }
                    try await actions.decide(.approve, revision)
                }
            }
            HStack(spacing: 8) {
                secondaryButton("수정", identifier: "draft.edit") { beginEditing(with: text) }
                secondaryButton(isRewriting ? "쓰는 중" : "다시 쓰기", identifier: "draft.rewrite") { rewrite() }
                Button(role: .destructive) {
                    run { try await actions.decide(.reject, revision) }
                } label: {
                    Text("반려")
                        .font(.subheadline.weight(.semibold))
                        .frame(maxWidth: .infinity, minHeight: 30)
                }
                .buttonStyle(.bordered)
                .accessibilityIdentifier("draft.reject")
            }
            hint(afterApproval)
        }
        .disabled(isDisabled)
    }

    private var decidedActions: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 10) {
                Label {
                    Text(status == .approved ? "승인했어요" : "반려했어요").foregroundStyle(.primary)
                } icon: {
                    Image(systemName: status == .approved ? "checkmark.circle.fill" : "xmark.circle")
                        .foregroundStyle(status == .approved ? AnyShapeStyle(.green) : AnyShapeStyle(.secondary))
                }
                .font(.subheadline.weight(.medium))
                Spacer(minLength: 8)
                if canReopen {
                    Button {
                        run { try await actions.reopen(revision) }
                    } label: {
                        Label("되돌리기", systemImage: "arrow.uturn.backward")
                            .font(.subheadline.weight(.semibold))
                    }
                    .buttonStyle(.bordered)
                    .disabled(isDisabled)
                    .accessibilityIdentifier("draft.reopen")
                }
            }
            if status == .approved {
                hint(afterApproval)
            }
        }
    }

    private func hint(_ text: String) -> some View {
        PhraseText(text: text)
            .font(.footnote)
            .foregroundStyle(.secondary)
    }

    private func primaryButton(_ title: String, identifier: String, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Text(title)
                .foregroundStyle(Color(.systemBackground))
                .font(.subheadline.weight(.semibold))
                .frame(maxWidth: .infinity, minHeight: 30)
        }
        .buttonStyle(.borderedProminent)
        .accessibilityIdentifier(identifier)
    }

    private func secondaryButton(_ title: String, identifier: String, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Text(title)
                .font(.subheadline.weight(.semibold))
                .frame(maxWidth: .infinity, minHeight: 30)
        }
        .buttonStyle(.bordered)
        .accessibilityIdentifier(identifier)
    }

    private func beginEditing(with value: String) {
        buffer = value
        editRevision = revision
        errorMessage = nil
        isEditing = true
    }

    // Rewritten text opens as an unsaved edit, so it never replaces the stored draft by itself.
    private func rewrite() {
        isRewriting = true
        Task {
            defer { isRewriting = false }
            do {
                beginEditing(with: try await actions.rewrite())
            } catch {
                show(error)
            }
        }
    }

    private func run(_ operation: @escaping @MainActor () async throws -> Void) {
        isSubmitting = true
        Task {
            defer { isSubmitting = false }
            do {
                try await operation()
                errorMessage = nil
            } catch {
                show(error)
            }
        }
    }

    private func show(_ error: Error) {
        errorMessage = error.localizedDescription
        if (error as? RoundupAPIError)?.isConflict == true { app.dataDidChange() }
    }
}

struct AssistantDraftDetailView: View {
    let kind: DraftKind
    let id: String
    @State private var loader = Loader<AssistantDraftDetail>()
    @Environment(AppModel.self) private var app

    var body: some View {
        LoadableContent(loader: loader, retry: load) { draft in
            List {
                CardSection("내용") {
                    VStack(alignment: .leading, spacing: 4) {
                        Text(keepingWords: draft.title).font(.headline)
                        ForEach(draft.lines, id: \.self) { line in
                            PhraseText(text: line)
                                .font(.subheadline)
                                .foregroundStyle(.secondary)
                        }
                    }
                    .padding(.vertical, 4)
                }
                CardSection("초안 검토", footer: "비서가 틀릴 수 있어요. 내용을 확인해 주세요.") {
                    card(draft)
                }
            }
            .cardList()
            .refreshable { await load() }
            .navigationTitle(draft.title)
        }
        .navigationBarTitleDisplayMode(.inline)
        .task(id: app.dataVersion) { await load() }
    }

    private func load() async {
        let (kind, id) = (kind, id)
        await loader.load { try await RoundupAPI.assistantDraft(kind: kind, id: id) }
    }

    private func card(_ draft: AssistantDraftDetail) -> some View {
        let (kind, id) = (kind, id)
        return AssistantDraftCard(
            text: draft.text, status: draft.status, revision: draft.revision, canReopen: draft.canReopen,
            afterApproval: draft.afterApproval, isOwnerEdited: app.ownerEditedDraftIDs.contains(id), isLocked: false,
            actions: DraftCardActions(
                save: { text, revision in
                    try await RoundupAPI.saveAssistantDraft(kind: kind, id: id, text: text, revision: revision)
                    app.markDraftEdited(id)
                    app.dataDidChange()
                },
                decide: { decision, revision in
                    let value = InquiryDecision(
                        decision: decision, draft: InquiryDraft(draft: draft.text, expectedRevision: revision))
                    try await RoundupAPI.decideAssistantDraft(kind: kind, id: id, decision: value)
                    app.dataDidChange()
                },
                reopen: { revision in
                    try await RoundupAPI.reopenAssistantDraft(kind: kind, id: id, revision: revision)
                    app.dataDidChange()
                },
                rewrite: {
                    try await RoundupAPI.ask(question: "아래 글을 같은 내용으로 다시 써 줘. 다시 쓴 글만 답해 줘.\n\n\(draft.text)")
                }
            )
        )
    }
}
