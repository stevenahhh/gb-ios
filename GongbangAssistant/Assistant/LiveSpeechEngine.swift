import AVFoundation
import Speech
import os

/// What the live recognizer reports. Delivered from Speech's own queue, so it carries only plain values.
nonisolated enum LiveRecognitionEvent: Sendable {
    case partial(String)
    case final(String)
    case failed(domain: String, code: Int)
}

/// The microphone side of live mode: one AVAudioEngine tap that measures the level and feeds the current
/// recognition request. The tap and Speech's result handler run on audio and Speech queues, so this type is
/// nonisolated and guards its mutable state with a lock; the conversation reads it only through streams.
nonisolated final class LiveAudioCapture: @unchecked Sendable {
    private struct State {
        var request: SFSpeechAudioBufferRecognitionRequest?
        var task: SFSpeechRecognitionTask?
        /// The utterance as 16 kHz mono samples, sent to the server for the final transcript.
        var samples: [Int16] = []
    }

    private static let recordingFormat = AVAudioFormat(
        commonFormat: .pcmFormatInt16, sampleRate: 16_000, channels: 1, interleaved: true)!

    private let engine = AVAudioEngine()
    private let recognizer = SFSpeechRecognizer(locale: Locale(identifier: "ko-KR"))
    private let state = OSAllocatedUnfairLock(uncheckedState: State())
    private var converter: AVAudioConverter?
    private(set) var isRunning = false
    /// True when the input runs through voice processing, so the assistant's own voice is cancelled from the mic.
    private(set) var cancelsEcho = false

    var canRecognize: Bool { recognizer?.isAvailable == true }

    static func speechAuthorization() async -> SFSpeechRecognizerAuthorizationStatus {
        let current = SFSpeechRecognizer.authorizationStatus()
        guard current == .notDetermined else { return current }
        return await withCheckedContinuation { continuation in
            SFSpeechRecognizer.requestAuthorization { continuation.resume(returning: $0) }
        }
    }

    /// Starts the input tap. `levels` receives the mic level as 0...1 for every buffer.
    func start(levels: AsyncStream<Double>.Continuation) throws {
        guard !isRunning else { return }
        let input = engine.inputNode
        do {
            try input.setVoiceProcessingEnabled(true)
            // Keep the assistant's speech at full volume while the mic stays open for barge-in.
            input.voiceProcessingOtherAudioDuckingConfiguration = .init(enableAdvancedDucking: false, duckingLevel: .min)
            cancelsEcho = true
        } catch {
            cancelsEcho = false
        }
        _ = engine.mainMixerNode
        let format = input.outputFormat(forBus: 0)
        converter = AVAudioConverter(from: format, to: Self.recordingFormat)
        input.removeTap(onBus: 0)
        input.installTap(onBus: 0, bufferSize: 1024, format: format) { [weak self] buffer, _ in
            self?.receive(buffer)
            levels.yield(Self.level(of: buffer))
        }
        engine.prepare()
        do {
            try engine.start()
        } catch {
            input.removeTap(onBus: 0)
            throw error
        }
        isRunning = true
    }

    func beginRecognition() -> AsyncStream<LiveRecognitionEvent> {
        endRecognition(cancel: true)
        let (stream, continuation) = AsyncStream.makeStream(of: LiveRecognitionEvent.self)
        guard let recognizer else {
            continuation.yield(.failed(domain: "LiveAudioCapture", code: -1))
            continuation.finish()
            return stream
        }
        let request = SFSpeechAudioBufferRecognitionRequest()
        request.shouldReportPartialResults = true
        request.addsPunctuation = true
        request.taskHint = .dictation
        request.requiresOnDeviceRecognition = recognizer.supportsOnDeviceRecognition
        let task = recognizer.recognitionTask(with: request) { result, error in
            if let result {
                let text = result.bestTranscription.formattedString
                continuation.yield(result.isFinal ? .final(text) : .partial(text))
                if result.isFinal { continuation.finish() }
            } else if let error = error as NSError? {
                continuation.yield(.failed(domain: error.domain, code: error.code))
                continuation.finish()
            }
        }
        state.withLockUnchecked { $0 = State(request: request, task: task) }
        return stream
    }

    /// Hands over the utterance heard since `beginRecognition` as a WAV file.
    func takeRecording() -> Data {
        let samples = state.withLockUnchecked { current in
            defer { current.samples = [] }
            return current.samples
        }
        return Self.wav(samples)
    }

    private func receive(_ buffer: AVAudioPCMBuffer) {
        guard let request = state.withLockUnchecked({ $0.request }) else { return }
        request.append(buffer)
        guard let converter else { return }
        let capacity = AVAudioFrameCount(Double(buffer.frameLength) * 16_000 / buffer.format.sampleRate) + 32
        guard let output = AVAudioPCMBuffer(pcmFormat: Self.recordingFormat, frameCapacity: capacity) else { return }
        var supplied = false
        var error: NSError?
        converter.convert(to: output, error: &error) { _, status in
            if supplied {
                status.pointee = .noDataNow
                return nil
            }
            supplied = true
            status.pointee = .haveData
            return buffer
        }
        guard error == nil, let channel = output.int16ChannelData?[0] else { return }
        let samples = UnsafeBufferPointer(start: channel, count: Int(output.frameLength))
        state.withLockUnchecked { $0.samples.append(contentsOf: samples) }
    }

    private static func wav(_ samples: [Int16]) -> Data {
        func bytes<T: FixedWidthInteger>(_ value: T) -> Data { withUnsafeBytes(of: value.littleEndian) { Data($0) } }
        let payload = UInt32(samples.count * 2)
        var data = Data("RIFF".utf8) + bytes(36 + payload) + Data("WAVEfmt ".utf8)
        data += bytes(UInt32(16)) + bytes(UInt16(1)) + bytes(UInt16(1)) + bytes(UInt32(16_000))
        data += bytes(UInt32(32_000)) + bytes(UInt16(2)) + bytes(UInt16(16)) + Data("data".utf8) + bytes(payload)
        samples.withUnsafeBytes { data += $0 }
        return data
    }

    func endRecognition(cancel: Bool) {
        let old = state.withLockUnchecked { current in
            defer { current = State() }
            return current
        }
        old.request?.endAudio()
        if cancel { old.task?.cancel() }
    }

    func stop() {
        endRecognition(cancel: true)
        guard isRunning else { return }
        engine.inputNode.removeTap(onBus: 0)
        engine.stop()
        isRunning = false
    }

    /// RMS in decibels mapped so quiet rooms sit near 0 and normal speech near the middle.
    private static func level(of buffer: AVAudioPCMBuffer) -> Double {
        guard let samples = buffer.floatChannelData?[0], buffer.frameLength > 0 else { return 0 }
        let count = Int(buffer.frameLength)
        var sum: Float = 0
        for index in 0..<count { sum += samples[index] * samples[index] }
        let rms = sqrt(sum / Float(count))
        let decibels = 20 * log10(max(rms, 0.000_01))
        return Double(min(max((decibels + 55) / 40, 0), 1))
    }
}

