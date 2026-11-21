import SwiftUI

private struct ChatTurn: Identifiable {
    enum Role { case owner, assistant, failure }
    let id = UUID()
    let role: Role
    let text: String
    var items: [WorkItem] = []
    /// True until the answer has been revealed once.
    var isFresh = false

    /// Failed turns stay on screen but never reach the model.
    var apiTurn: RoundupAPI.ChatTurn? {
        switch role {
        case .owner: RoundupAPI.ChatTurn(role: .owner, text: text)
        case .assistant: RoundupAPI.ChatTurn(role: .assistant, text: text)
        case .failure: nil
        }
    }
}

struct AssistantAccessory: View {
    let openText: () -> Void
    let openVoice: () -> Void

    var body: some View {
        HStack(spacing: 0) {
            Button(action: openText) {
                HStack(spacing: 10) {
                    AssistantFace(size: .composer)
                        .accessibilityHidden(true)
                    Text("\(AssistantIdentity.name)에게 맡기기")
                        .foregroundStyle(Color.secondaryText)
                        .lineLimit(1)
                    Spacer(minLength: 0)
                }
                .padding(.leading, 16)
                .frame(maxHeight: .infinity)
                .contentShape(.rect)
            }
            .buttonStyle(.plain)
            .accessibilityLabel("\(AssistantIdentity.name)에게 맡기기")
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
    @State private var sent: [ChatTurn] = []
    @State private var isAnswering = false
    @State private var isConfirmingDiscard = false
    @State private var recorder = VoiceRecorder()
    @State private var isTranscribing = false
    @State private var voiceError: String?
    @FocusState private var isFieldFocused: Bool
    @Environment(\.dynamicTypeSize) private var dynamicTypeSize

    private let suggestions = ["오늘 발송할 주문 알려줘", "예약금 안 낸 손님 알려줘", "주말 클래스 홍보 글 써 줘"]

    var body: some View {
        NavigationStack {
            Group {
                if sent.isEmpty {
                    ScrollView {
                        welcome
                            .padding(.top, 8)
                    }
                    .scrollBounceBehavior(.basedOnSize)
                } else {
                    conversation
                }
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
            }
            .safeAreaInset(edge: .bottom) {
                composer
            }
        }
        .interactiveDismissDisabled(!trimmed(message).isEmpty)
        // Half height leaves no room for the suggestions at accessibility sizes, so those open full height.
        .presentationDetents(dynamicTypeSize.isAccessibilitySize ? [.large] : [.medium, .large])
        .presentationDragIndicator(.visible)
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
            Text(launch == .voice ? "마이크 버튼을 누르고 말한 뒤 다시 누르면 글자로 바꿔 드려요." : "예약, 주문, 배송, 홍보를 물어보세요.")
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

    private var conversation: some View {
        ScrollViewReader { proxy in
            List {
                ForEach($sent) { $turn in
                    switch turn.role {
                    case .owner:
                        HStack {
                            Spacer(minLength: 40)
                            Text(turn.text)
                                .padding(.horizontal, 14)
                                .padding(.vertical, 10)
                                .background(.tint.opacity(0.15), in: .rect(cornerRadius: 16))
                        }
                        .listRowSeparator(.hidden)
                    case .assistant:
                        VStack(alignment: .leading, spacing: 10) {
                            Label {
                                GeneratedText(Self.rendered(turn.text), isFresh: $turn.isFresh)
                                    .textSelection(.enabled)
                            } icon: {
                                AssistantFace(size: .card)
                            }
                            .labelStyle(TopAlignedIconLabelStyle())
                            // The items the answer names, each with its one next action. They stay hidden until the text has settled.
                            ForEach(turn.items) { item in
                                WorkCard(item: item, isPrimary: false)
                                    .padding(12)
                                    .background(.fill.quaternary, in: .rect(cornerRadius: 14))
                            }
                            .opacity(turn.isFresh ? 0 : 1)
                        }
                        .animation(.default, value: turn.isFresh)
                        .listRowSeparator(.hidden)
                    case .failure:
                        Label(turn.text, systemImage: "exclamationmark.circle.fill")
                            .foregroundStyle(.orange)
                            .listRowSeparator(.hidden)
                    }
                }
                if isAnswering {
                    GeneratingIndicator(label: "비서가 현황을 보고 있어요")
                        .font(.subheadline)
                        .listRowSeparator(.hidden)
                        .id(Self.waitingRow)
                }
            }
            .listStyle(.plain)
            // A List has no bottom anchor, so the waiting row and then the answer's first line are scrolled into view.
            .onChange(of: isAnswering) {
                withAnimation {
                    if isAnswering {
                        proxy.scrollTo(Self.waitingRow, anchor: .bottom)
                    } else if let last = sent.last {
                        proxy.scrollTo(last.id, anchor: .top)
                    }
                }
            }
        }
    }

    private static let waitingRow = "assistant.waiting"

    /// At accessibility sizes the field takes its own full-width row, so its text is not squeezed.
    private var composerLayout: AnyLayout {
        dynamicTypeSize.isAccessibilitySize
            ? AnyLayout(VStackLayout(alignment: .trailing, spacing: 8))
            : AnyLayout(HStackLayout(spacing: 8))
    }

    private var composer: some View {
        VStack(spacing: 6) {
            composerLayout {
                TextField(isTranscribing ? "받아쓰는 중이에요" : "무엇이든 물어보세요", text: $message)
                    .font(.body)
                    .textFieldStyle(.plain)
                    .focused($isFieldFocused)
                    .submitLabel(.send)
                    .onSubmit { send(message) }
                    .padding(.horizontal, 16)
                    .frame(minHeight: 44)
                    .glassEffect(.regular, in: .capsule)
                HStack(spacing: 8) {
                    Button {
                        Task { await toggleRecording() }
                    } label: {
                        Label(isTranscribing ? "받아쓰는 중" : recorder.isRecording ? "녹음 끝내기" : "말로 입력",
                              systemImage: isTranscribing ? "waveform" : recorder.isRecording ? "stop.fill" : "mic.fill")
                            .labelStyle(.iconOnly)
                            .symbolEffect(.variableColor.iterative, options: .repeating, isActive: isTranscribing)
                            .symbolEffect(.breathe, options: .repeating, isActive: recorder.isRecording)
                            .contentTransition(.symbolEffect(.replace))
                    }
                    .buttonStyle(.glass)
                    .buttonBorderShape(.circle)
                    .controlSize(.large)
                    .tint(recorder.isRecording ? .red : nil)
                    .disabled(isTranscribing)
                    .accessibilityIdentifier("assistant.record")
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
            }
            if let voiceError {
                Label(voiceError, systemImage: "exclamationmark.circle.fill")
                    .font(.footnote)
                    .foregroundStyle(.orange)
            }
            // One line at every text size, so the suggestions above stay visible at half height.
            Text("비서가 틀릴 수 있어요")
                .font(.footnote)
                .foregroundStyle(Color.secondaryText)
                .lineLimit(1)
        }
        .padding()
        .background(.bar)
    }

    private func toggleRecording() async {
        voiceError = nil
        do {
            if recorder.isRecording {
                let wav = try recorder.stop()
                isTranscribing = true
                defer { isTranscribing = false }
                let text = try await RoundupAPI.transcribe(wav: wav)
                message = text.isEmpty ? message : text
                if text.isEmpty { voiceError = "말소리를 알아듣지 못했어요. 다시 말해 주세요." }
            } else {
                try await recorder.start()
            }
        } catch {
            voiceError = error.localizedDescription
        }
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
        guard !value.isEmpty else { return }
        let history = sent.compactMap(\.apiTurn)
        sent.append(ChatTurn(role: .owner, text: value))
        message = ""
        Task { await answer(value, history: history) }
    }

    private func answer(_ question: String, history: [RoundupAPI.ChatTurn]) async {
        isAnswering = true
        defer { isAnswering = false }
        do {
            let reply = try await RoundupAPI.ask(question: question, history: history)
            sent.append(ChatTurn(role: .assistant, text: reply.answer, items: reply.items, isFresh: true))
            AccessibilityNotification.Announcement(reply.answer).post()
        } catch {
            sent.append(ChatTurn(role: .failure, text: error.localizedDescription))
        }
    }
}

/// Keeps the assistant's face beside the first line of a long answer instead of its vertical middle.
private struct TopAlignedIconLabelStyle: LabelStyle {
    func makeBody(configuration: Configuration) -> some View {
        HStack(alignment: .firstTextBaseline, spacing: 10) {
            configuration.icon
                .alignmentGuide(.firstTextBaseline) { $0[VerticalAlignment.center] + 5 }
            configuration.title
        }
    }
}
