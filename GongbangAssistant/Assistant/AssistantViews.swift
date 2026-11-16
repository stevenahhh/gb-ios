import SwiftUI

struct AssistantAccessory: View {
    let openText: () -> Void
    let openVoice: () -> Void

    var body: some View {
        HStack(spacing: 0) {
            Button(action: openText) {
                HStack(spacing: 10) {
                    Image(systemName: "sparkles")
                        .foregroundStyle(.tint)
                        .accessibilityHidden(true)
                    Text("비서에게 물어보세요")
                        .foregroundStyle(.secondary)
                        .lineLimit(1)
                    Spacer(minLength: 0)
                }
                .padding(.leading, 16)
                .frame(maxHeight: .infinity)
                .contentShape(.rect)
            }
            .buttonStyle(.plain)
            .accessibilityLabel("비서에게 물어보기")
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
    let launch: AssistantLaunch
    @Environment(\.dismiss) private var dismiss
    @State private var message = ""
    @State private var sent: [String] = []
    @State private var isConfirmingDiscard = false
    @FocusState private var isFieldFocused: Bool

    private let suggestions = ["오늘 발송할 주문 알려줘", "예약금 안 낸 손님 알려줘", "주말 클래스 홍보 글 써 줘"]

    var body: some View {
        NavigationStack {
            Group {
                if sent.isEmpty {
                    ScrollView {
                        welcome
                            .padding(.top, 24)
                    }
                    .scrollBounceBehavior(.basedOnSize)
                } else {
                    conversation
                }
            }
            .navigationTitle("비서")
            .navigationBarTitleDisplayMode(.inline)
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
            }
            .safeAreaInset(edge: .bottom) {
                composer
            }
        }
        .interactiveDismissDisabled(!trimmed(message).isEmpty)
        .presentationDetents([.medium, .large])
        .presentationDragIndicator(.visible)
        .task {
            isFieldFocused = true
        }
    }

    private var welcome: some View {
        ContentUnavailableView {
            Label("무엇을 도와드릴까요?", systemImage: "sparkles")
        } description: {
            Text(launch == .voice ? "키보드의 마이크 버튼을 누르고 말로 물어보세요." : "예약, 주문, 배송, 홍보를 물어보세요.")
        } actions: {
            VStack(spacing: 8) {
                ForEach(suggestions, id: \.self) { suggestion in
                    Button(suggestion) {
                        send(suggestion)
                    }
                    .buttonStyle(.bordered)
                    .controlSize(.large)
                }
            }
        }
    }

    private var conversation: some View {
        List {
            ForEach(Array(sent.enumerated()), id: \.offset) { _, text in
                HStack {
                    Spacer(minLength: 40)
                    Text(text)
                        .padding(.horizontal, 14)
                        .padding(.vertical, 10)
                        .background(.tint.opacity(0.15), in: .rect(cornerRadius: 16))
                }
                .listRowSeparator(.hidden)
            }
            Label("답변 기능은 아직 연결하지 않았어요.", systemImage: "info.circle")
                .foregroundStyle(.secondary)
                .listRowSeparator(.hidden)
        }
        .listStyle(.plain)
    }

    private var composer: some View {
        VStack(spacing: 6) {
            HStack(spacing: 8) {
                TextField("예: 오늘 발송할 주문 알려줘", text: $message)
                    .textFieldStyle(.plain)
                    .focused($isFieldFocused)
                    .submitLabel(.send)
                    .onSubmit { send(message) }
                    .padding(.horizontal, 16)
                    .frame(minHeight: 44)
                    .glassEffect(.regular, in: .capsule)
                Button {
                    send(message)
                } label: {
                    Label("보내기", systemImage: "arrow.up")
                        .labelStyle(.iconOnly)
                        .foregroundStyle(Color(.systemBackground))
                }
                .buttonStyle(.glassProminent)
                .buttonBorderShape(.circle)
                .controlSize(.large)
                .disabled(trimmed(message).isEmpty)
            }
            Text(keepingWords: "비서가 틀릴 수 있어요. 보내기 전에 내용을 확인해 주세요.")
                .font(.footnote)
                .foregroundStyle(.secondary)
        }
        .padding()
        .background(.bar)
    }

    private func trimmed(_ text: String) -> String {
        text.trimmingCharacters(in: .whitespacesAndNewlines)
    }

    private func send(_ text: String) {
        let value = trimmed(text)
        guard !value.isEmpty else { return }
        sent.append(value)
        message = ""
    }
}
