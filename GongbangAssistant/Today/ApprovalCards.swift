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
    /// Who or where it is for, only as far as the server says.
    let detail: String?

    var id: String {
        switch source {
        case .inquiry(let inquiry): "inquiry.\(inquiry.id)"
        case .draft(let kind, let id): Self.id(kind, id)
        }
    }

    static func id(_ kind: DraftKind, _ id: String) -> String { "draft.\(kind.rawValue).\(id)" }

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

    /// What approving did not do.
    var approvedNote: String {
        switch source {
        case .inquiry: "승인했어요. 손님께 자동으로 보내지지는 않아요."
        case .draft(.content, _): "승인했어요. 자동으로 게시되지는 않아요."
        case .draft(.recommendation, _): "승인했어요. 자동으로 신청되거나 발송되지는 않아요."
        }
    }

    static func replies(_ inquiries: [Inquiry]) -> [ApprovalItem] {
        inquiries.filter { $0.status == .pending }.map {
            ApprovalItem(source: .inquiry($0), title: $0.subject,
                         detail: ["\($0.customer) 님", $0.channel].compactMap { $0 }.joined(separator: " · "))
        }
    }

    static func drafts(_ today: TodayScreenData) -> [ApprovalItem] {
        var seen = Set<String>()
        return (today.suggestions.items + today.channels.todos).compactMap { item in
            guard let draft = item.draft, draft.status == .pending, seen.insert(draft.id).inserted else { return nil }
            // A draft card's last line is its body; the line before it is a fact, such as where it goes.
            return ApprovalItem(source: .draft(draft.kind, draft.id), title: item.title,
                                detail: item.lines.dropLast().first)
        }
    }
}

/// What was approved on the 오늘 tab today, newest first. These rows stay with their next step.
@MainActor
@Observable
final class ApprovalDecisions {
    static let shared = ApprovalDecisions()

    private struct Entry {
        let item: ApprovalItem
        let revision: Int
        let day: String
    }

    private var entries: [Entry] = []

    func record(_ item: ApprovalItem, revision: Int) {
        forget(item.id)
        entries.insert(Entry(item: item, revision: revision, day: Date.now.dayKey), at: 0)
    }

    func forget(_ id: String) {
        entries.removeAll { $0.item.id == id }
    }

    func items(_ inquiries: [Inquiry]) -> [ApprovalItem] {
        let today = Date.now.dayKey
        return entries.filter { $0.day == today }.map(\.item).filter { revision(of: $0, inquiries: inquiries) != nil }
    }

    /// The revision an undo checks, or nil while the item waits. A completed reply stays editable, so its revision
    /// comes from the store, never from the moment it was completed.
    func revision(of item: ApprovalItem, inquiries: [Inquiry]) -> Int? {
        switch item.source {
        case .inquiry(let inquiry):
            inquiries.first { $0.id == inquiry.id && $0.status == .approved }?.revision
        case .draft:
            entries.first { $0.item.id == item.id }?.revision
        }
    }
}

/// One row of 확인해 주실 일, whatever it asks.
private enum AttentionItem: Identifiable {
    case approval(ApprovalItem)
    case carryOver(CarryOverQuestion)
    case k06(BK06AttentionItem)

    var id: String {
        switch self {
        case .approval(let item): item.id
        case .carryOver(let question): question.id
        case .k06(let item): item.id
        }
    }

    var title: String {
        switch self {
        case .approval(let item): item.title
        case .carryOver(let question): question.title
        case .k06(let item): item.title
        }
    }
}

/// The section's rows in order, without the ones the owner cleared.
@MainActor
private struct AttentionRows {
    private(set) var decided: [AttentionItem]
    private(set) var waiting: [AttentionItem]
    let hiddenCount: Int

    init(today: TodayScreenData, inquiries: [Inquiry]) {
        let now = Date.now
        let groups = today.tasks.groups
        let approved = ApprovalDecisions.shared.items(inquiries)
        let approvedIDs = Set(approved.map(\.id))
        let approvals = (ApprovalItem.replies(inquiries) + ApprovalItem.drafts(today))
            .filter { !approvedIDs.contains($0.id) }
        let k06 = BK06Inbox.shared.rows
        let isLate = { (item: BK06AttentionItem) in if case .late = item { true } else { false } }

        let allDecided = approved.map(AttentionItem.approval)
            + CarryOverQuestion.carried(groups, now: now).map(AttentionItem.carryOver)
        let allWaiting = CarryOverQuestion.collect(groups, now: now).map(AttentionItem.carryOver)
            + k06.filter(isLate).map(AttentionItem.k06)
            + approvals.map(AttentionItem.approval)
            + k06.filter { !isLate($0) }.map(AttentionItem.k06)

        let visibility = AttentionVisibility.shared
        decided = allDecided.filter { !visibility.isHidden($0.id) }
        waiting = allWaiting.filter { !visibility.isHidden($0.id) }
        hiddenCount = allDecided.count + allWaiting.count - decided.count - waiting.count
    }

