import SwiftUI
import RoundupCore

private enum RewriteStyle: String, CaseIterable, Identifiable {
    case shorter = "더 짧게"
    case friendlier = "더 친근하게"
    case politer = "더 정중하게"

    var id: Self { self }

    var instruction: String {
        switch self {
        case .shorter: "같은 내용을 핵심만 남겨 더 짧게 써 줘."
        case .friendlier: "같은 내용을 더 친근하고 따뜻한 말투로 바꿔 줘."
        case .politer: "같은 내용을 더 정중하고 격식 있는 말투로 바꿔 줘."
        }
    }
}

extension Inquiry {
    var badge: Status {
        status == .approved ? Status(text: "답변 준비됨", tone: .done) : Status(text: "답변 대기", tone: .attention)
    }
}

struct InquiryDetailView: View {
    let id: String
    @Environment(InquiryStore.self) private var store
    @Environment(AppModel.self) private var app
    @Environment(\.scenePhase) private var scenePhase
    @State private var errorMessage: String?
    @State private var isGenerating = false
    @State private var draft = ""
    @State private var editorRevision: Int?
    @State private var savedDraft = ""
    @State private var completionCount = 0
    @State private var isDraftFresh = false
    #if BUILD_B
    @State private var grounding = BK25Grounding()
    #endif

    private var isEditingLocked: Bool {
        isGenerating || store.isInquiryBusy || store.requiresInquiryReload
    }

    private var isDraftBlank: Bool {
        draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }

    var body: some View {
        Group {
            if let inquiry = store.inquiry(id: id) {
                detail(inquiry)
            } else {
                ContentUnavailableView {
                    Label("문의를 찾을 수 없어요", systemImage: "bubble.left")
                } description: {
                    Text(verbatim: "목록으로 돌아가 다시 골라 주세요.")
                        .foregroundStyle(Color.secondaryText)
                }
            }
        }
        .navigationTitle(store.inquiry(id: id)?.subject ?? "문의 답변")
        .navigationBarTitleDisplayMode(.inline)
        .onChange(of: store.inquiry(id: id)?.revision, initial: true) {
            if editorRevision == nil || draft == savedDraft {
                loadEditorFromStore()
            }
        }
        .onChange(of: scenePhase) { _, phase in
            if phase != .active { saveUnsavedEdit() }
        }
        .onDisappear(perform: saveUnsavedEdit)
        // This screen reads the inquiry store directly, so a failed load or save gets the shared connection line here.
        #if BUILD_B
        .task(id: id) { await grounding.load(id, draft: store.inquiry(id: id)?.draft ?? draft) }
        #endif
        .safeAreaInset(edge: .top) {
            if store.inquiryLoadError != nil || store.requiresInquiryReload {
                ConnectionNotice(retry: {}) { store.inquiryLoadError != nil }
            }
        }
    }

    private func detail(_ inquiry: Inquiry) -> some View {
        List {
            CardSection("손님 문의") {
                VStack(alignment: .leading, spacing: 4) {
                    StatusBadge(inquiry.badge)
                    Text(verbatim: inquiry.subject)
                        .font(.headline)
                    Text(inquiry.customer)
                        .font(.subheadline)
                        .foregroundStyle(Color.secondaryText)
                }
                .padding(.vertical, 4)
                Text(inquiry.question)
                    .textSelection(.enabled)
            }

            CardSection {
                KoreanTextEditor(text: $draft, isFresh: $isDraftFresh)
                    .frame(minHeight: 160)
                    // The reply about to be replaced is dimmed while the assistant writes.
                    .opacity(isGenerating ? 0.4 : 1)
                    .animation(.default, value: isGenerating)
                    .accessibilityLabel("답변 작성")
                    .accessibilityIdentifier("inquiry.draft")
                    .disabled(isEditingLocked)
                if editorRevision != inquiry.revision {
                    Button("서버 답변으로 되돌리기") {
                        loadEditorFromStore()
                        errorMessage = nil
                    }
                }
                if let errorMessage {
                    Label {
                        Text(verbatim: errorMessage)
                            .foregroundStyle(.primary)
                    } icon: {
                        Image(systemName: "exclamationmark.circle.fill")
                            .foregroundStyle(.orange)
                    }
                    .font(.subheadline.weight(.semibold))
                    .accessibilityIdentifier("inquiry.error")
                }
                ViewThatFits(in: .horizontal) {
                    HStack(spacing: 8) { replyActions(inquiry) }
                    VStack(spacing: 8) { replyActions(inquiry) }
                }
                // Hidden while edits are unsaved, so the owner never copies text that differs from the saved reply.
                if inquiry.status == .approved && draft == inquiry.draft {
                    DraftShareActions(share: .inquiry, text: inquiry.draft)
                }
            } header: {
                Text("답변 작성")
            } footer: {
                Text("비서가 틀릴 수 있어요. 답변 완료를 눌러도 손님께 자동으로 보내지지는 않아요. 고친 내용은 화면을 나갈 때 저장해요.")
            }

            #if BUILD_B
            BK25GroundingSection(grounding: grounding, inquiryID: id, draft: $draft, approve: complete,
                                 showDraft: show(generated:))
            #endif

            CardSection("답변 근거", footer: "공방에 등록해 둔 안내만 근거로 비서가 써요.") {
                ForEach(inquiry.facts, id: \.self) { Text($0) }
            }
        }
        .cardList()
        .sensoryFeedback(.success, trigger: completionCount)
    }

