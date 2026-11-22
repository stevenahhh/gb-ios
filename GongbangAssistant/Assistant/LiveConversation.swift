import AVFoundation
import Observation
import RoundupCore
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
    /// Grows when a spoken undo could mean several steps, so the screen shows them to choose from.
    private(set) var undoChoices = 0
    /// How loud the assistant's voice is right now, 0...1; the orb swells with it.
    private(set) var speechLevel = 0.0

    /// One owner turn on its way to the server. 다시 시도 sends it again under the same id, so it runs once.
    private struct Question {
        let id = UUID().uuidString
        let text: String
        let history: [RoundupAPI.ChatTurn]
    }

    /// An answer on its way. It is not cancelled with the conversation: what a run did is recorded either way.
    private struct Reply {
        let question: Question?
        let turn: Task<LiveTurn, any Error>
    }

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
    private var progressTask: Task<Void, Never>?
    /// The answer the owner has not heard yet; a pause keeps it for the return.
    private var unheard: Reply?
    /// The question 다시 시도 sends again; nil when what failed was not a question.
    private var unanswered: Question?
    /// The recognizer gave up in the middle of this utterance, so only the server's transcript has its end.
    private var recognitionBroke = false
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
    private static let followInterval: Duration = .milliseconds(1500)
    private static let followLimit: TimeInterval = 180
    private static let unheardNotice = "방금 말씀을 놓쳤어요. 한 번만 더 들려주세요."
    private static let tooLongNotice = "말씀이 길어서 다 담지 못했어요. 조금씩 끊어서 들려주세요."
    private static let numberNotice = "숫자를 잘못 들은 것 같아요. 천천히 다시 불러 주시거나 채팅창에 쳐 주세요."

    var keepsScreenOn: Bool {
        switch phase {
        case .starting, .listening, .thinking, .speaking: true
        case .paused, .failed: false
        }
    }

    /// An answer is on its way, or arrived while paused and has not been heard.
    var isAnswerPending: Bool { unheard != nil }

    /// Every proposal of this conversation once, the latest first.
    var proposals: [AgentProposal] {
        var seen = Set<AgentProposal.ID>()
        return turns.reversed().flatMap { $0.agent?.proposals ?? [] }.filter { seen.insert($0.id).inserted }
    }

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
            fail(.microphone, "공도리가 마이크를 쓸 수 없게 막혀 있어요. 아이폰 설정에서 마이크를 허용해 주시면 음성으로 대화해요.")
            return
        }
        do {
            let session = AVAudioSession.sharedInstance()
            try session.setCategory(.playAndRecord, mode: .voiceChat, options: [.defaultToSpeaker, .allowBluetoothHFP])
            try session.setActive(true)
        } catch {
            fail(.microphone, "마이크가 안 켜져요. 통화 중이거나 다른 앱에서 쓰고 있지 않은지 봐 주세요.")
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
            resume()
        } else {
            openMicForBargeIn()
        }
    }

    /// The orb: stops the answer, sends what was heard, or resumes, depending on the moment.
    func tapOrb() {
        switch phase {
        case .speaking: interrupt()
        case .listening where !heard.trimmed.isEmpty: commit()
        case .paused: resume()
        case .failed: retry()
        // Only the wait stops: the answer stays on its way, and a resume picks it up.
        case .thinking where isAnswerPending: pause()
        case .starting, .listening, .thinking: break
        }
    }

    func retry() {
        guard case .failed(let failure) = phase else { return }
        speaker.stop()
        switch failure.kind {
        case .microphone: Task { await prepare() }
        case .recognition: listen()
        case .network:
            if let unanswered {
                ask(unanswered)
            } else {
                Task { await prepare() }
            }
        }
    }

    /// Leaving the app stops the mic and the voice; the owner resumes from 일시정지.
    func pause() {
        stopAudio()
        askTask?.cancel()
        if case .failed = phase { return }
        isMuted = true
        phase = .paused
    }

    private func resume() {
        isMuted = false
        if let unheard { wait(for: unheard) } else { listen() }
    }

    func end() {
        stopAudio()
        askTask?.cancel()
        speechTask?.cancel()
        speechTask = nil
        try? AVAudioSession.sharedInstance().setActive(false, options: .notifyOthersOnDeactivation)
    }

    // MARK: Listening

    private func listen(includingRecent: Bool = false) {
        heard = ""
        recognitionBroke = false
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
            fail(.microphone, "마이크가 안 켜져요. 조금 있다가 한 번 더 눌러 주세요.")
            return
        }
        let events = capture.beginRecognition(includingRecent: includingRecent)
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

    /// Without the mic an answer is still stopped from the orb, so a mic that will not open is no failure here.
    private func openMicForBargeIn() {
        guard !isMuted, !usesServerTranscription, phase == .speaking || phase == .thinking else { return }
        try? startCapture()
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
                if let loudSince, now.timeIntervalSince(loudSince) > 0.35 { interrupt(byVoice: true) }
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
        let stalled = !recognitionBroke && now.timeIntervalSince(lastHeardChangeAt) > 3
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
            if text.trimmed.isEmpty { listen() } else { commit() }
        case .failed(let domain, let code):
            // 1110 no speech, 203 retry, 216/301 cancelled: the recognizer simply starts over.
            let quiet = domain == "kAFAssistantErrorDomain" && [203, 216, 301, 1107, 1110].contains(code)
            if !heard.trimmed.isEmpty {
                // The owner may still be speaking, so their silence ends the turn and not this error.
                recognitionBroke = true
                capture.recordWithoutRecognition()
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
            if spokeAt != nil, now.timeIntervalSince(began) > 54 {
                // The recorder stops itself at 55 seconds, and half a request is not one.
                _ = try? recorder.stop()
                speak(Self.tooLongNotice)
                return
            }
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
                caption = Caption(sentence: Self.unheardNotice, spoken: 0)
                listen()
            } else {
                take(text)
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
        let isCutOff = recognitionBroke
        stopListening()
        phase = .thinking
        caption = nil
        guard ServerConnection.shared.hasNetworkPath else {
            fail(.network, ConnectionError().localizedDescription)
            return
        }
        askTask?.cancel()
        askTask = Task {
            let transcript = await Self.transcript(of: recording)
            guard !Task.isCancelled else { return }
            if recording.count >= LiveAudioCapture.fullRecording {
                speak(Self.tooLongNotice)
            } else if isCutOff && transcript.isEmpty {
                speak(Self.unheardNotice)
            } else if !SpokenTurn.numbersAgree(onDevice, transcript) {
                speak(Self.numberNotice)
            } else {
                take(transcript.isEmpty ? onDevice : transcript)
            }
        }
    }

    /// The server's transcript; empty when the call fails or hears nothing.
    private static func transcript(of wav: Data) async -> String {
        // Under ~0.3 s of 16 kHz audio there is nothing worth a server round trip.
        guard wav.count > 44 + 9_600 else { return "" }
        return (try? await RoundupAPI.transcribe(wav: wav))?.trimmed ?? ""
    }

    // MARK: Asking and speaking

    private func take(_ text: String) {
        heard = text
        guard !SpokenTurn.isTooLong(text) else {
            speak(Self.tooLongNotice)
            return
        }
        let question = Question(text: text, history: baseHistory + turns.compactMap(\.apiTurn))
        record(LiveTurn(role: .owner, text: text, items: []))
        if SpokenTurn.isUndoRequest(text) { undoLastStep() } else { ask(question) }
    }

    private func ask(_ question: Question) {
        wait(for: Reply(question: question, turn: Task {
            let answer = try await AgentCenter.shared.answer(
                question.text, history: question.history, source: .voice, requestID: question.id)
            let turn = try await Self.finished(answer)
            record(turn)
            return turn
        }))
    }

    /// Takes back the one step the last answer reports, without the model: it has no tool for this.
    private func undoLastStep() {
        let last = turns.last { $0.role == .assistant }
        let steps = (last?.agent?.steps ?? []).map(AgentCenter.shared.current).filter { $0.undoable && !$0.undone }
        wait(for: Reply(question: nil, turn: Task {
            let turn = try await undone(steps)
            record(turn)
            return turn
        }))
    }

    private func undone(_ steps: [AgentStep]) async throws -> LiveTurn {
        guard let step = steps.first else {
            return LiveTurn(role: .assistant, text: "이번 답에선 바꾼 게 없으니 되돌릴 것도 없어요.", items: [])
        }
        guard steps.count == 1 else {
            undoChoices += 1
            return LiveTurn(role: .assistant, text: "되돌릴 게 몇 개 있어요. 원하시는 걸 화면에서 눌러 주세요.", items: [])
        }
        do {
            let result = try await RoundupAPI.undo(step)
            replace(result.step)
            return LiveTurn(role: .assistant, text: result.summary, items: [], undidStep: true)
        } catch let refusal as RoundupAPIError {
            return LiveTurn(role: .assistant, text: refusal.message, items: [])
        }
    }

    private func wait(for reply: Reply) {
        unheard = reply
        unanswered = nil
        phase = .thinking
        caption = nil
        askTask?.cancel()
        askTask = Task { await deliver(reply) }
        progressTask?.cancel()
        progressTask = Task {
            try? await Task.sleep(for: .seconds(6))
            guard !Task.isCancelled, phase == .thinking else { return }
            _ = speaker.speak("지금 하는 중이에요.")
        }
    }

    private func deliver(_ reply: Reply) async {
        do {
            let turn = try await reply.turn.value
            guard !Task.isCancelled else { return }
            unheard = nil
            let waiting = (turn.agent?.proposals ?? []).filter {
                AgentCenter.shared.standing(of: $0, at: .now) == .open
            }
            speak(SpokenTurn.spoken(
                LiveText.speakable(turn.text),
                reportsWork: turn.undidStep || turn.agent?.steps.contains { !$0.isRead } == true,
                waiting: waiting.count))
        } catch {
            guard !Task.isCancelled else { return }
            unheard = nil
            fail(.network, (error is CancellationError ? ConnectionError() : error).localizedDescription,
                 retrying: reply.question)
        }
    }

    /// The answer as a turn, once its run has ended: an unfinished run has no words yet.
    private static func finished(_ answer: AssistantAnswer) async throws -> LiveTurn {
        guard let agent = answer.agent, agent.status.isUnfinished else {
            return LiveTurn(role: .assistant, text: answer.text, items: answer.items, agent: answer.agent)
        }
        let run = try await endedRun(agent.runID)
        AgentCenter.shared.noteRaised(run.proposals)
        return LiveTurn(role: .assistant, text: run.answer ?? "", items: [], agent: AgentRecord(run))
    }

    private static func endedRun(_ id: String) async throws -> AgentRun {
        let deadline = Date.now.addingTimeInterval(followLimit)
        var failures = 0
        while Date.now < deadline {
            do {
                let run = try await RoundupAPI.agentRun(id: id)
                guard run.status.isUnfinished else { return run }
                failures = 0
                try await Task.sleep(for: followInterval)
            } catch is ConnectionError {
                failures += 1
                try await Task.sleep(for: ReconnectBackoff.delay(afterFailures: failures))
            }
        }
        throw ConnectionError()
    }

    private func speak(_ text: String) {
        spokenText = text
        loudSince = nil
        phase = .speaking
        progressTask?.cancel()
        speaker.stop()
        openMicForBargeIn()
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
            guard !Task.isCancelled, phase == .speaking else { return }
            next = index + 1 < chunks.count ? fetch(chunks[index + 1]) : nil
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

    private func interrupt(byVoice: Bool = false) {
        guard phase == .speaking else { return }
        stopSpeaking()
        caption = nil
        listen(includingRecent: byVoice)
    }

    // MARK: Bookkeeping

    private func record(_ turn: LiveTurn) {
        turns.append(turn)
        onTurn(turn)
    }

    private func replace(_ step: AgentStep) {
        for turn in turns.indices {
            guard let index = turns[turn].agent?.steps.firstIndex(where: { $0.id == step.id }) else { continue }
            turns[turn].agent?.steps[index] = step
        }
        ConversationStore.shared.update(step)
    }

    private func fail(_ kind: Failure.Kind, _ message: String, retrying question: Question? = nil) {
        progressTask?.cancel()
        stopListening()
        stopCapture()
        unanswered = question
        phase = .failed(Failure(kind: kind, message: message))
        if kind == .network { _ = speaker.speak(message) }
    }

    private func stopAudio() {
        listenGeneration += 1
        progressTask?.cancel()
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
    /// The server refuses an earlier turn without words.
    var apiTurn: RoundupAPI.ChatTurn? {
        text.isEmpty ? nil : RoundupAPI.ChatTurn(role: role == .owner ? .owner : .assistant, text: text)
    }
}

private extension String {
    var trimmed: String { trimmingCharacters(in: .whitespacesAndNewlines) }
}