enum LiveSpeechConfig {
    /// CLOVA Voice Premium through the server's /tts (enabled on the NCP app on 2026-11-21). Turn this off if the
    /// plan is cancelled; the device voice then speaks, with no network wait per sentence.
    static let usesServerSpeech = true
    /// After a /tts failure the device voice takes over for this long, so no answer waits on a dead endpoint.
    static var serverSpeechPausedUntil = Date.distantPast

    static var serverSpeechAvailable: Bool { usesServerSpeech && Date.now >= serverSpeechPausedUntil }
}

/// What the synthesizer reports, tagged with the utterance it belongs to so a stopped answer never moves the next one.
nonisolated enum LiveSpeechEvent: Sendable {
    case word(utterance: Int, range: NSRange)
    case finished(utterance: Int)
    case cancelled(utterance: Int)
}

/// Speaks answers with the best installed Korean voice. Delegate callbacks arrive off the main actor and are
/// forwarded as plain values.
nonisolated final class LiveSpeaker: NSObject, AVSpeechSynthesizerDelegate, @unchecked Sendable {
    let events: AsyncStream<LiveSpeechEvent>
    private let continuation: AsyncStream<LiveSpeechEvent>.Continuation
    private let synthesizer = AVSpeechSynthesizer()
    private let ids = OSAllocatedUnfairLock(initialState: [ObjectIdentifier: Int]())
    private var counter = 0

    /// Premium, then enhanced, then default quality; Yuna wins a tie.
    private static let voice: AVSpeechSynthesisVoice? = AVSpeechSynthesisVoice.speechVoices()
        .filter { $0.language == "ko-KR" }
        .max { rank($0) < rank($1) } ?? AVSpeechSynthesisVoice(language: "ko-KR")

    /// False when only a default-quality Korean voice is installed, so live mode can suggest downloading Yuna.
    static var hasNaturalVoice: Bool { voice.map { $0.quality == .premium || $0.quality == .enhanced } ?? false }

    private static func rank(_ voice: AVSpeechSynthesisVoice) -> (Int, Int) {
        let quality = switch voice.quality {
        case .premium: 3
        case .enhanced: 2
        default: 1
        }
        return (quality, voice.name.localizedCaseInsensitiveContains("Yuna") || voice.name.contains("유나") ? 1 : 0)
    }

    override init() {
        (events, continuation) = AsyncStream.makeStream(of: LiveSpeechEvent.self)
        super.init()
        synthesizer.delegate = self
    }

    /// Returns the id that this utterance's events carry.
    func speak(_ text: String) -> Int {
        counter += 1
        let utterance = AVSpeechUtterance(string: text)
        utterance.voice = Self.voice
        utterance.rate = AVSpeechUtteranceDefaultSpeechRate
        utterance.pitchMultiplier = 1
        utterance.preUtteranceDelay = 0
        let key = ObjectIdentifier(utterance)
        let id = counter
        ids.withLock { $0[key] = id }
        synthesizer.speak(utterance)
        return counter
    }

    func stop() {
        synthesizer.stopSpeaking(at: .immediate)
    }

    private func id(of utterance: AVSpeechUtterance, removing: Bool = false) -> Int? {
        let key = ObjectIdentifier(utterance)
        return ids.withLock { removing ? $0.removeValue(forKey: key) : $0[key] }
    }

    func speechSynthesizer(_ synthesizer: AVSpeechSynthesizer, willSpeakRangeOfSpeechString characterRange: NSRange,
                           utterance: AVSpeechUtterance) {
        if let id = id(of: utterance) { continuation.yield(.word(utterance: id, range: characterRange)) }
    }

    func speechSynthesizer(_ synthesizer: AVSpeechSynthesizer, didFinish utterance: AVSpeechUtterance) {
        if let id = id(of: utterance, removing: true) { continuation.yield(.finished(utterance: id)) }
    }

    func speechSynthesizer(_ synthesizer: AVSpeechSynthesizer, didCancel utterance: AVSpeechUtterance) {
        if let id = id(of: utterance, removing: true) { continuation.yield(.cancelled(utterance: id)) }
    }
}

