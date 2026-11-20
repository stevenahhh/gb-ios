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

/// The card head: the assistant's face and who wrote this, in clay because it is the assistant's own mark.
private struct AssistantDraftLabel: View {
    let isReply: Bool

    var body: some View {
        HStack(spacing: 6) {
            AssistantFace(size: .card)
                .accessibilityHidden(true)
            Text(isReply ? "\(AssistantIdentity.name)가 쓴 답변" : "\(AssistantIdentity.name)가 쓴 글")
                .font(.system(size: 12, weight: .semibold))
                .foregroundStyle(Color.assistantAccent)
        }
    }
}

/// "비서 초안" and its status; stacked at accessibility sizes so neither squeezes to one letter per line.
private struct DraftHeader: View {
    let badge: Status?
    let isReply: Bool
    @Environment(\.dynamicTypeSize) private var dynamicTypeSize

    var body: some View {
        if dynamicTypeSize.isAccessibilitySize {
            VStack(alignment: .leading, spacing: 6) {
                AssistantDraftLabel(isReply: isReply)
                if let badge { StatusBadge(badge) }
            }
        } else {
            HStack {
                AssistantDraftLabel(isReply: isReply)
                Spacer(minLength: 8)
                if let badge { StatusBadge(badge) }
            }
        }
    }
}

struct AssistantDraftRow: View {
    let title: String
    let text: String
    /// Waiting drafts share one state, which the section title already says; only different states get a badge.
    let badge: Status?
    let isReply: Bool
    let route: AppRoute
    let identifier: String

    init(title: String, reference: DraftReference) {
        self.title = title
        text = reference.preview
        badge = reference.status == .pending ? nil : reference.status.badge
        isReply = false
        route = .draft(reference.kind, reference.id)
        identifier = "draft.\(reference.kind.rawValue).\(reference.id)"
    }

    init(inquiry: Inquiry) {
        title = inquiry.subject
        text = inquiry.draft
        badge = inquiry.status == .pending ? nil : inquiry.badge
        isReply = true
        route = .inquiry(inquiry.id)
        identifier = "inquiry.\(inquiry.id)"
    }

