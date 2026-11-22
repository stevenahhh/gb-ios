import RoundupCore
import SwiftUI

struct AssistantAccessory: View {
    let openText: () -> Void
    let openVoice: () -> Void

    var body: some View {
        HStack(spacing: 0) {
            Button(action: openText) {
                HStack(spacing: 10) {
                    Text("채팅하기")
                        .foregroundStyle(.primary)
                        .lineLimit(1)
                    Spacer(minLength: 0)
                }
                .padding(.leading, 16)
                .frame(maxHeight: .infinity)
                .contentShape(.rect)
            }
            .buttonStyle(.plain)
            .accessibilityLabel("채팅하기")
            .accessibilityIdentifier("assistant.accessory")

            Button(action: openVoice) {
                Image(systemName: "mic.fill")
                    .frame(width: 44, height: 44)
                    .contentShape(.rect)
            }
            .buttonStyle(.plain)
            .foregroundStyle(.primary)
            .padding(.trailing, 8)
            .accessibilityLabel("음성으로 질문하기")
            .accessibilityIdentifier("assistant.voice")
        }
        .tutorialAnchor(.assistantBar)
    }
}

struct AssistantSheet: View {
    @Environment(\.dismiss) private var dismiss
    @Environment(\.dynamicTypeSize) private var dynamicTypeSize
    @State private var message = ""
    /// When this sheet opened; the transcript treats later turns as live.
    @State private var openedAt = Date.now
    @State private var revealed: Set<ConversationStore.Turn.ID> = []
    @State private var isConfirmingDiscard = false
    @FocusState private var isFieldFocused: Bool
    @State private var composerFrame: CGRect = .zero
    private let store = ConversationStore.shared

    /// The newest answer asks for a decision, so its card must not sit under the keyboard.
    private var newestAnswerWaits: Bool {
        store.current?.turns.last?.agent?.proposals.contains {
            AgentCenter.shared.standing(of: $0, at: .now) == .open
        } ?? false
    }

    private let suggestions = ["오늘 택배 보낼 주문이 뭐야?", "예약금 아직 입금 안 한 사람 누구야?", "이번 주말 수업 홍보하는 글 하나 부탁해"]

    var body: some View {
        NavigationStack {
            Group {
                if let conversation = store.current {
                    AssistantTranscript(conversation: conversation, isAnswering: store.isAnswering,
                                        liveSince: openedAt, revealed: $revealed, retry: store.retry)
                        .id(conversation.id)
                } else {
                    ScrollView {
                        welcome
                            .padding(.top, 8)
                    }
                    .scrollBounceBehavior(.basedOnSize)
                }
            }
            .containerBackground(for: .navigation) {
                AssistantBackdrop(composerFrame: composerFrame)
            }
            .navigationTitle("비서")
            .navigationBarTitleDisplayMode(.inline)
            .appDestinations()
            .assistantAgent()
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("닫기", systemImage: "xmark") {
                        if trimmed(message).isEmpty {
                            dismiss()
                        } else {
                            isConfirmingDiscard = true
                        }
                    }
                    .confirmationDialog("쓰다 만 질문은 지울까요?", isPresented: $isConfirmingDiscard, titleVisibility: .visible) {
                        Button("지울게요", role: .destructive) {
                            dismiss()
                        }
                        Button("마저 쓸게요", role: .cancel) {}
                    }
                }
                ToolbarItemGroup(placement: .topBarTrailing) {
                    NavigationLink {
                        AssistantHistoryView()
                    } label: {
                        Label("이전 대화 목록", systemImage: "clock.arrow.circlepath")
                    }
                    .accessibilityIdentifier("assistant.history")
                    // The way back from a conversation to the start; the conversation stays in 지난 대화.
                    if store.current != nil {
                        Button("새 대화", systemImage: "square.and.pencil") {
                            store.startNew()
                        }
                        .accessibilityIdentifier("assistant.new")
                    }
                }
            }
            .safeAreaInset(edge: .bottom) {
                AssistantComposer(message: $message, isAnswering: store.isAnswering, isFocused: $isFieldFocused) {
                    send(message)
                }
                .onGeometryChange(for: CGRect.self) { $0.frame(in: .global) } action: { composerFrame = $0 }
            }
        }
        .interactiveDismissDisabled(!trimmed(message).isEmpty)
        // Half height leaves no room for the suggestions at accessibility sizes, so those open full height.
        .presentationDetents(dynamicTypeSize.isAccessibilitySize ? [.large] : [.medium, .large])
        .presentationDragIndicator(.visible)
        .onAppear {
            store.resume()
        }
        .task {
            isFieldFocused = true
        }
        .onChange(of: newestAnswerWaits) { _, waits in
            if waits { isFieldFocused = false }
        }
    }

    private var welcome: some View {
        // Top-aligned so the suggestions sit above the composer when the sheet opens at half height.
        VStack(alignment: .leading, spacing: 10) {
            Text("오늘은 어떤 일을 도와드릴까요?")
                .font(.title3.weight(.semibold))
                .accessibilityAddTraits(.isHeader)
            Text("오늘 들어온 주문이나 예약, 배송, 홍보 뭐든 편하게 말 걸어 보세요.")
                .font(.subheadline)
                .foregroundStyle(Color.secondaryText)
            ForEach(suggestions, id: \.self) { suggestion in
                Button {
                    send(suggestion)
                } label: {
                    Text(suggestion)
                        .frame(maxWidth: .infinity, alignment: .leading)
                }
                .buttonStyle(.bordered)
                .controlSize(.large)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(.horizontal)
    }

    private func trimmed(_ text: String) -> String {
        text.trimmingCharacters(in: .whitespacesAndNewlines)
    }

    /// Bold and lists render instead of showing raw ** marks; anything unparsable stays plain text.
    static func rendered(_ text: String) -> AttributedString {
        let options = AttributedString.MarkdownParsingOptions(interpretedSyntax: .inlineOnlyPreservingWhitespace)
        return (try? AttributedString(markdown: SpokenTurn.escapingMaskedNames(text), options: options)) ?? AttributedString(text)
    }

    private func send(_ text: String) {
        let value = trimmed(text)
        // One question at a time: while an answer is on its way the draft waits in the field.
        guard !value.isEmpty, !store.isAnswering else { return }
        message = ""
        store.ask(value)
    }
}
