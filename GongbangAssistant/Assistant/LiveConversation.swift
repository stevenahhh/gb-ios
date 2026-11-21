import AVFoundation
import Observation
import Speech

/// One live voice session: listen, ask, speak, and listen again, until the owner mutes or leaves.
@MainActor
@Observable
final class LiveConversation {
    enum Phase: Equatable {
        case starting, listening, thinking, speaking, paused
        case failed(Failure)
    }

    struct Failure: Equatable {
        enum Kind { case microphone, network, recognition }
        let kind: Kind
        let message: String
    }

    /// The subtitle on screen: one sentence of the answer and how much of it has been spoken (UTF-16 length).
    struct Caption: Equatable {
        let sentence: String
        let spoken: Int
    }

    private(set) var phase: Phase = .starting
    private(set) var isMuted = false
    /// The owner's words as recognized so far; kept as the question while the assistant thinks.
    private(set) var heard = ""
    private(set) var caption: Caption?
    private(set) var turns: [LiveTurn] = []
    private(set) var level = 0.0
    /// How loud the assistant's voice is right now, 0...1; the orb swells with it.
    private(set) var speechLevel = 0.0

    private var baseHistory: [RoundupAPI.ChatTurn] = []
    private var onTurn: (LiveTurn) -> Void = { _ in }
    private let capture = LiveAudioCapture()
    private let speaker = LiveSpeaker()
    private var recorder: VoiceRecorder?
    private var usesServerTranscription = false

    private var listenTask: Task<Void, Never>?
    private var silenceTask: Task<Void, Never>?
    private var levelTask: Task<Void, Never>?
    private var speechTask: Task<Void, Never>?
    private var askTask: Task<Void, Never>?
    private var speakTask: Task<Void, Never>?
    private var player: AVAudioPlayer?
    /// Each queued device utterance's start in `spokenText`, since its word ranges count from its own sentence.
    private var deviceOffsets: [Int: Int] = [:]
    private var lastUtterance: Int?
    private var listenGeneration = 0
    private var spokenText = ""
    private var lastVoiceAt = Date.distantPast
    private var lastHeardChangeAt = Date.distantPast
    private var loudSince: Date?

    private static let endOfUtterance: TimeInterval = 1.2
    private static let speechLevel = 0.35
    private static let bargeInLevel = 0.6

    func start(history: [RoundupAPI.ChatTurn], onTurn: @escaping (LiveTurn) -> Void) async {
        baseHistory = history
        self.onTurn = onTurn
        if speechTask == nil {
            speechTask = Task { [weak self, events = speaker.events] in
                for await event in events { self?.handle(event) }
            }
        }
        await prepare()
    }

    private func prepare() async {
        phase = .starting
        guard await AVAudioApplication.requestRecordPermission() else {
            fail(.microphone, "마이크 권한이 꺼져 있어요. 설정에서 마이크를 허용하면 말로 대화할 수 있어요.")
            return
        }
        do {
            let session = AVAudioSession.sharedInstance()
            try session.setCategory(.playAndRecord, mode: .voiceChat, options: [.defaultToSpeaker, .allowBluetoothHFP])
            try session.setActive(true)
        } catch {
            fail(.microphone, "마이크를 켜지 못했어요. 다른 앱이 마이크를 쓰고 있는지 확인해 주세요.")
            return
        }
        let status = await LiveAudioCapture.speechAuthorization()
        usesServerTranscription = status != .authorized || !capture.canRecognize
        listen()
    }

    // MARK: Owner controls

    func toggleMute() {
        isMuted.toggle()
        if isMuted {
            if phase == .listening {
                stopListening()
                phase = .paused
            }
            stopCapture()
        } else if phase == .paused {
            listen()
        }
    }

    /// The orb: stops the answer, sends what was heard, or resumes, depending on the moment.
    func tapOrb() {
        switch phase {
        case .speaking: interrupt()
        case .listening where !heard.trimmed.isEmpty: commit()
        case .paused:
            isMuted = false
            listen()
        case .failed: retry()
        case .starting, .listening, .thinking: break
        }
    }

    func retry() {
        guard case .failed(let failure) = phase else { return }
        switch failure.kind {
        case .microphone: Task { await prepare() }
        case .recognition: listen()
        case .network:
            if let question = turns.last.flatMap({ $0.role == .owner ? $0.text : nil }) {
                ask(question, history: baseHistory + turns.dropLast().map(\.apiTurn))
            } else {
                listen()
            }
        }
    }

