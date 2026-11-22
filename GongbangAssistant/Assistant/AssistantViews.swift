import SwiftUI

struct AssistantAccessory: View {
    let openText: () -> Void
    let openVoice: () -> Void

    var body: some View {
        HStack(spacing: 0) {
            Button(action: openText) {
                HStack(spacing: 10) {
                    AssistantFace(size: .composer)
                        .accessibilityHidden(true)
                    Text("글을 입력하세요")
                        .foregroundStyle(Color.secondaryText)
                        .lineLimit(1)
                    Spacer(minLength: 0)
                }
                .padding(.leading, 16)
                .frame(maxHeight: .infinity)
                .contentShape(.rect)
            }
            .buttonStyle(.plain)
            .accessibilityLabel("글을 입력하세요")
            .accessibilityIdentifier("assistant.accessory")

            Button(action: openVoice) {
                Image(systemName: "mic.fill")
                    .frame(width: 44, height: 44)
                    .contentShape(.rect)
            }
            .buttonStyle(.plain)
            .foregroundStyle(.primary)
            .padding(.trailing, 8)
            .accessibilityLabel("말로 물어보기")
            .accessibilityIdentifier("assistant.voice")
        }
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

    private let suggestions = ["오늘 발송할 주문 알려줘", "예약금 안 낸 손님 알려줘", "주말 클래스 홍보 글 써 줘"]

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
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("닫기", systemImage: "xmark") {
                        if trimmed(message).isEmpty {
                            dismiss()
                        } else {
                            isConfirmingDiscard = true
                        }
                    }
                    .confirmationDialog("작성 중인 질문을 버릴까요?", isPresented: $isConfirmingDiscard, titleVisibility: .visible) {
                        Button("버리기", role: .destructive) {
                            dismiss()
                        }
                        Button("계속 쓰기", role: .cancel) {}
                    }
                }
                ToolbarItemGroup(placement: .topBarTrailing) {
                    NavigationLink {
                        AssistantHistoryView()
                    } label: {
                        Label("지난 대화", systemImage: "clock.arrow.circlepath")
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
    }

    private var welcome: some View {
        // Top-aligned so the suggestions sit above the composer when the sheet opens at half height.
        VStack(alignment: .leading, spacing: 10) {
            AssistantFace(size: .sheet)
            Text("무엇을 맡기실래요?")
                .font(.title3.weight(.semibold))
                .accessibilityAddTraits(.isHeader)
            Text("예약, 주문, 배송, 홍보를 물어보세요.")
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
        return (try? AttributedString(markdown: text, options: options)) ?? AttributedString(text)
    }

    private func send(_ text: String) {
        let value = trimmed(text)
        // One question at a time: while an answer is on its way the draft waits in the field.
        guard !value.isEmpty, !store.isAnswering else { return }
        message = ""
        store.ask(value)
    }
}
