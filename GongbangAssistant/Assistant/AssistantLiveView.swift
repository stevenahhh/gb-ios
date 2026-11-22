import AVFAudio
import RoundupCore
import SwiftUI
import UIKit

/// One finished turn of a live conversation, handed to whoever keeps the shared chat history.
struct LiveTurn: Sendable {
    enum Role: Sendable { case owner, assistant }
    let role: Role
    let text: String
    let items: [WorkItem]
    /// What the agent did or proposed for an answer; nil for the owner's words and for an answer `/ask` gave.
    var agent: AgentRecord?
    /// True for a turn that reports an undo, which changes a row without a run of its own.
    var undidStep = false
}

/// Full-screen voice conversation: the owner talks, the assistant answers aloud with subtitles.
struct AssistantLiveView: View {
    private let history: @MainActor () -> [RoundupAPI.ChatTurn]
    private let onTurn: @MainActor (LiveTurn) -> Void
    @State private var conversation = LiveConversation()
    @State private var showsTranscript = false
    @State private var center = AgentCenter.shared
    @Environment(AppModel.self) private var app
    @Environment(\.dismiss) private var dismiss
    @Environment(\.scenePhase) private var scenePhase

    init(history: @escaping @MainActor () -> [RoundupAPI.ChatTurn], onTurn: @escaping @MainActor (LiveTurn) -> Void) {
        self.history = history
        self.onTurn = onTurn
    }

    var body: some View {
        NavigationStack {
            VStack(spacing: 0) {
                status
                    .padding(.top, 12)
                if showsTranscript {
                    LiveOrb(conversation: conversation, diameter: 72)
                        .padding(.vertical, 12)
                    LiveTranscript(turns: conversation.turns)
                        .transition(.opacity)
                } else if !shownProposals.isEmpty {
                    LiveOrb(conversation: conversation, diameter: 96)
                        .padding(.vertical, 12)
                    // Above the caption, so a caption that changes height never moves a button under a finger.
                    proposalCards
                    captions
                        .frame(maxWidth: .infinity, alignment: .top)
                        .padding(.horizontal, 28)
                } else {
                    Spacer(minLength: 24)
                    LiveOrb(conversation: conversation, diameter: 220)
                    Spacer(minLength: 24)
                    captions
                        .frame(maxWidth: .infinity, minHeight: 150, alignment: .top)
                        .padding(.horizontal, 28)
                }
                controls
                    .padding(.top, 12)
                    .padding(.bottom, 8)
            }
            .background { LiveBackground() }
            .toolbarVisibility(.hidden, for: .navigationBar)
            .appDestinations()
        }
        .animation(.smooth, value: showsTranscript)
        .accessibilityIdentifier("assistant.live")
        .sensoryFeedback(trigger: conversation.phase) { _, phase in
            switch phase {
            case .listening: .impact(weight: .light)
            case .thinking: .selection
            case .speaking: .impact(flexibility: .soft)
            case .paused: .impact(weight: .medium)
            case .failed: .error
            case .starting: nil
            }
        }
        .task {
            await conversation.start(history: history()) { turn in
                onTurn(turn)
                // A spoken request can change a row too, so the screens behind this one reload.
                if turn.agent?.changedData == true || turn.undidStep { app.dataDidChange() }
            }
        }
        // A locked screen would pause the conversation while a run is still at work.
        .onChange(of: conversation.keepsScreenOn, initial: true) { _, isOn in
            UIApplication.shared.isIdleTimerDisabled = isOn
        }
        .onChange(of: conversation.undoChoices) { showsTranscript = true }
        .onReceive(NotificationCenter.default.publisher(for: AVAudioSession.interruptionNotification)) { notice in
            let type = notice.userInfo?[AVAudioSessionInterruptionTypeKey] as? UInt
            if type == AVAudioSession.InterruptionType.began.rawValue { conversation.pause() }
        }
        .onChange(of: scenePhase) { _, phase in
            if phase == .background { conversation.pause() }
        }
        .onDisappear {
            conversation.end()
            UIApplication.shared.isIdleTimerDisabled = false
        }
        // The root's alert would close this screen, so it shows its own.
        .alert("처리하지 못했어요", isPresented: Binding(get: { app.failureMessage != nil },
                                                  set: { if !$0 { app.failureMessage = nil } })) {
            Button("확인", role: .cancel) {}
        } message: {
            Text(app.failureMessage ?? "")
        }
    }

    // MARK: Proposals

    /// Every proposal of this conversation that still waits, and the latest answer's with what became of them.
    private var shownProposals: [AgentProposal] {
        let latest = Set((conversation.turns.last?.agent?.proposals ?? []).map(\.id))
        return conversation.proposals.filter { latest.contains($0.id) || center.standing(of: $0, at: .now) == .open }
    }