    var all: [AttentionItem] { decided + waiting }

    /// Up to three waiting rows, under the latest decided ones that still offer their undo.
    var short: [AttentionItem] { Array(decided.prefix(3) + waiting.prefix(3)) }
}

/// The one number of things to confirm, for the section header and the greeting.
@MainActor
enum AttentionCount {
    static func value(today: TodayScreenData, inquiries: [Inquiry]) -> Int {
        AttentionRows(today: today, inquiries: inquiries).waiting.count
    }
}

/// "확인해 주실 일": drafts, unfinished work from earlier days, and K06 checks in one list, then the K06 tools.
struct AttentionSection: View {
    let today: TodayScreenData
    @State private var editing: ApprovalItem?
    @State private var showsAll = false
    @Environment(InquiryStore.self) private var store
    @Environment(AppModel.self) private var app

    init(today: TodayScreenData) {
        self.today = today
    }

    var body: some View {
        let rows = AttentionRows(today: today, inquiries: store.inquiries)
        let short = rows.short
        CardSection {
            ForEach(short.keeping(editing)) { AttentionItemRow(item: $0, editing: $editing) }
            if rows.waiting.isEmpty, BK06Inbox.shared.cards != nil, store.hasLoadedInquiries {
                AttentionEmptyLine()
            }
            // The row stays while its list is open, so approving down to three rows does not close the list.
            if rows.all.count > short.count || showsAll {
                Button {
                    showsAll = true
                } label: {
                    HStack {
                        Text("모두 보기")
                        Spacer(minLength: 8)
                        Image(systemName: "chevron.forward")
                            .font(.footnote.weight(.semibold))
                            .foregroundStyle(.tertiary)
                            .accessibilityHidden(true)
                    }
                    .contentShape(.rect)
                }
                .buttonStyle(.plain)
                .accessibilityIdentifier("approvals.all")
                .navigationDestination(isPresented: $showsAll) { ApprovalListView(today: today) }
            }
            AttentionRestoreRow(count: rows.hiddenCount)
            BK06ToolRows()
        } header: {
            HStack(alignment: .firstTextBaseline) {
                // `Color.primary` is the label color; `.primary` alone would be the header's gray.
                Text("확인해 주실 일 \(rows.waiting.count)건")
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
            .task(id: app.dataVersion) { await BK06Inbox.shared.load() }
        }
    }
}

/// Every row of 확인해 주실 일. It loads its own copy of the today screen, so a decision made here shows up here.
struct ApprovalListView: View {
    let today: TodayScreenData
    @State private var loader = Loader<TodayScreenData>()
    @State private var editing: ApprovalItem?
    @Environment(InquiryStore.self) private var store
    @Environment(AppModel.self) private var app

    var body: some View {
        let rows = AttentionRows(today: loader.value ?? today, inquiries: store.inquiries)
        List {
            CardSection {
                ForEach(rows.all.keeping(editing)) { AttentionItemRow(item: $0, editing: $editing) }
                if rows.waiting.isEmpty { AttentionEmptyLine() }
                AttentionRestoreRow(count: rows.hiddenCount)
            }
        }
        .cardList()
        .refreshable {
            await load()
            await store.loadInquiries()
        }
        .navigationTitle("확인해 주실 일")
        .navigationBarTitleDisplayMode(.inline)
        .task(id: app.dataVersion) { await load() }
    }

    private func load() async {
        await loader.load { try await RoundupAPI.today() }
        await BK06Inbox.shared.load()
    }
}

private extension [AttentionItem] {
    /// The row whose editor is open stays, so a decision made in the editor does not close it.
    func keeping(_ editing: ApprovalItem?) -> [AttentionItem] {
        guard let editing, !contains(where: { $0.id == editing.id }) else { return self }
        return [.approval(editing)] + self
    }
}

private struct AttentionEmptyLine: View {
    var body: some View {
        Text("지금은 확인할 일이 없어요")
            .foregroundStyle(Color.secondaryText)
    }
}

private struct AttentionRestoreRow: View {
    let count: Int

    var body: some View {
        if count > 0 {
            Button("숨긴 일 \(count)건 다시 보기") {
                withAnimation { AttentionVisibility.shared.restoreAll() }
            }
            .accessibilityIdentifier("attention.restore")
        }
    }
}

private struct AttentionItemRow: View {
    let item: AttentionItem
    @Binding var editing: ApprovalItem?
    @Environment(AppModel.self) private var app

