import SwiftUI

/// The assistant sheet's input row: the question field, dictation, and send, with the reminder under them.
struct AssistantComposer: View {
    /// The room above the field where messages fade out; the sheet's backdrop is half the page color at its top.
    static let fadeRoom: CGFloat = 28

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
                    // A wrapping field takes the keyboard's send key as a line break, so that break sends instead.
                    .onChange(of: message) {
                        guard message.last?.isNewline == true else { return }
                        message.removeLast()
                        send()
                    }
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
        .padding(.top, Self.fadeRoom)
        .background(alignment: .top) { ComposerCover() }
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

/// Covers the messages that scroll under the composer, from where the backdrop turns fully opaque (the field's top
/// edge) down, with a short soft edge so a line of text is not cut sharply. Above it the messages stay readable.
private struct ComposerCover: View {
    private static let softEdge: CGFloat = 12

    var body: some View {
        VStack(spacing: 0) {
            Color.clear
                .frame(height: AssistantComposer.fadeRoom - Self.softEdge)
            LinearGradient(colors: [AppPalette.listBackground.opacity(0), AppPalette.listBackground],
                           startPoint: .top, endPoint: .bottom)
                .frame(height: Self.softEdge)
            AppPalette.listBackground
        }
        .ignoresSafeArea(edges: .bottom)
        .allowsHitTesting(false)
    }
}

/// The assistant sheet keeps the system's translucent background, like Siri. Over it this layer adds the page color
/// (black in dark mode): none at the grabber, half just above the question field, and all of it from the field down,
/// so messages fade out under the field. Reduce Transparency gets the plain page color.
struct AssistantBackdrop: View {
    /// The composer in global coordinates; zero until it is laid out.
    let composerFrame: CGRect
    @Environment(\.accessibilityReduceTransparency) private var reduceTransparency

    var body: some View {
        GeometryReader { proxy in
            if reduceTransparency {
                AppPalette.listBackground
            } else {
                let sheet = proxy.frame(in: .global)
                let height = max(sheet.height, 1)
                let half = composerFrame == .zero ? 1 : min(max((composerFrame.minY - sheet.minY) / height, 0), 1)
                let full = composerFrame == .zero
                    ? 1 : min(max((composerFrame.minY + AssistantComposer.fadeRoom - sheet.minY) / height, half), 1)
                LinearGradient(stops: [
                    .init(color: AppPalette.listBackground.opacity(0), location: 0),
                    .init(color: AppPalette.listBackground.opacity(0.5), location: half),
                    .init(color: AppPalette.listBackground, location: full),
                ], startPoint: .top, endPoint: .bottom)
            }
        }
        .ignoresSafeArea()
    }
}
