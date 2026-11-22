import SwiftUI

/// One conversation as a scrolling transcript: the owner's questions, the assistant's answers with their cards, and
/// the row that stands in while an answer is on its way or did not arrive.
struct AssistantTranscript: View {
    let conversation: ConversationStore.Conversation
    let isAnswering: Bool
    /// Turns newer than this happened while the sheet was open: their question moves to the top of the view and
    /// their answer is written out once. Saved turns rest, and the transcript opens at its end.
    let liveSince: Date
    @Binding var revealed: Set<ConversationStore.Turn.ID>
    let retry: () -> Void
    /// The height messages can use between the navigation bar and the composer.
    @State private var viewport: CGFloat = 0
    @Environment(AppModel.self) private var app
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    private static let exchange = "assistant.exchange"
    private static let spacing: CGFloat = 20

    /// The last question and everything after it. Earlier turns sit above as plain rows.
    private var exchangeStart: Int {
        conversation.turns.lastIndex { $0.role == .owner } ?? conversation.turns.endIndex
    }

    /// One card in the whole conversation takes the prominent button: the first still waiting.
    private var primaryProposal: AgentProposal.ID? {
        conversation.turns.flatMap { $0.agent?.proposals ?? [] }
            .first { AgentCenter.shared.standing(of: $0, at: .now) == .open }?.id
    }

    private var isLive: Bool {
        conversation.turns[exchangeStart...].first.map { $0.date > liveSince } ?? false
    }

    var body: some View {
        ScrollViewReader { proxy in
            ScrollView {
                LazyVStack(alignment: .leading, spacing: Self.spacing) {
                    ForEach(conversation.turns[..<exchangeStart]) { row($0) }
                    if exchangeStart < conversation.turns.endIndex {
                        VStack(alignment: .leading, spacing: Self.spacing) {
                            ForEach(conversation.turns[exchangeStart...]) { row($0) }
                            pending
                        }
                        .padding(.vertical, 12)
                        // A live exchange fills the view, so its question can sit at the top and the answer is
                        // written below it without anything moving when it lands.
                        .frame(minHeight: isLive ? viewport : nil, alignment: .top)
                        .id(Self.exchange)
                    }
                }
                .padding(.horizontal, 16)
            }
            // A saved transcript opens at its end. A live one starts at its question, and stays there as the answer
            // grows below: until something scrolls, the view returns to this anchor whenever its content changes size.
            .defaultScrollAnchor(isLive ? .top : .bottom, for: .initialOffset)
            .scrollDismissesKeyboard(.interactively)
            // `containerSize` is the room left between the bars; `visibleRect` is the whole frame, bars included.
            .onScrollGeometryChange(for: Viewport.self) { geometry in
                Viewport(height: geometry.containerSize.height,
                         showsEnd: geometry.visibleRect.maxY - geometry.contentInsets.bottom >= geometry.contentSize.height - 1)
            } action: { old, new in
                viewport = new.height
                // The keyboard took room from a saved transcript resting at its end: keep the end in view.
                if new.height < old.height, old.showsEnd, !isLive {
                    withAnimation(reduceMotion ? nil : .easeOut(duration: 0.25)) { scrollToEnd(proxy) }
                }
            }
            .onChange(of: conversation.turns[exchangeStart...].first?.id) {
                guard isLive else { return }
                withAnimation(reduceMotion ? nil : .snappy) { proxy.scrollTo(Self.exchange, anchor: .top) }
            }
        }
        // Keyed by the words too: the answer of a run that went on at the server arrives in a turn already shown.
        .onChange(of: conversation.turns.last.map { [$0.id.uuidString, $0.text] }) {
            if let last = conversation.turns.last, last.role == .assistant, !last.text.isEmpty {
                AccessibilityNotification.Announcement(last.text).post()
            }
        }
        .task(id: app.dataVersion) {
            await ConversationStore.shared.refreshCards()
            await ConversationStore.shared.refreshRuns()
        }
    }

    private func scrollToEnd(_ proxy: ScrollViewProxy) {
        if exchangeStart < conversation.turns.endIndex {
            proxy.scrollTo(Self.exchange, anchor: .bottom)
        } else if let last = conversation.turns.last {
            proxy.scrollTo(last.id, anchor: .bottom)
        }
    }