    private var proposalCards: some View {
        ScrollView {
            VStack(spacing: 12) {
                ForEach(shownProposals) { proposal in
                    AgentProposalCard(proposal: proposal, isPrimary: false)
                        .padding(16)
                        .background(AppPalette.card, in: .card)
                }
            }
            .padding(.horizontal, 20)
            .padding(.vertical, 8)
        }
        .scrollBounceBehavior(.basedOnSize)
        .accessibilityIdentifier("assistant.live.proposals")
    }

    // MARK: Status and captions

    private var statusText: String {
        switch conversation.phase {
        case .starting: "준비하고 있어요"
        case .listening: "듣고 있어요"
        case .thinking: "생각하고 있어요"
        case .speaking: "말하고 있어요"
        case .paused: "일시정지"
        case .failed: "대화를 이어 가지 못했어요"
        }
    }

    private var hintText: String {
        switch conversation.phase {
        case .listening: "말씀이 끝나면 바로 답해 드려요"
        case .speaking: "원을 누르면 말을 멈추고 들을게요"
        case .paused where conversation.isAnswerPending: "맡긴 일은 계속 처리해요. 원을 누르면 이어서 알려 드려요"
        case .paused: "마이크를 켜거나 원을 누르면 다시 들어요"
        case .starting, .thinking, .failed: "\(AssistantIdentity.name)가 틀릴 수 있어요"
        }
    }

    private var status: some View {
        VStack(spacing: 4) {
            Text(statusText)
                .font(.headline)
                .contentTransition(.opacity)
            Text(verbatim: hintText)
                .font(.subheadline)
                .foregroundStyle(Color.secondaryText)
        }
        .multilineTextAlignment(.center)
        .padding(.horizontal, 24)
        .animation(.default, value: conversation.phase)
        .accessibilityElement(children: .combine)
        .accessibilityAddTraits(.updatesFrequently)
        .accessibilityIdentifier("assistant.live.status")
    }

    @ViewBuilder
    private var captions: some View {
        VStack(spacing: 16) {
            switch conversation.phase {
            case .failed(let failure):
                failureView(failure)
            case .thinking:
                ownerLine(conversation.heard)
            case .listening, .starting, .paused:
                if let caption = conversation.caption, conversation.heard.isEmpty {
                    assistantLine(caption)
                } else {
                    ownerLine(conversation.heard)
                }
            case .speaking:
                if let caption = conversation.caption { assistantLine(caption) }
            }
        }
        .multilineTextAlignment(.center)
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("assistant.live.caption")
    }

    private func ownerLine(_ text: String) -> some View {
        Text(verbatim: text)
            .font(.title3)
            .foregroundStyle(Color.secondaryText)
            .lineLimit(5)
            .truncationMode(.head)
            .contentTransition(.opacity)
            .accessibilityIdentifier("assistant.live.heard")
    }

    private func assistantLine(_ caption: LiveConversation.Caption) -> some View {
        let sentence = caption.sentence as NSString
        let spokenLength = min(max(caption.spoken, 0), sentence.length)
        var spoken = AttributedString(sentence.substring(to: spokenLength))
        spoken.foregroundColor = .primary
        var rest = AttributedString(sentence.substring(from: spokenLength))
        // Full-strength gray: a thinner one drops under 3:1 on the light backdrop.
        rest.foregroundColor = Color.secondaryText
        return Text(spoken + rest)
            .font(.title2.weight(.medium))
            .lineLimit(6)
            .animation(.easeOut(duration: 0.15), value: caption)
            .accessibilityLabel(caption.sentence)
            .accessibilityIdentifier("assistant.live.answer")
    }

    private func failureView(_ failure: LiveConversation.Failure) -> some View {
        VStack(spacing: 14) {
            Label {
                Text(verbatim: failure.message)
            } icon: {
                Image(systemName: "exclamationmark.circle.fill")
                    .foregroundStyle(.orange)
            }
            .font(.body)
            .accessibilityIdentifier("assistant.live.error")
            HStack(spacing: 12) {
                Button(action: conversation.retry) {
                    Text("다시 시도")
                        .foregroundStyle(Color(.systemBackground))
                }
                .buttonStyle(.borderedProminent)
                    .accessibilityIdentifier("assistant.live.retry")
                if failure.kind == .microphone {
                    Button("설정 열기") {
                        if let url = URL(string: UIApplication.openSettingsURLString) { UIApplication.shared.open(url) }
                    }
                    .buttonStyle(.bordered)
                }
            }
            .controlSize(.large)
        }
    }

    // MARK: Controls

