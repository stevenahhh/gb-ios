import SwiftUI
import RoundupCore

struct InquiryDetailView: View {
    let id: String
    @Environment(DemoStore.self) private var store
    @State private var errorMessage: String?
    @State private var isGenerating = false
    @State private var draft = ""
    @State private var editorRevision: Int?
    @State private var savedDraft = ""

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
        .navigationTitle("문의 답변")
        .navigationBarTitleDisplayMode(.inline)
        .onChange(of: store.inquiry(id: id)?.revision, initial: true) {
            if let inquiry = store.inquiry(id: id), editorRevision == nil || draft == savedDraft {
                draft = inquiry.draft
                savedDraft = inquiry.draft
                editorRevision = inquiry.revision
            }
        }
    }

    private func detail(_ inquiry: Inquiry) -> some View {
        List {
            Section("손님 문의") {
                VStack(alignment: .leading, spacing: 6) {
                    StatusBadge(inquiry.status.badge)
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

            Section {
                ForEach(inquiry.facts, id: \.self) { fact in
                    Label(fact, systemImage: "doc.text")
                }
            } header: {
                Text("답변 근거")
            } footer: {
                Text("공방에 등록해 둔 안내예요. AI 초안은 이 안내만 근거로 HyperCLOVA X가 써요.")
            }

            Section {
                if inquiry.status == .pending {
                    TextEditor(text: $draft)
                        .scrollContentBackground(.hidden)
                        .frame(minHeight: 160)
                        .accessibilityLabel("답변 초안 편집")
                        .accessibilityIdentifier("inquiry.draft")
                        .disabled(isGenerating || store.isInquiryBusy || store.requiresInquiryReload)
                    Button("초안 저장") {
                        Task { await saveDraft() }
                    }
                    .buttonStyle(.bordered)
                    .controlSize(.large)
                    .disabled(isGenerating || store.isInquiryBusy || store.requiresInquiryReload || draft == inquiry.draft)
                    .accessibilityIdentifier("inquiry.save")
                    Text(draft == inquiry.draft ? "저장된 초안이에요." : "아직 저장하지 않은 수정 내용이 있어요. 초안 저장 또는 승인을 눌러 주세요.")
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                    if editorRevision != inquiry.revision {
                        Button("서버 초안으로 되돌리기") {
                            draft = inquiry.draft
                            savedDraft = inquiry.draft
                            editorRevision = inquiry.revision
                            errorMessage = nil
                        }
                        .buttonStyle(.bordered)
                        .controlSize(.large)
                    }
                    Button {
                        Task { await generateDraft(for: inquiry) }
                    } label: {
                        if isGenerating {
                            ProgressView("초안을 쓰는 중이에요")
                        } else {
                            Label("AI로 초안 다시 쓰기", systemImage: "sparkles")
                        }
                    }
                    .disabled(isGenerating || store.isInquiryBusy || store.requiresInquiryReload)
                    .accessibilityIdentifier("inquiry.generate")
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
                    decisionButtons
                        .disabled(isGenerating || store.isInquiryBusy || store.requiresInquiryReload)
                    if store.isSavingInquiry {
                        ProgressView("서버에 저장하는 중이에요")
                    }
                } else {
                    if inquiry.draft.isEmpty {
                        Text("초안을 비운 채 반려했어요.")
                            .foregroundStyle(.secondary)
                    } else {
                        Text(inquiry.draft)
                            .textSelection(.enabled)
                    }
                    Label(inquiry.status == .approved ? "답변을 승인했어요." : "초안을 반려했어요.",
                          systemImage: inquiry.status == .approved ? "checkmark.circle.fill" : "xmark.circle")
                        .foregroundStyle(.secondary)
                }
            } header: {
                Text("답변 초안")
            } footer: {
                if inquiry.status == .pending {
                    Text("고쳐 쓴 뒤 승인하거나 반려해 주세요. 승인해도 아직 손님께 발송되지는 않아요.")
                } else {
                    Text("처리한 답변은 다시 바꿀 수 없어요.")
                }
            }
        }
        .listStyle(.insetGrouped)
        .sensoryFeedback(.success, trigger: inquiry.status)
    }

    private var decisionButtons: some View {
        VStack(spacing: 8) {
            Button {
                decide(.approve)
            } label: {
                Text("답변 승인")
                    .foregroundStyle(Color(.systemBackground))
                    .font(.subheadline.weight(.semibold))
                    .frame(maxWidth: .infinity, minHeight: 30)
            }
            .buttonStyle(.borderedProminent)
            .controlSize(.large)
            .accessibilityIdentifier("inquiry.approve")

            Button(role: .destructive) {
                decide(.reject)
            } label: {
                Text("초안 반려")
                    .font(.subheadline.weight(.semibold))
                    .frame(maxWidth: .infinity, minHeight: 30)
            }
            .buttonStyle(.bordered)
            .controlSize(.large)
            .accessibilityIdentifier("inquiry.reject")
        }
        .padding(.vertical, 4)
    }

    private func generateDraft(for inquiry: Inquiry) async {
        isGenerating = true
        defer { isGenerating = false }
        do {
            let text = try await RoundupAPI.draft(customer: inquiry.customer, subject: inquiry.subject,
                                                  question: inquiry.question, facts: inquiry.facts)
            // Generated text is an unsaved edit, and never overwrites an in-flight decision.
            draft = text
            errorMessage = nil
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    private func saveDraft() async {
        guard let editorRevision else { return }
        do {
            try await store.saveDraft(id: id, draft: InquiryDraft(draft: draft, expectedRevision: editorRevision))
            savedDraft = draft
            self.editorRevision = store.inquiry(id: id)?.revision
            errorMessage = nil
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    private func decide(_ decision: ReplyDecision) {
        guard let editorRevision else { return }
        let value = InquiryDecision(decision: decision, draft: InquiryDraft(draft: draft, expectedRevision: editorRevision))
        Task {
            do {
                try await store.decide(id: id, decision: value)
                errorMessage = nil
            } catch {
                errorMessage = error.localizedDescription
            }
        }
    }
}

#Preview {
    NavigationStack {
        InquiryDetailView(id: "inquiry-clay")
    }
    .environment(DemoStore())
}