    var body: some View {
        NavigationLink(value: route) {
            VStack(alignment: .leading, spacing: 6) {
                DraftHeader(badge: badge, isReply: isReply)
                Text(keepingWords: title)
                    .font(.headline)
                Text(keepingWords: text.isEmpty ? "내용을 비운 초안이에요." : text)
                    .font(.subheadline)
                    .foregroundStyle(Color.secondaryText)
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

/// What the owner does by hand after approval or completion, while no channel is connected.
struct DraftShare {
    let copyLabel: String
    let openLabel: String
    let url: URL

    static let inquiry = DraftShare(copyLabel: "답변 복사하기", openLabel: "네이버 스마트스토어 열기",
                                    url: URL(string: "https://sell.smartstore.naver.com/")!)
    static let content = DraftShare(copyLabel: "글 복사하기", openLabel: "Instagram 열기",
                                    url: URL(string: "https://www.instagram.com/")!)
}

/// After approval with no connected channel: say so, copy the text, and open the channel to send it by hand.
struct DraftShareActions: View {
    let share: DraftShare
    let text: String
    @Environment(AppModel.self) private var app

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("채널이 아직 연결되지 않아 직접 보내야 해요.")
                .font(.footnote)
                .foregroundStyle(Color.secondaryText)
            Button {
                UIPasteboard.general.string = text
                app.showToast("복사했어요")
            } label: {
                Text(share.copyLabel)
                    .foregroundStyle(Color(.systemBackground))
                    .font(.subheadline.weight(.semibold))
                    .frame(maxWidth: .infinity, minHeight: 30)
            }
            .buttonStyle(.borderedProminent)
            .accessibilityIdentifier("draft.copy")
            Link(destination: share.url) {
                Text(share.openLabel)
                    .font(.subheadline.weight(.semibold))
                    .frame(maxWidth: .infinity, minHeight: 30)
            }
            .buttonStyle(.bordered)
            .accessibilityIdentifier("draft.open")
        }
    }
}

struct AssistantDraftCard: View {
    let text: String
    let status: ReplyStatus
    var share: DraftShare?
    /// Opened from 고치기 on an approval card: the editor is already open.
    var startsEditing = false
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
    /// The identifier of the button whose write is in flight.
    @State private var runningID: String?
    @State private var isBufferFresh = false
    @State private var errorMessage: String?
    @Environment(AppModel.self) private var app

    private var isDisabled: Bool { isLocked || isRewriting || runningID != nil }

    var body: some View {
        content
            .task {
                if startsEditing, status == .pending, !isEditing { beginEditing(with: text) }
            }
    }

    private var content: some View {
        VStack(alignment: .leading, spacing: 10) {
            DraftHeader(badge: status.badge, isReply: false)
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
                    .foregroundStyle(Color.secondaryText)
            } else {
                Text(text).textSelection(.enabled)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(12)
        .background(.fill.tertiary, in: .rect(cornerRadius: 12))
        // The text about to be replaced is dimmed while the assistant writes.
        .opacity(isRewriting ? 0.4 : 1)
        .animation(.default, value: isRewriting)
        .accessibilityIdentifier("draft.text")
    }

    private var editor: some View {
        VStack(spacing: 10) {
            KoreanTextEditor(text: $buffer, isFresh: $isBufferFresh)
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
                    run("draft.save") {
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
                run("draft.approve") {
                    guard !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
                        throw ReplyError.emptyDraft
                    }
                    try await actions.decide(.approve, revision)
                }
            }
            HStack(spacing: 8) {
                secondaryButton("수정", identifier: "draft.edit") { beginEditing(with: text) }
                Button(action: rewrite) {
                    Group {
                        if isRewriting {
                            GeneratingIndicator(label: "쓰는 중", showsFace: false)
                        } else {
                            Text("다시 쓰기")
                        }
                    }
                    .font(.subheadline.weight(.semibold))
                    .frame(maxWidth: .infinity, minHeight: 30)
                }
                .buttonStyle(.bordered)
                .accessibilityIdentifier("draft.rewrite")
                // No destructive red: a rejection can be undone.
                Button {
                    run("draft.reject") { try await actions.decide(.reject, revision) }
                } label: {
                    BusyLabel(title: "반려", isBusy: runningID == "draft.reject")
                        .foregroundStyle(.primary)
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
                        .foregroundStyle(Color.secondaryText)
                }
                .font(.subheadline.weight(.medium))
                Spacer(minLength: 8)
                if canReopen {
                    Button {
                        run("draft.reopen") { try await actions.reopen(revision) }
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
                if let share {
                    DraftShareActions(share: share, text: text)
                } else {
                    hint(afterApproval)
                }
            }
        }
    }

    private func hint(_ text: String) -> some View {
        PhraseText(text: text)
            .font(.footnote)
            .foregroundStyle(Color.secondaryText)
    }

    private func primaryButton(_ title: String, identifier: String, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            BusyLabel(title: title, isBusy: runningID == identifier, isProminent: true)
                .font(.subheadline.weight(.semibold))
                .frame(maxWidth: .infinity, minHeight: 30)
        }
        .buttonStyle(.borderedProminent)
        .accessibilityIdentifier(identifier)
    }

    private func secondaryButton(_ title: String, identifier: String, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            BusyLabel(title: title, isBusy: runningID == identifier)
                .font(.subheadline.weight(.semibold))
                .frame(maxWidth: .infinity, minHeight: 30)
        }
        .buttonStyle(.bordered)
        .accessibilityIdentifier(identifier)
    }

    private func beginEditing(with value: String, isFresh: Bool = false) {
        buffer = value
        isBufferFresh = isFresh
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
                beginEditing(with: try await actions.rewrite(), isFresh: true)
                AccessibilityNotification.Announcement("\(AssistantIdentity.name)가 다 썼어요. 내용을 확인해 주세요.").post()
            } catch {
                show(error)
            }
        }
    }

    private func run(_ identifier: String, _ operation: @escaping @MainActor () async throws -> Void) {
        runningID = identifier
        Task {
            defer { runningID = nil }
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
    var startsEditing = false
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
                                .foregroundStyle(Color.secondaryText)
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
            text: draft.text, status: draft.status, share: kind == .content ? .content : nil,
            startsEditing: startsEditing, revision: draft.revision, canReopen: draft.canReopen,
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
                    try await RoundupAPI.rewrite(kind: kind.rewriteKind, title: draft.title, text: draft.text)
                }
            )
        )
    }
}
