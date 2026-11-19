import SwiftUI
import RoundupCore

struct InquiryDetailView: View {
    let id: String
    @Environment(InquiryStore.self) private var store
    @Environment(AppModel.self) private var app

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
    }

    private func detail(_ inquiry: Inquiry) -> some View {
        List {
            CardSection("손님 문의") {
                VStack(alignment: .leading, spacing: 4) {
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

            CardSection("초안 검토", footer: "비서가 틀릴 수 있어요. 내용을 확인해 주세요.") {
                card(inquiry)
                if store.isSavingInquiry {
                    ProgressView("서버에 저장하는 중이에요")
                }
            }

            CardSection("답변 근거", footer: "공방에 등록해 둔 안내만 근거로 비서가 썼어요.") {
                ForEach(inquiry.facts, id: \.self) { Text($0) }
            }
        }
        .cardList()
    }

    private func card(_ inquiry: Inquiry) -> some View {
        let id = id
        return AssistantDraftCard(
            text: inquiry.draft, status: inquiry.status, revision: inquiry.revision,
            canReopen: inquiry.canReopen, afterApproval: "승인해도 아직 손님께 발송되지는 않아요.",
            isOwnerEdited: app.ownerEditedDraftIDs.contains(id),
            isLocked: store.isInquiryBusy || store.requiresInquiryReload,
            actions: DraftCardActions(
                save: { text, revision in
                    try await store.saveDraft(id: id, draft: InquiryDraft(draft: text, expectedRevision: revision))
                    app.markDraftEdited(id)
                    app.dataDidChange()
                },
                decide: { decision, revision in
                    let draft = InquiryDraft(draft: inquiry.draft, expectedRevision: revision)
                    try await store.decide(id: id, decision: InquiryDecision(decision: decision, draft: draft))
                    app.dataDidChange()
                },
                reopen: { revision in
                    try await store.reopen(id: id, request: InquiryReopen(expectedRevision: revision))
                    app.dataDidChange()
                },
                rewrite: {
                    try await RoundupAPI.draft(customer: inquiry.customer, subject: inquiry.subject,
                                               question: inquiry.question, facts: inquiry.facts)
                }
            )
        )
    }
}