    /// Leaving the app stops the mic and the voice; the owner resumes from 일시정지.
    func pause() {
        stopAudio()
        askTask?.cancel()
        isMuted = true
        phase = .paused
    }

    func end() {
        stopAudio()
        askTask?.cancel()
        speechTask?.cancel()
        speechTask = nil
        try? AVAudioSession.sharedInstance().setActive(false, options: .notifyOthersOnDeactivation)
    }

    // MARK: Listening

    private func listen() {
        heard = ""
        guard !isMuted else {
            phase = .paused
            return
        }
        stopListening()
        listenGeneration += 1
        let generation = listenGeneration
        lastVoiceAt = .distantPast
        lastHeardChangeAt = .distantPast
        phase = .listening
        if usesServerTranscription {
            listenTask = Task { await recordUtterance(generation: generation) }
            return
        }
        do {
            try startCapture()
        } catch {
            fail(.microphone, "마이크를 켜지 못했어요. 다시 시도해 주세요.")
            return
        }
        let events = capture.beginRecognition()
        listenTask = Task { [weak self] in
            for await event in events {
                guard let self, generation == self.listenGeneration else { return }
                self.handle(event)
            }
        }
        silenceTask = Task { [weak self] in
            while !Task.isCancelled {
                try? await Task.sleep(for: .milliseconds(100))
                guard let self, generation == self.listenGeneration, self.phase == .listening else { return }
                if self.utteranceEnded(at: .now) { self.commit() }
            }
        }
    }

    private func startCapture() throws {
        guard !capture.isRunning else { return }
        let (levels, continuation) = AsyncStream.makeStream(of: Double.self, bufferingPolicy: .bufferingNewest(1))
        try capture.start(levels: continuation)
        levelTask?.cancel()
        levelTask = Task { [weak self] in
            for await value in levels { self?.receive(level: value) }
        }
    }

    private func receive(level value: Double) {
        level = level * 0.6 + value * 0.4
        let now = Date.now
        switch phase {
        case .listening where value > Self.speechLevel:
            lastVoiceAt = now
        case .speaking where capture.cancelsEcho:
            // Without echo cancellation the assistant's own voice would interrupt itself, so only the orb stops it then.
            if value > Self.bargeInLevel {
                loudSince = loudSince ?? now
                if let loudSince, now.timeIntervalSince(loudSince) > 0.35 { interrupt() }
            } else {
                loudSince = nil
            }
        default:
            break
        }
    }

    /// End of turn: ~1.2 s with no new words and no voice-level sound, or 3 s of words not changing in a noisy room.
    private func utteranceEnded(at now: Date) -> Bool {
        guard !heard.trimmed.isEmpty else { return false }
        let quiet = now.timeIntervalSince(max(lastVoiceAt, lastHeardChangeAt)) > Self.endOfUtterance
        let stalled = now.timeIntervalSince(lastHeardChangeAt) > 3
        return quiet || stalled
    }

    private func handle(_ event: LiveRecognitionEvent) {
        switch event {
        case .partial(let text):
            if text != heard {
                heard = text
                lastHeardChangeAt = .now
                caption = nil
            }
        case .final(let text):
            heard = text
            commit()
        case .failed(let domain, let code):
            // 1110 no speech, 203 retry, 216/301 cancelled: the recognizer simply starts over.
            let quiet = domain == "kAFAssistantErrorDomain" && [203, 216, 301, 1107, 1110].contains(code)
            if !heard.trimmed.isEmpty {
                commit()
            } else if quiet {
                listen()
            } else {
                // The recognizer is unavailable here (no network, no on-device model): the server transcribes instead.
                usesServerTranscription = true
                listen()
            }
        }
    }

