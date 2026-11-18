import SwiftUI
import RoundupCore

private struct ChatTurn: Identifiable {
    enum Role { case owner, assistant, failure }
    let id = UUID()
    let role: Role
    let text: String
}

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
    @Environment(DemoStore.self) private var store
    @State private var sent: [ChatTurn] = []
    @State private var isAnswering = false
    @State private var isConfirmingDiscard = false
    @State private var recorder = VoiceRecorder()
    @State private var isTranscribing = false
    @State private var voiceError: String?
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
            Text(launch == .voice ? "마이크 버튼을 누르고 말한 뒤 다시 누르면 글자로 바꿔 드려요." : "예약, 주문, 배송, 홍보를 물어보세요.")
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
            ForEach(sent) { turn in
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
                    Label {
                        Text(turn.text).textSelection(.enabled)
                    } icon: {
                        Image(systemName: "sparkles").foregroundStyle(.tint)
                    }
                    .listRowSeparator(.hidden)
                case .failure:
                    Label(turn.text, systemImage: "exclamationmark.circle.fill")
                        .foregroundStyle(.orange)
                        .listRowSeparator(.hidden)
                }
            }
            if isAnswering {
                ProgressView("비서가 현황을 보고 있어요")
                    .listRowSeparator(.hidden)
            }
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
                    Task { await toggleRecording() }
                } label: {
                    if isTranscribing {
                        ProgressView()
                    } else {
                        Label(recorder.isRecording ? "녹음 끝내기" : "말로 입력",
                              systemImage: recorder.isRecording ? "stop.fill" : "mic.fill")
                            .labelStyle(.iconOnly)
                    }
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
            if let voiceError {
                Label(voiceError, systemImage: "exclamationmark.circle.fill")
                    .font(.footnote)
                    .foregroundStyle(.orange)
            }
            Text(keepingWords: "비서가 틀릴 수 있어요. 보내기 전에 내용을 확인해 주세요.")
                .font(.footnote)
                .foregroundStyle(.secondary)
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

    private func send(_ text: String) {
        let value = trimmed(text)
        guard !value.isEmpty else { return }
        sent.append(ChatTurn(role: .owner, text: value))
        message = ""
        Task { await answer(value) }
    }

    private func answer(_ question: String) async {
        isAnswering = true
        defer { isAnswering = false }
        do {
            let reply = try await RoundupAPI.ask(question: question, context: workshopContext)
            sent.append(ChatTurn(role: .assistant, text: reply))
        } catch {
            sent.append(ChatTurn(role: .failure, text: error.localizedDescription))
        }
    }

    private var workshopContext: [String] {
        let time = Date.FormatStyle(date: .omitted, time: .shortened).locale(Locale(identifier: "ko_KR"))
        var lines = ["답변 대기 문의 \(store.pendingCount)건"]
        lines += store.pendingInquiries.map { "답변 대기 문의: \($0.customer) · \($0.subject) · \($0.question)" }
        lines += store.sessions(on: store.referenceDay).map {
            "오늘 수업: \($0.startsAt.formatted(time)) \($0.title) · 예약 \($0.bookedPeople)/\($0.capacity)명"
        }
        lines += SampleData.shipToday.map { "오늘 발송: \($0.title) · \($0.status?.text ?? "") · \($0.lines.joined(separator: " · "))" }
        lines += OperationArea.bookings.items.filter { $0.tag == "예약금 대기" }
            .map { "예약금 대기: \($0.title) · \($0.lines.joined(separator: " · ")) · \($0.deadline ?? "")" }
        return lines
    }
}