    var body: some View {
        Group {
            switch item {
            case .approval(let approval): ApprovalRow(item: approval, editing: $editing)
            case .carryOver(let question): CarryOverRow(question: question)
            case .k06(let item): BK06AttentionRow(item: item)
            }
        }
        .listRowInsets(.vertical, 4)
        .swipeActions(edge: .trailing, allowsFullSwipe: true) {
            Button("숨기기", systemImage: "eye.slash", action: hide)
                .tint(.gray)
        }
    }

    private func hide() {
        let id = item.id
        withAnimation { AttentionVisibility.shared.hide(id) }
        app.showToast("‘\(item.title)’ 숨겼어요") {
            withAnimation { AttentionVisibility.shared.restore(id) }
        }
    }
}

/// Title, who it is for, and 승인 · 고치기; the text opens the full draft.
/// Once approved the row stays and offers only 되돌리기 and, where there is one, the place to send it from.
private struct ApprovalRow: View {
    let item: ApprovalItem
    @Binding var editing: ApprovalItem?
    @Environment(InquiryStore.self) private var store
    @Environment(AppModel.self) private var app

    private var isRunning: Bool { app.isRunning(item.id) }

    private var isEditing: Binding<Bool> {
        Binding(get: { editing?.id == item.id }, set: { if !$0 { editing = nil } })
    }

    var body: some View {
        let approvedRevision = ApprovalDecisions.shared.revision(of: item, inquiries: store.inquiries)
        VStack(alignment: .leading, spacing: 0) {
            AttentionRow(title: item.title, detail: item.detail, route: item.route, identifier: item.id) {
                if approvedRevision == nil {
                    AttentionButton(title: "승인", isProminent: true, isBusy: isRunning, action: approve)
                        .accessibilityLabel("승인, \(item.title)")
                        .accessibilityInputLabels(["승인"])
                        .accessibilityIdentifier("approval.approve.\(item.id)")
                    AttentionButton(title: "고치기") { editing = item }
                        .disabled(isRunning)
                        .accessibilityLabel("고치기, \(item.title)")
                        .accessibilityInputLabels(["고치기"])
                        .accessibilityIdentifier("approval.edit.\(item.id)")
                }
            }
            if let approvedRevision {
                Text(verbatim: item.approvedNote)
                    .font(.subheadline)
                    .foregroundStyle(Color.secondaryText)
                    .fixedSize(horizontal: false, vertical: true)
                ViewThatFits(in: .horizontal) {
                    HStack(spacing: 6) { nextSteps(approvedRevision) }
                    VStack(alignment: .leading, spacing: 0) { nextSteps(approvedRevision) }
                }
            }
        }
        .navigationDestination(isPresented: isEditing) { item.editor }
    }

    @ViewBuilder
    private func nextSteps(_ revision: Int) -> some View {
        AttentionButton(title: "되돌리기", isBusy: isRunning) { undo(revision: revision) }
            .accessibilityIdentifier("approval.undo.\(item.id)")
        if let share = item.share {
            Link(share.openLabel, destination: share.url)
                .buttonStyle(AttentionButtonStyle())
                .accessibilityIdentifier("draft.open")
        }
    }

    private func approve() {
        Task {
            await app.run(id: item.id) {
                switch item.source {
                case .inquiry(let inquiry):
                    try await BK25Approval.approve(inquiry, store: store)
                    ApprovalDecisions.shared.record(item, revision: inquiry.revision + 1)
                case .draft(let kind, let id):
                    let detail = try await RoundupAPI.assistantDraft(kind: kind, id: id)
                    let draft = InquiryDraft(draft: detail.text, expectedRevision: detail.revision)
                    try await RoundupAPI.decideAssistantDraft(kind: kind, id: id,
                                                             decision: InquiryDecision(decision: .approve, draft: draft))
                    ApprovalDecisions.shared.record(item, revision: detail.revision + 1)
                }
            }
        }
    }

    private func undo(revision: Int) {
        Task {
            let undone = await app.run(id: item.id) {
                switch item.source {
                case .inquiry(let inquiry):
                    try await store.undoCompletion(id: inquiry.id, expectedRevision: revision)
                case .draft(let kind, let id):
                    do {
                        try await RoundupAPI.reopenAssistantDraft(kind: kind, id: id, revision: revision)
                    } catch let error as RoundupAPIError where error.isConflict {
                        // It was decided again elsewhere; the reload says how it stands.
                        ApprovalDecisions.shared.forget(item.id)
                        throw error
                    }
                }
                ApprovalDecisions.shared.forget(item.id)
            }
            if !undone { app.dataDidChange() }
        }
    }
}