    /// Fallback without live recognition: record until the level shows the owner stopped, then ask the server.
    private func recordUtterance(generation: Int) async {
        let recorder = recorder ?? VoiceRecorder()
        self.recorder = recorder
        do {
            try await recorder.start(configuresSession: false)
        } catch {
            fail(.microphone, error.localizedDescription)
            return
        }
        let began = Date.now
        var spokeAt: Date?
        while !Task.isCancelled, generation == listenGeneration, phase == .listening {
            try? await Task.sleep(for: .milliseconds(80))
            let value = recorder.level()
            level = level * 0.6 + value * 0.4
            let now = Date.now
            if value > Self.speechLevel { spokeAt = now }
            if let spokeAt, now.timeIntervalSince(spokeAt) > Self.endOfUtterance { break }
            if spokeAt == nil, now.timeIntervalSince(began) > 50 {
                _ = try? recorder.stop()
                listen()
                return
            }
        }
        guard !Task.isCancelled, generation == listenGeneration, phase == .listening else {
            _ = try? recorder.stop()
            return
        }
        phase = .thinking
        do {
            let text = try await RoundupAPI.transcribe(wav: recorder.stop()).trimmed
            guard generation == listenGeneration, phase == .thinking else { return }
            if text.isEmpty {
                caption = Caption(sentence: "잘 못 들었어요. 다시 말씀해 주세요.", spoken: 0)
                listen()
            } else {
                heard = text
                send(text)
            }
        } catch is CancellationError {
            return
        } catch {
            fail(.network, error.localizedDescription)
        }
    }

    private func stopListening() {
        listenTask?.cancel()
        listenTask = nil
        silenceTask?.cancel()
        silenceTask = nil
        capture.endRecognition(cancel: true)
        if recorder?.isRecording == true { _ = try? recorder?.stop() }
    }

    /// On-device recognition decides when the owner stopped; NAVER CSR then reads the same audio for the final text.
    private func commit() {
        let onDevice = heard.trimmed
        guard phase == .listening, !onDevice.isEmpty else { return }
        listenGeneration += 1
        let recording = capture.takeRecording()
        stopListening()
        phase = .thinking
        caption = nil
        askTask?.cancel()
        askTask = Task {
            let question = await Self.finalText(of: recording, onDevice: onDevice)
            guard !Task.isCancelled else { return }
            heard = question
            let history = baseHistory + turns.map(\.apiTurn)
            record(LiveTurn(role: .owner, text: question, items: []))
            await answer(question, history: history)
        }
    }

    /// The server's transcript when it has one; the on-device words when the call fails or hears nothing.
    private static func finalText(of wav: Data, onDevice: String) async -> String {
        // Under ~0.3 s of 16 kHz audio there is nothing worth a server round trip.
        guard wav.count > 44 + 9_600 else { return onDevice }
        let text = (try? await RoundupAPI.transcribe(wav: wav))?.trimmed ?? ""
        return text.isEmpty ? onDevice : text
    }

    // MARK: Asking and speaking

    private func send(_ question: String) {
        let history = baseHistory + turns.map(\.apiTurn)
        record(LiveTurn(role: .owner, text: question, items: []))
        ask(question, history: history)
    }

    private func ask(_ question: String, history: [RoundupAPI.ChatTurn]) {
        phase = .thinking
        caption = nil
        askTask?.cancel()
        askTask = Task { await answer(question, history: history) }
    }

    private func answer(_ question: String, history: [RoundupAPI.ChatTurn]) async {
        do {
            let reply = try await RoundupAPI.ask(question: question, history: history)
            guard !Task.isCancelled else { return }
            record(LiveTurn(role: .assistant, text: reply.answer, items: reply.items))
            speak(reply.answer)
        } catch is CancellationError {
            return
        } catch {
            guard !Task.isCancelled else { return }
            fail(.network, error.localizedDescription)
        }
    }

    private func speak(_ answer: String) {
        spokenText = LiveText.speakable(answer)
        loudSince = nil
        phase = .speaking
        showSpoken(upTo: 0)
        speakTask?.cancel()
        if LiveSpeechConfig.serverSpeechAvailable {
            speakTask = Task { await play(LiveText.chunks(of: spokenText)) }
        } else {
            speakOnDevice(from: 0)
        }
    }

    /// CLOVA Voice reads one chunk while the next is fetched. The first failure hands the rest of the answer, and
    /// the next ten minutes, to the device voice without retrying, so the owner never waits on a dead endpoint.
    private func play(_ chunks: [NSRange]) async {
        let text = spokenText as NSString
        func fetch(_ range: NSRange) -> Task<Data, any Error> {
            Task { try await RoundupAPI.speech(text: text.substring(with: range)) }
        }
        var next = chunks.first.map(fetch)
        for (index, range) in chunks.enumerated() {
            guard let pending = next else { break }
            let audio = try? await pending.value
            next = index + 1 < chunks.count ? fetch(chunks[index + 1]) : nil
            guard !Task.isCancelled, phase == .speaking else {
                next?.cancel()
                return
            }
            guard let audio, await playClip(audio, range: range) else {
                LiveSpeechConfig.serverSpeechPausedUntil = .now.addingTimeInterval(600)
                next?.cancel()
                if !Task.isCancelled { speakOnDevice(from: range.location) }
                return
            }
        }
        if !Task.isCancelled { finishSpeaking() }
    }

