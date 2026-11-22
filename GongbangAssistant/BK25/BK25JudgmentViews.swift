#if BUILD_B
import RoundupCore
import SwiftUI

/// The questions that wait for the owner's one-line answer.
@MainActor
@Observable
final class BK25JudgmentInbox {
    static let shared = BK25JudgmentInbox()
    private(set) var items: [BK25Judgment] = []
    private(set) var loadFailed = false

    func load() async {
        do {
            items = try await BK25API.openJudgments()
            loadFailed = false
        } catch is CancellationError {
            return
        } catch {
            loadFailed = true
        }
    }
}

/// Today's 판단 필요 cards: the facts do not answer these customers, so the owner does, and the answer can become a rule.
struct BK25JudgmentSection: View {
    @State private var inbox = BK25JudgmentInbox.shared

    var body: some View {
        if !inbox.items.isEmpty || inbox.loadFailed {
            CardSection {
                ForEach(inbox.items) { BK25JudgmentRow(judgment: $0) }
                if inbox.loadFailed {
                    LabeledContent {
                        Button("다시 시도") { Task { await inbox.load() } }
                    } label: {
                        Text("판단 필요 목록을 불러오지 못했어요")
                            .foregroundStyle(Color.secondaryText)
                    }
                }
            } header: {
                Text("판단 필요 \(inbox.items.count)건")
                    .font(.headline)
                    .foregroundStyle(Color.primary)
                    .textCase(nil)
                    .accessibilityIdentifier("bk25.judgments.header")
            }
        }
    }
}

struct BK25JudgmentRow: View {
    let judgment: BK25Judgment
    @State private var isAnswering = false
    @Environment(InquiryStore.self) private var store
    @Environment(AppModel.self) private var app

    var body: some View {
        Button {
            isAnswering = true
        } label: {
            VStack(alignment: .leading, spacing: 4) {
                HStack(alignment: .firstTextBaseline, spacing: 6) {
                    Circle()
                        .fill(Color.pendingOrange)
                        .frame(width: 7, height: 7)
                        .accessibilityHidden(true)
                    Text(judgment.issue)
                        .font(.headline)
                }
                Text(verbatim: "\(judgment.customer) 님 · \(judgment.question.replacingOccurrences(of: "\n", with: " "))")
                    .font(.subheadline)
                    .foregroundStyle(Color.secondaryText)
                    .lineLimit(2)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .contentShape(.rect)
        }
        .buttonStyle(.plain)
        .padding(.vertical, 4)
        .accessibilityIdentifier("judgment.\(judgment.id)")
        .sheet(isPresented: $isAnswering) {
            BK25JudgmentSheet(judgment: judgment) { answer in
                await save(answer)
            }
        }
    }

    /// The reply written again is kept as the inquiry's draft, so it is there when the owner opens it.
    private func save(_ answer: BK25JudgmentAnswer) async {
        if let inquiry = store.inquiry(id: judgment.inquiryId), inquiry.status == .pending, !answer.draft.isEmpty {
            do {
                try await store.saveDraft(id: inquiry.id, draft: InquiryDraft(draft: answer.draft,
                                                                              expectedRevision: inquiry.revision))
            } catch {
                app.failureMessage = error.localizedDescription
            }
        }
        app.dataDidChange()
        app.showToast("답장 초안을 다시 썼어요")
    }
}

/// Answer a question in the owner's own words, see the sentence it becomes, and choose how far it reaches.
struct BK25JudgmentSheet: View {
    let judgment: BK25Judgment
    let onAnswered: (BK25JudgmentAnswer) async -> Void
    @State private var text = ""
    @State private var preview: BK25RulePreview?
    @State private var isPreviewFresh = false
    @State private var isWorking = false
    @State private var errorMessage: String?
    @Environment(\.dismiss) private var dismiss

    private var isAnswerBlank: Bool {
        text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }

