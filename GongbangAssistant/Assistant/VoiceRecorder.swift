import AVFoundation
import Observation

@MainActor
@Observable
final class VoiceRecorder {
    private(set) var isRecording = false
    private var recorder: AVAudioRecorder?
    private let fileURL = FileManager.default.temporaryDirectory.appending(path: "assistant-voice.wav")

    func start() async throws {
        guard await AVAudioApplication.requestRecordPermission() else {
            throw RoundupAPIError(message: "마이크 권한이 꺼져 있어요. 설정에서 마이크를 허용해 주세요.")
        }
        let session = AVAudioSession.sharedInstance()
        try session.setCategory(.record, mode: .measurement)
        try session.setActive(true)
        let settings: [String: Any] = [
            AVFormatIDKey: kAudioFormatLinearPCM,
            AVSampleRateKey: 16_000,
            AVNumberOfChannelsKey: 1,
            AVLinearPCMBitDepthKey: 16,
            AVLinearPCMIsFloatKey: false,
        ]
        let recorder = try AVAudioRecorder(url: fileURL, settings: settings)
        guard recorder.record(forDuration: 55) else {
            throw RoundupAPIError(message: "녹음을 시작하지 못했어요.")
        }
        self.recorder = recorder
        isRecording = true
    }

    func stop() throws -> Data {
        recorder?.stop()
        recorder = nil
        isRecording = false
        try? AVAudioSession.sharedInstance().setActive(false)
        return try Data(contentsOf: fileURL)
    }
}