    @ViewBuilder
    private func row(_ turn: ConversationStore.Turn) -> some View {
        switch turn.role {
        case .owner:
            Text(turn.text)
                .textSelection(.enabled)
                .padding(.horizontal, 14)
                .padding(.vertical, 10)
                .background(.tint.opacity(0.15), in: .inner)
                .frame(maxWidth: .infinity, alignment: .trailing)
                .padding(.leading, 48)
        case .assistant:
            // The answer of a run that goes on at the server has no words yet; how the run stands takes their place.
            if turn.text.isEmpty, let agent = turn.agent {
                AgentRunDetail(record: agent, primaryID: primaryProposal)
            } else {
                answer(turn)
            }
        case .failure:
            UnansweredNotice(text: turn.text, retry: turn.id == conversation.turns.last?.id ? retry : nil)
        }
    }

    private func answer(_ turn: ConversationStore.Turn) -> some View {
        let isFresh = Binding(
            get: { turn.id == conversation.turns.last?.id && turn.date > liveSince && !revealed.contains(turn.id) },
            set: { if !$0 { revealed.insert(turn.id) } }
        )
        let text = AssistantSheet.rendered(turn.text)
        return VStack(alignment: .leading, spacing: 10) {
            GeneratedText(text, isFresh: isFresh)
                .textSelection(.enabled)
                .accessibilityLabel(Text("\(AssistantIdentity.name): \(Text(text))"))
            // Written posts and replies get pasted elsewhere, so every answer can be copied in one tap.
            Button("복사하기", systemImage: "doc.on.doc") {
                UIPasteboard.general.string = turn.text
                app.showToast("복사했어요", seconds: 2)
            }
            .font(.subheadline.weight(.semibold))
            .buttonStyle(.bordered)
            .opacity(isFresh.wrappedValue ? 0 : 1)
            .accessibilityIdentifier("assistant.copy")
            // The items the answer names, each with its one next action. They stay hidden until the text has settled.
            ForEach(turn.items) { item in
                WorkCard(item: item, isPrimary: false)
                    .buttonStyle(DisclosureLinkStyle())
                    .padding(16)
                    .background(AppPalette.card, in: .card)
            }
            .opacity(isFresh.wrappedValue ? 0 : 1)
            // What the answer's run did and what it asks the owner to approve, hidden like the cards until the
            // text has settled.
            if let agent = turn.agent, agent.hasDetail(showingStatus: true) {
                AgentRunDetail(record: agent, primaryID: primaryProposal)
                    .opacity(isFresh.wrappedValue ? 0 : 1)
            }
        }
        .animation(.default, value: isFresh.wrappedValue)
    }

    /// What follows the last turn: the waiting line, or a way to ask again when a question was left without an answer.
    @ViewBuilder
    private var pending: some View {
        if isAnswering {
            GeneratingIndicator(label: "\(AssistantIdentity.name)가 현황을 보고 있어요")
        } else if conversation.turns.last?.role == .owner {
            UnansweredNotice(text: "답을 받지 못했어요.", retry: retry)
        }
    }
}

private struct Viewport: Equatable {
    let height: CGFloat
    let showsEnd: Bool
}

/// A question without an answer: what happened, in the label color with a symbol, and 다시 시도 while it is still the
/// last thing in the conversation.
private struct UnansweredNotice: View {
    let text: String
    let retry: (() -> Void)?

    var body: some View {
        Label {
            VStack(alignment: .leading, spacing: 8) {
                Text(verbatim: text)
                if let retry {
                    Button("다시 시도", action: retry)
                        .buttonStyle(.bordered)
                        .controlSize(.large)
                        .accessibilityIdentifier("assistant.retry")
                }
            }
        } icon: {
            Image(systemName: "exclamationmark.circle")
                .foregroundStyle(Color.secondaryText)
        }
        .labelStyle(TopAlignedIconLabelStyle())
    }
}

/// Keeps the status symbol next to the first line of the notice.
private struct TopAlignedIconLabelStyle: LabelStyle {
    func makeBody(configuration: Configuration) -> some View {
        HStack(alignment: .firstTextBaseline, spacing: 10) {
            configuration.icon
                .alignmentGuide(.firstTextBaseline) { $0[VerticalAlignment.center] + 5 }
            configuration.title
        }
    }
}

/// Outside a List a navigation link draws no disclosure mark, so a card that only opens a screen gets one here.
/// Cards with an action button style their own link and are not affected.
private struct DisclosureLinkStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        HStack(spacing: 8) {
            configuration.label
            Image(systemName: "chevron.forward")
                .font(.footnote.weight(.semibold))
                .foregroundStyle(.tertiary)
                .accessibilityHidden(true)
        }
        .contentShape(.rect)
        .opacity(configuration.isPressed ? 0.6 : 1)
    }
}
