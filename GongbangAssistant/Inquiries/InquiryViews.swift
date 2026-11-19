import SwiftUI
import RoundupCore

extension Inquiry {
    var badge: Status {
        status == .approved ? Status(text: "답변 완료", tone: .done) : Status(text: "답변 대기", tone: .attention)
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
                    Text(keepingWords: "목록으로 돌아가 다시 골라 주세요.")
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
    }

    private func detail(_ inquiry: Inquiry) -> some View {
        List {
            CardSection("손님 문의") {
                VStack(alignment: .leading, spacing: 4) {
                    StatusBadge(inquiry.badge)
                    Text(keepingWords: inquiry.subject)
                        .font(.headline)
                    Text(inquiry.customer)
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                }
                .padding(.vertical, 4)
                Text(inquiry.question)
                    .textSelection(.enabled)
            }

            CardSection {
                TextEditor(text: $draft)
                    .scrollContentBackground(.hidden)
                    .frame(minHeight: 160)
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
                        Text(keepingWords: errorMessage)
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
            } header: {
                Text("답변 작성")
            } footer: {
                Text("비서가 틀릴 수 있어요. 답변 완료를 눌러도 손님께 자동으로 보내지지는 않아요. 고친 내용은 화면을 나갈 때 저장해요.")
            }

            CardSection("답변 근거", footer: "공방에 등록해 둔 안내만 근거로 비서가 써요.") {
                ForEach(inquiry.facts, id: \.self) { Text($0) }
            }
        }
        .cardList()
        .sensoryFeedback(.success, trigger: completionCount)
    }

    @ViewBuilder
    private func replyActions(_ inquiry: Inquiry) -> some View {
        Button {
            Task { await generateDraft(for: inquiry) }
        } label: {
            Group {
                if isGenerating {
                    ProgressView()
                } else {
                    HStack(spacing: 4) {
                        Image(systemName: "sparkles")
                        Text("비서로 다시 쓰기")
                            .lineLimit(1)
                            .fixedSize()
                    }
                }
            }
            .font(.subheadline.weight(.semibold))
            .frame(maxWidth: .infinity, minHeight: 30)
        }
        .buttonStyle(.bordered)
        .controlSize(.large)
        .disabled(isEditingLocked)
        .accessibilityIdentifier("inquiry.generate")

        Button(action: complete) {
            Group {
                if store.isSavingInquiry {
                    ProgressView()
                } else {
                    Text("답변 완료")
                        .foregroundStyle(Color(.systemBackground))
                }
            }
            .font(.subheadline.weight(.semibold))
            .frame(maxWidth: .infinity, minHeight: 30)
        }
        .buttonStyle(.borderedProminent)
        .controlSize(.large)
        .disabled(isEditingLocked || isDraftBlank || (inquiry.status == .approved && draft == inquiry.draft))
        .accessibilityIdentifier("inquiry.complete")
    }

    private func loadEditorFromStore() {
        guard let inquiry = store.inquiry(id: id) else { return }
        draft = inquiry.draft
        savedDraft = inquiry.draft
        editorRevision = inquiry.revision
    }

    private func generateDraft(for inquiry: Inquiry) async {
        isGenerating = true
        defer { isGenerating = false }
        do {
            // Generated text is an unsaved edit, and never overwrites an in-flight completion.
            draft = try await RoundupAPI.draft(customer: inquiry.customer, subject: inquiry.subject,
                                               question: inquiry.question, facts: inquiry.facts)
            errorMessage = nil
        } catch {
            errorMessage = error.localizedDescription
        }
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
        let value = InquiryDecision(decision: .approve, draft: InquiryDraft(draft: draft, expectedRevision: editorRevision))
        Task {
            do {
                try await store.decide(id: id, decision: value)
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