    private var controls: some View {
        HStack(alignment: .top, spacing: 36) {
            control(conversation.isMuted ? "마이크 켜기" : "마이크 끄기",
                    caption: conversation.isMuted ? "음소거됨" : "마이크",
                    symbol: conversation.isMuted ? "mic.slash.fill" : "mic.fill",
                    id: "assistant.live.mute", isOn: conversation.isMuted, action: conversation.toggleMute)
            control(showsTranscript ? "대화 내용 숨기기" : "대화 내용 보기",
                    caption: "대화 내용",
                    symbol: showsTranscript ? "text.bubble.fill" : "text.bubble",
                    id: "assistant.live.transcript", isOn: showsTranscript) { showsTranscript.toggle() }
            control("대화 끝내기", caption: "끝내기", symbol: "xmark", id: "assistant.live.end", isOn: false) {
                dismiss()
            }
        }
    }

    private func control(_ label: String, caption: String, symbol: String, id: String, isOn: Bool,
                         action: @escaping () -> Void) -> some View {
        VStack(spacing: 6) {
            Button(action: action) {
                Image(systemName: symbol)
                    .font(.title2)
                    .frame(width: 44, height: 44)
                    .contentTransition(.symbolEffect(.replace))
                    .foregroundStyle(.primary)
            }
            .buttonStyle(.glass)
            .buttonBorderShape(.circle)
            .controlSize(.large)
            .accessibilityLabel(label)
            .accessibilityAddTraits(isOn ? .isSelected : [])
            .accessibilityIdentifier(id)
            Text(caption)
                .font(.subheadline)
                .foregroundStyle(Color.secondaryText)
                .accessibilityHidden(true)
        }
    }
}

// MARK: - Orb

/// The assistant's presence: a soft clay blob that breathes with the owner's voice while listening and with its
/// own words while speaking. Reduce Motion keeps it still and lets only its opacity follow the same energy.
private struct LiveOrb: View {
    let conversation: LiveConversation
    let diameter: CGFloat
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        Button(action: conversation.tapOrb) {
            TimelineView(.animation) { context in
                let energy = energy(at: context.date)
                if reduceMotion {
                    Circle()
                        .fill(Color.assistantAccent.gradient)
                        .opacity(0.55 + 0.45 * energy)
                } else {
                    blob(time: context.date.timeIntervalSinceReferenceDate, energy: energy)
                }
            }
            .saturation(0.55)
            .frame(width: diameter, height: diameter)
            .contentShape(.circle)
        }
        .buttonStyle(.plain)
        .accessibilityLabel("\(AssistantIdentity.name)")
        .accessibilityValue(accessibilityValue)
        .accessibilityHint(accessibilityHint)
        .accessibilityIdentifier("assistant.live.orb")
    }

    private var accessibilityValue: String {
        switch conversation.phase {
        case .listening: "듣는 중"
        case .thinking: "생각하는 중"
        case .speaking: "말하는 중"
        case .paused: "일시정지"
        case .starting: "준비 중"
        case .failed: "오류"
        }
    }

    private var accessibilityHint: String {
        switch conversation.phase {
        case .speaking: "말을 멈추고 다시 들어요"
        case .listening: "지금까지 들은 말로 물어봐요"
        case .paused: "다시 들어요"
        case .failed: "다시 시도해요"
        case .thinking where conversation.isAnswerPending: "기다리기를 멈춰요. 맡긴 일은 계속 처리해요"
        case .starting, .thinking: ""
        }
    }

    /// 0...1: the mic level while listening, the assistant's voice level while speaking, a slow swell while thinking.
    private func energy(at date: Date) -> Double {
        switch conversation.phase {
        case .listening: min(conversation.level * 1.4, 1)
        case .speaking: max(0.25, conversation.speechLevel)
        case .thinking: 0.35 + 0.2 * sin(date.timeIntervalSinceReferenceDate * 2.4)
        case .starting: 0.2
        case .paused, .failed: 0
        }
    }

    private var speed: Double {
        switch conversation.phase {
        case .thinking: 2.2
        case .speaking: 1.4
        case .listening, .starting: 1
        case .paused, .failed: 0.35
        }
    }

    private func blob(time: TimeInterval, energy: Double) -> some View {
        let lobes: [(phase: Double, rate: Double, tone: Double)] = [(0, 0.9, 0), (2.1, 1.3, 0.25), (4.2, 0.7, -0.2), (1.0, 1.7, 0.1)]
        let t = time * speed
        return Canvas { context, size in
            let radius = min(size.width, size.height) / 2
            let center = CGPoint(x: size.width / 2, y: size.height / 2)
            for lobe in lobes {
                let wobble = 0.09 + 0.12 * energy
                let r = radius * (0.66 + 0.06 * sin(t * lobe.rate + lobe.phase) + 0.1 * energy)
                let offset = CGPoint(x: cos(t * lobe.rate * 0.8 + lobe.phase) * radius * wobble,
                                     y: sin(t * lobe.rate + lobe.phase * 1.3) * radius * wobble)
                let rect = CGRect(x: center.x + offset.x - r, y: center.y + offset.y - r, width: r * 2, height: r * 2)
                let tone = lobe.tone >= 0 ? Color.white.opacity(lobe.tone) : Color.black.opacity(-lobe.tone)
                context.fill(Path(ellipseIn: rect), with: .color(.assistantAccent.opacity(0.75)))
                context.fill(Path(ellipseIn: rect), with: .color(tone))
            }
        }
        .blur(radius: diameter * 0.07)
        .overlay {
            Circle()
                .fill(RadialGradient(colors: [.white.opacity(0.35), .clear], center: UnitPoint(x: 0.35, y: 0.3),
                                     startRadius: 0, endRadius: diameter * 0.3))
                .scaleEffect(0.78 + 0.08 * energy)
                .blendMode(.plusLighter)
        }
        .scaleEffect(1 + 0.12 * energy)
    }
}