enum LiveText {
    /// Markdown marks are read aloud literally by the synthesizer, so headings, bullets, and emphasis are removed.
    static func speakable(_ markdown: String) -> String {
        let options = AttributedString.MarkdownParsingOptions(interpretedSyntax: .inlineOnlyPreservingWhitespace)
        return markdown.split(separator: "\n", omittingEmptySubsequences: true).map { line in
            let bare = line.replacing(/^\s*(#{1,6}|[-*•>]|\d+[.)])\s+/, with: "")
            let plain = (try? AttributedString(markdown: String(bare), options: options)).map { String($0.characters) }
            return (plain ?? String(bare)).trimmingCharacters(in: .whitespaces)
        }
        .filter { !$0.isEmpty }
        .joined(separator: "\n")
    }

    /// Sentence ranges grouped for CLOVA Voice: the first sentence alone so speech starts fast, then up to
    /// about 300 characters per request.
    static func chunks(of text: String) -> [NSRange] {
        var chunks: [NSRange] = []
        for sentence in sentences(of: text) {
            if chunks.count > 1, let last = chunks.last, NSMaxRange(sentence) - last.location <= 300 {
                chunks[chunks.count - 1] = NSUnionRange(last, sentence)
            } else {
                chunks.append(sentence)
            }
        }
        return chunks
    }

    /// Every sentence that has something to say, with its trailing space, in order.
    static func sentences(of text: String) -> [NSRange] {
        let ns = text as NSString
        var sentences: [NSRange] = []
        ns.enumerateSubstrings(in: NSRange(location: 0, length: ns.length), options: .bySentences) { _, _, enclosing, _ in
            sentences.append(enclosing)
        }
        return sentences.filter { !ns.substring(with: $0).trimmingCharacters(in: .whitespacesAndNewlines).isEmpty }
    }

    /// The sentence that holds `location` (UTF-16 offset), so captions show one subtitle at a time.
    static func sentence(in text: String, containing location: Int) -> NSRange {
        let ns = text as NSString
        var found = NSRange(location: 0, length: ns.length)
        ns.enumerateSubstrings(in: NSRange(location: 0, length: ns.length), options: .bySentences) { _, range, enclosing, stop in
            if location < NSMaxRange(enclosing) {
                found = range
                stop.pointee = true
            }
        }
        return found
    }
}
