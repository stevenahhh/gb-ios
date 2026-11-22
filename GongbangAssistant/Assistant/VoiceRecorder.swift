import AVFoundation
import Observation

@MainActor
@Observable
final class VoiceRecorder {
    private(set) var isRecording = false
    private var recorder: AVAudioRecorder?
    private var ownsSession = false
    private let fileURL = FileManager.default.temporaryDirectory.appending(path: "assistant-voice.wav")

    /// Live mode passes `configuresSession: false` because it already runs a play-and-record voice chat session.
    func start(configuresSession: Bool = true) async throws {
        guard await AVAudioApplication.requestRecordPermission() else {
            throw RoundupAPIError(message: "마이크 권한이 꺼져 있어요. 설정에서 마이크를 허용해 주세요.")
        }
        if configuresSession {
            let session = AVAudioSession.sharedInstance()
            try session.setCategory(.record, mode: .measurement)
            try session.setActive(true)
        }
        ownsSession = configuresSession
        let settings: [String: Any] = [
            AVFormatIDKey: kAudioFormatLinearPCM,
            AVSampleRateKey: 16_000,
            AVNumberOfChannelsKey: 1,
            AVLinearPCMBitDepthKey: 16,
            AVLinearPCMIsFloatKey: false,
        ]
        let recorder = try AVAudioRecorder(url: fileURL, settings: settings)
        recorder.isMeteringEnabled = true
        guard recorder.record(forDuration: 55) else {
            throw RoundupAPIError(message: "녹음을 시작하지 못했어요.")
        }
        self.recorder = recorder
        isRecording = true
    }

    /// The current input level as 0...1, on the same scale as live mode's engine tap.
    func level() -> Double {
        guard let recorder, recorder.isRecording else { return 0 }
        recorder.updateMeters()
        return Double(min(max((recorder.averagePower(forChannel: 0) + 55) / 40, 0), 1))
    }

    func stop() throws -> Data {
        recorder?.stop()
        recorder = nil
        isRecording = false
        if ownsSession { try? AVAudioSession.sharedInstance().setActive(false) }
        // What was said can name customers, so the recording does not outlive its reading.
        defer { try? FileManager.default.removeItem(at: fileURL) }
        return try Data(contentsOf: fileURL)
    }
}