private struct LiveBackground: View {
    @Environment(\.colorScheme) private var colorScheme

    var body: some View {
        ZStack {
            colorScheme == .dark ? Color.black : Color(red: 0.93, green: 0.92, blue: 0.91)
            RadialGradient(colors: [Color.assistantAccent.opacity(colorScheme == .dark ? 0.22 : 0.14), .clear],
                           center: UnitPoint(x: 0.5, y: 0.42), startRadius: 0, endRadius: 380)
                .saturation(0.6)
        }
        .ignoresSafeArea()
    }
}

// MARK: - Transcript

private struct LiveTranscript: View {
    let turns: [LiveTurn]
    /// The download tip appears once, and only while every installed Korean voice is default quality.
    @AppStorage("assistant.live.voiceHintShown") private var voiceHintShown = false
    @State private var showsVoiceHint = false

    var body: some View {
        ScrollViewReader { proxy in
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 18) {
                    if turns.isEmpty {
                        Text("아직 나눈 대화가 없어요. 말씀하시면 여기에 글자로 남아요.")
                            .font(.subheadline)
                            .foregroundStyle(Color.secondaryText)
                            .frame(maxWidth: .infinity)
                            .multilineTextAlignment(.center)
                            .padding(.top, 24)
                    }
                    ForEach(Array(turns.enumerated()), id: \.offset) { index, turn in
                        row(turn)
                            .id(index)
                    }
                    if showsVoiceHint {
                        Label {
                            Text(verbatim: "설정 > 손쉬운 사용 > 읽기 및 말하기 > 음성 > 한국어에서 유나(프리미엄)를 받으면 목소리가 더 자연스러워져요")
                        } icon: {
                            Image(systemName: "info.circle")
                        }
                        .font(.subheadline)
                        .foregroundStyle(Color.secondaryText)
                        .accessibilityIdentifier("assistant.live.voiceHint")
                    }
                    Text("\(AssistantIdentity.name)가 틀릴 수 있어요")
                        .font(.footnote)
                        .foregroundStyle(Color.secondaryText)
                        .frame(maxWidth: .infinity)
                        .id("end")
                }
                .padding(.horizontal, 20)
                .padding(.vertical, 8)
            }
            .scrollIndicators(.hidden)
            .defaultScrollAnchor(.bottom)
            .onChange(of: turns.count) {
                withAnimation { proxy.scrollTo("end", anchor: .bottom) }
            }
            .onAppear {
                showsVoiceHint = !voiceHintShown && !LiveSpeaker.hasNaturalVoice
                voiceHintShown = true
            }
        }
        .accessibilityIdentifier("assistant.live.transcriptList")
    }

    @ViewBuilder
    private func row(_ turn: LiveTurn) -> some View {
        switch turn.role {
        case .owner:
            HStack {
                Spacer(minLength: 48)
                Text(turn.text)
                    .padding(.horizontal, 14)
                    .padding(.vertical, 10)
                    .background(.tint.opacity(0.15), in: .inner)
                    .textSelection(.enabled)
            }
        case .assistant:
            let text = Self.rendered(turn.text)
            VStack(alignment: .leading, spacing: 10) {
                Text(text)
                    .textSelection(.enabled)
                    .accessibilityLabel(Text("\(AssistantIdentity.name): \(Text(text))"))
                if let agent = turn.agent, agent.hasDetail(showingStatus: true) {
                    AgentRunDetail(record: agent, isLive: true)
                }
                ForEach(turn.items) { item in
                    WorkCard(item: item, isPrimary: false)
                        .padding(12)
                        .background(AppPalette.card, in: .inner)
                }
            }
        }
    }

    private static func rendered(_ text: String) -> AttributedString {
        let options = AttributedString.MarkdownParsingOptions(interpretedSyntax: .inlineOnlyPreservingWhitespace)
        return (try? AttributedString(markdown: SpokenTurn.escapingMaskedNames(text), options: options))
            ?? AttributedString(text)
    }
}