    var body: some View {
        NavigationStack {
            List {
                CardSection {
                    VStack(alignment: .leading, spacing: 8) {
                        Label {
                            Text(judgment.issue)
                                .font(.title3.bold())
                        } icon: {
                            Image(systemName: "questionmark.circle")
                        }
                        Text(judgment.question)
                            .font(.subheadline)
                            .foregroundStyle(Color.secondaryText)
                            .textSelection(.enabled)
                    }
                    .padding(.vertical, 4)
                }
                CardSection("한 줄로 답해 주세요") {
                    BK25VoiceField(text: $text, prompt: "예: 6명부터 1인 3만 원")
                        .onChange(of: text) { preview = nil }
                    if let preview {
                        VStack(alignment: .leading, spacing: 6) {
                            Text("이 규칙을 다음 답장에도 쓸까요?")
                                .font(.subheadline.weight(.semibold))
                            GeneratedText(AttributedString(preview.ruleText), isFresh: $isPreviewFresh)
                                .font(.body)
                                .accessibilityIdentifier("bk25.rule.preview")
                            Text(preview.className.map { "\($0)에 쓰는 규칙" } ?? "공방 전체에 쓰는 규칙")
                                .font(.subheadline)
                                .foregroundStyle(Color.secondaryText)
                        }
                        .padding(.vertical, 4)
                    } else if isWorking {
                        GeneratingIndicator(label: "답을 규칙으로 다듬는 중이에요", showsFace: false)
                    } else {
                        Button("규칙 문장으로 보기") { Task { await previewRule() } }
                            .buttonStyle(.bordered)
                            .disabled(isAnswerBlank)
                            .accessibilityIdentifier("bk25.rule.show")
                    }
                    if let errorMessage {
                        Label(errorMessage, systemImage: "exclamationmark.circle")
                            .font(.subheadline)
                    }
                }
                if preview != nil {
                    CardSection {
                        Button {
                            Task { await answer(scope: .rule) }
                        } label: {
                            BusyLabel(title: "다음 답장에도 쓰기", isBusy: isWorking, isProminent: true)
                                .frame(maxWidth: .infinity, minHeight: 30)
                        }
                        .buttonStyle(.borderedProminent)
                        .controlSize(.large)
                        .accessibilityIdentifier("bk25.answer.rule")
                        Button {
                            Task { await answer(scope: .once) }
                        } label: {
                            Text("이번 답장에만 쓰기")
                                .font(.subheadline.weight(.semibold))
                                .frame(maxWidth: .infinity, minHeight: 30)
                        }
                        .buttonStyle(.bordered)
                        .controlSize(.large)
                        .accessibilityIdentifier("bk25.answer.once")
                    }
                    .disabled(isWorking)
                }
                CardSection {
                    Button("답하지 않고 닫기") { Task { await dismissJudgment() } }
                        .font(.subheadline)
                        .disabled(isWorking)
                        .accessibilityIdentifier("bk25.judgment.dismiss")
                } header: {
                    EmptyView()
                } footer: {
                    Text("닫으면 이 문의는 지금처럼 초안을 직접 써요.")
                }
            }
            .cardList()
            .scrollDismissesKeyboard(.immediately)
            .navigationTitle("판단 필요")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("닫기") { dismiss() }
                }
            }
            // A written answer must not vanish with one swipe.
            .interactiveDismissDisabled(!isAnswerBlank)
        }
        .presentationDetents([.medium, .large])
    }

    private func previewRule() async {
        // The keyboard would cover the choice between the two answers.
        UIApplication.shared.sendAction(#selector(UIResponder.resignFirstResponder), to: nil, from: nil, for: nil)
        await run {
            let shown = try await BK25API.previewRule(judgment.id, answer: text)
            preview = shown
            isPreviewFresh = true
        }
    }

    private func answer(scope: BK25Scope) async {
        await run {
            let answered = try await BK25API.answer(judgment.id, answer: text, scope: scope)
            await BK25JudgmentInbox.shared.load()
            await onAnswered(answered)
            dismiss()
        }
    }

    private func dismissJudgment() async {
        await run {
            _ = try await BK25API.dismiss(judgment.id)
            await BK25JudgmentInbox.shared.load()
            dismiss()
        }
    }

    /// A failed request keeps the sheet and the typed answer, so the owner can try again.
    private func run(_ operation: () async throws -> Void) async {
        isWorking = true
        errorMessage = nil
        defer { isWorking = false }
        do {
            try await operation()
        } catch is CancellationError {
            return
        } catch {
            errorMessage = error.localizedDescription
        }
    }
}
#endif