    /// Plays one MP3 clip to the end, moving the subtitle with its progress. False when it cannot play.
    private func playClip(_ audio: Data, range: NSRange) async -> Bool {
        guard let player = try? AVAudioPlayer(data: audio) else { return false }
        player.isMeteringEnabled = true
        self.player = player
        guard player.play() else { return false }
        while player.isPlaying, !Task.isCancelled {
            try? await Task.sleep(for: .milliseconds(50))
            player.updateMeters()
            speechLevel = Double(min(max((player.averagePower(forChannel: 0) + 40) / 35, 0), 1))
            let progress = player.duration > 0 ? player.currentTime / player.duration : 0
            showSpoken(upTo: range.location + Int(Double(range.length) * progress))
        }
        player.stop()
        speechLevel = 0
        return true
    }

    /// Queues one utterance per sentence: natural pauses between sentences, and a barge-in stops the queue at once.
    private func speakOnDevice(from location: Int) {
        let text = spokenText as NSString
        deviceOffsets = [:]
        lastUtterance = nil
        for sentence in LiveText.sentences(of: spokenText) where NSMaxRange(sentence) > location {
            let start = max(sentence.location, location)
            let id = speaker.speak(text.substring(with: NSRange(location: start, length: NSMaxRange(sentence) - start)))
            deviceOffsets[id] = start
            lastUtterance = id
        }
        if lastUtterance == nil { finishSpeaking() }
    }

    private func handle(_ event: LiveSpeechEvent) {
        switch event {
        case .word(let id, let range):
            guard let offset = deviceOffsets[id], phase == .speaking else { return }
            speechLevel = 0.8
            showSpoken(upTo: offset + NSMaxRange(range))
            Task {
                try? await Task.sleep(for: .milliseconds(180))
                if deviceOffsets[id] != nil { speechLevel = 0.3 }
            }
        case .finished(let id):
            guard id == lastUtterance, phase == .speaking else { return }
            finishSpeaking()
        case .cancelled:
            break
        }
    }

    /// Shows the sentence holding `position` with everything before it marked as spoken.
    private func showSpoken(upTo position: Int) {
        let text = spokenText as NSString
        let clamped = min(max(position, 0), text.length)
        let sentence = LiveText.sentence(in: spokenText, containing: max(clamped - 1, 0))
        caption = Caption(sentence: text.substring(with: sentence),
                          spoken: min(max(clamped - sentence.location, 0), sentence.length))
    }

    private func finishSpeaking() {
        speechLevel = 0
        showSpoken(upTo: (spokenText as NSString).length)
        listen()
    }

    private func stopSpeaking() {
        speakTask?.cancel()
        speakTask = nil
        player?.stop()
        player = nil
        deviceOffsets = [:]
        lastUtterance = nil
        speaker.stop()
        speechLevel = 0
    }

    private func interrupt() {
        guard phase == .speaking else { return }
        stopSpeaking()
        caption = nil
        listen()
    }

    // MARK: Bookkeeping

    private func record(_ turn: LiveTurn) {
        turns.append(turn)
        onTurn(turn)
    }

    private func fail(_ kind: Failure.Kind, _ message: String) {
        stopListening()
        phase = .failed(Failure(kind: kind, message: message))
    }

    private func stopAudio() {
        listenGeneration += 1
        stopListening()
        stopSpeaking()
        stopCapture()
    }

    private func stopCapture() {
        capture.stop()
        levelTask?.cancel()
        levelTask = nil
        level = 0
    }
}

private extension LiveTurn {
    var apiTurn: RoundupAPI.ChatTurn {
        RoundupAPI.ChatTurn(role: role == .owner ? .owner : .assistant, text: text)
    }
}

private extension String {
    var trimmed: String { trimmingCharacters(in: .whitespacesAndNewlines) }
}