    @ViewBuilder
    private func replyActions(_ inquiry: Inquiry) -> some View {
        Menu {
            Button("새로 쓰기") {
                Task { await generateDraft(for: inquiry) }
            }
            ForEach(RewriteStyle.allCases) { style in
                Button(style.rawValue) {
                    Task { await rewrite(inquiry, style: style) }
                }
                .disabled(isDraftBlank)
            }
        } label: {
            Group {
                if isGenerating {
                    GeneratingIndicator(label: "쓰는 중이에요", showsFace: false)
                } else {
                    HStack(spacing: 6) {
                        AssistantFace(size: .card)
                            .accessibilityHidden(true)
                        Text("비서로 다시 쓰기")
                            .lineLimit(1)
                            .fixedSize()
                    }
                }
            }
            .font(.subheadline.weight(.semibold))
            .frame(maxWidth: .infinity, minHeight: 30)
        }
        .menuStyle(.button)
        .buttonStyle(.bordered)
        .controlSize(.large)
        .disabled(isEditingLocked)
        .accessibilityIdentifier("inquiry.generate")

        Button(action: complete) {
            BusyLabel(title: "답변 완료", isBusy: store.isSavingInquiry, isProminent: true)
                .font(.subheadline.weight(.semibold))
                .frame(maxWidth: .infinity, minHeight: 30)
        }
        .buttonStyle(.borderedProminent)
        .controlSize(.large)
        .disabled(isEditingLocked || isDraftBlank || (inquiry.status == .approved && draft == inquiry.draft))
        #if BUILD_B
        .disabled(grounding.blocksApproval(draft))
        #endif
        .accessibilityIdentifier("inquiry.complete")
    }

    private func loadEditorFromStore() {
        guard let inquiry = store.inquiry(id: id) else { return }
        // Server text is not something the assistant just wrote, so it never plays the reveal.
        isDraftFresh = false
        draft = inquiry.draft
        savedDraft = inquiry.draft
        editorRevision = inquiry.revision
    }

    private func generateDraft(for inquiry: Inquiry) async {
        isGenerating = true
        defer { isGenerating = false }
        do {
            #if BUILD_B
            if let written = try await grounding.generate(inquiry.id) { show(generated: written) }
            #else
            show(generated: try await RoundupAPI.draft(customer: inquiry.customer, subject: inquiry.subject,
                                                       question: inquiry.question, facts: inquiry.facts))
            #endif
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    private func rewrite(_ inquiry: Inquiry, style: RewriteStyle) async {
        isGenerating = true
        defer { isGenerating = false }
        do {
            show(generated: try await RoundupAPI.rewrite(kind: .inquiry, title: inquiry.subject, text: draft,
                                                         instruction: style.instruction))
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    /// Generated text is an unsaved edit, and never overwrites an in-flight completion.
    /// The editor reveals it once, and VoiceOver hears about it once.
    private func show(generated text: String) {
        draft = text
        isDraftFresh = true
        errorMessage = nil
        AccessibilityNotification.Announcement("\(AssistantIdentity.name)가 다 썼어요. 내용을 확인해 주세요.").post()
    }

    /// The owner has no save button, so edits persist when the screen or app is left.
    private func saveUnsavedEdit() {
        guard let inquiry = store.inquiry(id: id), let editorRevision, editorRevision == inquiry.revision,
              draft != inquiry.draft, !store.isInquiryBusy, !store.requiresInquiryReload,
              inquiry.status == .pending || !isDraftBlank else { return }
        let edit = InquiryDraft(draft: draft, expectedRevision: editorRevision)
        Task {
            do {
                try await store.saveDraft(id: id, draft: edit)
                // The owner may have kept typing while this save was in flight.
                savedDraft = edit.draft
                self.editorRevision = store.inquiry(id: id)?.revision
                app.dataDidChange()
            } catch {
                app.failureMessage = error.localizedDescription
            }
        }
    }

    private func complete() {
        guard let editorRevision else { return }
        Task {
            do {
                #if BUILD_B
                try await grounding.decide(id, draft: draft, expectedRevision: editorRevision)
                await store.loadInquiries()
                #else
                let value = InquiryDecision(decision: .approve, draft: InquiryDraft(draft: draft, expectedRevision: editorRevision))
                try await store.decide(id: id, decision: value)
                #endif
                loadEditorFromStore()
                errorMessage = nil
                completionCount += 1
                app.dataDidChange()
            } catch {
                errorMessage = error.localizedDescription
            }
        }
    }
}
