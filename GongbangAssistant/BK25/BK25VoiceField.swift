import SwiftUI

/// One line of text that can also be dictated, shaped like the assistant's question field.
struct BK25VoiceField: View {
    @Binding var text: String
    let prompt: String
    @State private var recorder = VoiceRecorder()
    @State private var isTranscribing = false
    @State private var errorMessage: String?

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack(alignment: .bottom, spacing: 8) {
                TextField(isTranscribing ? "듣고 바로 글자로 옮기는 중이에요" : prompt, text: $text, axis: .vertical)
                    .lineLimit(1...4)
                    .textFieldStyle(.plain)
                    .padding(.horizontal, 12)
                    .padding(.vertical, 10)
                    .background(CalendarTokens.fill, in: .inner)
                    .accessibilityIdentifier("bk25.field")
                Button {
                    Task { await toggleRecording() }
                } label: {
                    Label(recorder.isRecording ? "녹음 멈추기" : "음성으로 말하기",
                          systemImage: recorder.isRecording ? "stop.fill" : "mic.fill")
                        .labelStyle(.iconOnly)
                        .frame(minWidth: 30, minHeight: 30)
                        .symbolEffect(.variableColor.iterative, options: .repeating, isActive: isTranscribing)
                }
                .buttonStyle(.bordered)
                .buttonBorderShape(.circle)
                .tint(recorder.isRecording ? .red : nil)
                .disabled(isTranscribing)
                .accessibilityIdentifier("bk25.record")
            }
            if let errorMessage {
                Label(errorMessage, systemImage: "exclamationmark.circle")
                    .font(.subheadline)
                    .accessibilityIdentifier("bk25.voiceError")
            }
        }
    }

    private func toggleRecording() async {
        errorMessage = nil
        do {
            if recorder.isRecording {
                let wav = try recorder.stop()
                isTranscribing = true
                defer { isTranscribing = false }
                let spoken = try await RoundupAPI.transcribe(wav: wav)
                if spoken.isEmpty {
                    errorMessage = "한 번 더 말씀하시거나 키보드로 적어 보세요"
                } else {
                    text = text.isEmpty ? spoken : "\(text) \(spoken)"
                }
            } else {
                try await recorder.start()
            }
        } catch {
            errorMessage = error.localizedDescription
        }
    }
}
