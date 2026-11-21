import SwiftUI

/// The assistant sheet's input row: the question field, dictation, and send, with the reminder under them.
struct AssistantComposer: View {
    @Binding var message: String
    /// An answer is on its way: the owner can keep typing, and sending waits for it.
    let isAnswering: Bool
    let isFocused: FocusState<Bool>.Binding
    let send: () -> Void
    @State private var recorder = VoiceRecorder()
    @State private var isTranscribing = false
    @State private var voiceError: String?
    @Environment(\.dynamicTypeSize) private var dynamicTypeSize

    /// At accessibility sizes the field takes its own full-width row, so its text is not squeezed.
    private var layout: AnyLayout {
        dynamicTypeSize.isAccessibilitySize
            ? AnyLayout(VStackLayout(alignment: .trailing, spacing: 8))
            : AnyLayout(HStackLayout(alignment: .bottom, spacing: 8))
    }

    private var canSend: Bool {
        !isAnswering && !message.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }

    var body: some View {
        VStack(spacing: 6) {
            layout {
                // A long or dictated question wraps up to five lines, so all of it can be read before sending.
                TextField(isTranscribing ? "받아쓰는 중이에요" : "무엇이든 물어보세요", text: $message, axis: .vertical)
                    .lineLimit(1...5)
                    .font(.body)
                    .textFieldStyle(.plain)
                    .focused(isFocused)
                    .submitLabel(.send)
                    .onSubmit(send)
                    .padding(.horizontal, 16)
                    .padding(.vertical, 11)
                    .frame(minHeight: 44)
                    // Radius 22 is a capsule at one line and a rounded box once the question wraps.
                    .glassEffect(.regular, in: .rect(cornerRadius: 22))
                    .accessibilityIdentifier("assistant.field")
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
                    Button(action: send) {
                        Label("보내기", systemImage: "arrow.up")
                            .labelStyle(.iconOnly)
                            .foregroundStyle(Color(.systemBackground))
                    }
                    .buttonStyle(.glassProminent)
                    .buttonBorderShape(.circle)
                    .controlSize(.large)
                    .disabled(!canSend)
                    .accessibilityIdentifier("assistant.send")
                }
            }
            if let voiceError {
                Label(voiceError, systemImage: "exclamationmark.circle")
                    .font(.footnote)
            }
            // One line at every text size, so the suggestions above stay visible at half height.
            Text("\(AssistantIdentity.name)가 틀릴 수 있어요")
                .font(.footnote)
                .foregroundStyle(Color.secondaryText)
                .lineLimit(1)
        }
        .padding([.horizontal, .bottom])
        // The room above the field is where messages fade out.
        .padding(.top, 28)
        .background { ComposerScrim() }
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
}

/// The composer's backdrop: clear at its top edge, then the page color behind a blur, so messages fade out under the
/// field instead of meeting a bar's hard edge.
private struct ComposerScrim: View {
    @Environment(\.accessibilityReduceTransparency) private var reduceTransparency
    /// How far below the composer's top edge the fade ends. From there down, and under the keyboard, it is the page.
    private static let fade: CGFloat = 44

    var body: some View {
        ZStack {
            if !reduceTransparency {
                Rectangle()
                    .fill(.ultraThinMaterial)
                    .mask { fading(from: .clear, to: .black) }
            }
            fading(from: AppPalette.listBackground.opacity(0), to: AppPalette.listBackground)
        }
        .ignoresSafeArea(edges: .bottom)
    }

    private func fading(from top: Color, to bottom: Color) -> some View {
        VStack(spacing: 0) {
            LinearGradient(colors: [top, bottom], startPoint: .top, endPoint: .bottom)
                .frame(height: Self.fade)
            bottom
        }
    }
}
