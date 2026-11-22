import Combine
import SwiftUI

extension AgentProposal {
    /// The moment a yes stops being possible, worded like every other deadline in the app.
    var due: CardDue? {
        expiry.map { CardDue(at: $0.ISO8601Format(), prefix: "승인", suffix: "까지", missed: "기한 지남") }
    }

    func badge(for standing: AgentCenter.ProposalStanding) -> Status {
        switch standing {
        case .open where isInvoiceFile: Status(text: "파일 필요", tone: .attention)
        case .open where needsOwnerWords: Status(text: "내용 필요", tone: .attention)
        case .open: Status(text: "승인 대기", tone: .attention)
        case .approved: Status(text: "승인함", tone: .done)
        case .dismissed: Status(text: "하지 않기로 함", tone: .neutral)
        case .expired: Status(text: "만료", tone: .neutral)
        case .closed: Status(text: "끝난 제안", tone: .neutral)
        }
    }

    /// What an open card promises. A card that lacks its value or its file cannot run on a yes, so it says
    /// what the owner has to give first.
    var openNote: String {
        if isInvoiceFile {
            return "아직 등록한 송장은 없어요. 파일은 휴대폰에 남기지 않아서 같은 파일을 다시 골라야 등록할 수 있어요."
        }
        guard needsOwnerWords else { return "아직 바꾼 것은 없어요. 승인하시면 그때 처리해요." }
        return tool == "register_invoice"
            ? "아직 바꾼 것은 없어요. 송장번호를 알려 주시면 등록할게요."
            : "아직 바꾼 것은 없어요. 기관의 답을 알려 주시면 적어 둘게요."
    }
}

/// One thing the assistant asks the owner to settle. Until then it changes nothing and says so. Most cards take
/// a yes; a card that lacks a value takes that value in the owner's own words, and a card for an imported file
/// asks for the file again. After a yes the card shows the step that ran, with its undo while the server still
/// allows one.
struct AgentProposalCard: View {
    let proposal: AgentProposal
    /// Only one card on a screen takes the prominent button.
    var isPrimary = true
    @State private var center = AgentCenter.shared
    @State private var pressed: Choice?
    @State private var value = ""
    @Environment(AppModel.self) private var app
    @Environment(\.pickInvoiceFile) private var pickInvoiceFile
    @Environment(\.dynamicTypeSize) private var dynamicTypeSize

    private enum Choice {
        case settle
        case dismiss
    }

    private var isBusy: Bool { app.isRunning(AgentCenter.runID(proposal)) }

    var body: some View {
        TimelineView(.everyMinute) { context in
            let standing = center.standing(of: proposal, at: context.date)
            VStack(alignment: .leading, spacing: 10) {
                header(standing)
                Text(verbatim: proposal.title)
                    .font(.headline)
                if !proposal.reason.isEmpty {
                    Text(verbatim: proposal.reason)
                        .font(.subheadline)
                        .foregroundStyle(Color.secondaryText)
                }
                preview
                outcome(standing)
            }
            .padding(.vertical, 4)
            .accessibilityElement(children: .contain)
            .accessibilityIdentifier("agent.proposal.\(proposal.id)")
        }
    }

    private func header(_ standing: AgentCenter.ProposalStanding) -> some View {
        let layout = dynamicTypeSize.isAccessibilitySize
            ? AnyLayout(VStackLayout(alignment: .leading, spacing: 4))
            : AnyLayout(HStackLayout(alignment: .center))
        return layout {
            StatusBadge(proposal.badge(for: standing))
            if !dynamicTypeSize.isAccessibilitySize {
                Spacer(minLength: 8)
            }
            if standing == .open, let due = proposal.due {
                DueLabel(due: due)
            }
        }
    }

    private var preview: some View {
        let needed = proposal.evidenceNeeded.isEmpty
            ? [] : [CardField(label: "필요한 것", value: proposal.evidenceNeeded.joined(separator: " · "))]
        let rows = Array((proposal.preview + needed).enumerated())
        return Group {
            if dynamicTypeSize.isAccessibilitySize {
                VStack(alignment: .leading, spacing: 8) {
                    ForEach(rows, id: \.offset) { _, row in
                        VStack(alignment: .leading, spacing: 0) {
                            Text(verbatim: row.label)
                                .foregroundStyle(Color.secondaryText)
                            Text(verbatim: row.value)
                        }
                        .accessibilityElement(children: .combine)
                    }
                }
            } else {
                Grid(alignment: .leadingFirstTextBaseline, horizontalSpacing: 12, verticalSpacing: 6) {
                    ForEach(rows, id: \.offset) { _, row in
                        GridRow {
                            Text(verbatim: row.label)
                                .foregroundStyle(Color.secondaryText)
                            Text(verbatim: row.value)
                                .textSelection(.enabled)
                        }
                    }
                }
            }
        }
        .font(.subheadline)
    }

    @ViewBuilder
    private func outcome(_ standing: AgentCenter.ProposalStanding) -> some View {
        switch standing {
        case .open:
            open
        case .approved(let step):
            if let step {
                AgentStepRow(step: step)
            } else {
                Label("승인한 대로 처리했어요.", systemImage: "checkmark")
                    .font(.subheadline.weight(.medium))
            }
        case .dismissed:
            note("하지 않기로 했어요. 바뀐 것은 없어요.")
        case .expired:
            note("기한이 지난 제안이에요. 바뀐 것은 없어요.")
        case .closed:
            note("이미 정했거나 기한이 지난 제안이에요.")
        }
    }

    @ViewBuilder
    private var open: some View {
        if let reply = center.replies[proposal.id] {
            Text(verbatim: reply)
                .font(.subheadline)
                .accessibilityIdentifier("agent.proposal.reply.\(proposal.id)")
        }
        note(proposal.openNote)
        if proposal.isInvoiceFile {
            actions("파일 다시 고르기", identifier: "repick", isAvailable: pickInvoiceFile != nil) {
                pickInvoiceFile?(proposal.id)
            }
        } else if proposal.needsOwnerWords {
            BK25VoiceField(text: $value, prompt: proposal.evidenceNeeded.joined(separator: ", "))
            actions("알려 주기", identifier: "supply",
                    isAvailable: !value.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty) {
                settle { await center.supply(value, for: proposal, app: app) }
            }
        } else {
            actions("승인하기", identifier: "approve") {
                settle { await center.approve(proposal, app: app) }
            }
        }
    }

    private func note(_ text: String) -> some View {
        Text(verbatim: text)
            .font(.subheadline)
            .foregroundStyle(Color.secondaryText)
    }

    /// The card's two answers: the one that settles it, and 하지 않기.
    private func actions(_ title: String, identifier: String, isAvailable: Bool = true,
                         settle: @escaping () -> Void) -> some View {
        let layout = dynamicTypeSize.isAccessibilitySize
            ? AnyLayout(VStackLayout(spacing: 8)) : AnyLayout(HStackLayout(spacing: 10))
        return layout {
            settleButton(title, identifier: identifier, isAvailable: isAvailable, action: settle)
            Button {
                pressed = .dismiss
                Task {
                    await center.dismiss(proposal, app: app)
                    pressed = nil
                }
            } label: {
                BusyLabel(title: "하지 않기", isBusy: isBusy && pressed == .dismiss)
                    .font(.subheadline.weight(.semibold))
                    .frame(maxWidth: .infinity, minHeight: 40)
            }
            .buttonStyle(.bordered)
            .accessibilityLabel("\(proposal.title) 하지 않기")
            .accessibilityIdentifier("agent.proposal.dismiss.\(proposal.id)")
        }
        .disabled(isBusy)
    }

    @ViewBuilder
    private func settleButton(_ title: String, identifier: String, isAvailable: Bool,
                              action: @escaping () -> Void) -> some View {
        let button = Button(action: action) {
            BusyLabel(title: title, isBusy: isBusy && pressed == .settle, isProminent: isPrimary)
                .font(.subheadline.weight(.semibold))
                .frame(maxWidth: .infinity, minHeight: 40)
        }
        .disabled(!isAvailable)
        .accessibilityLabel("\(proposal.title) \(title)")
        .accessibilityIdentifier("agent.proposal.\(identifier).\(proposal.id)")
        if isPrimary {
            button.buttonStyle(.borderedProminent)
        } else {
            button.buttonStyle(.bordered)
        }
    }

    private func settle(_ work: @escaping () async -> Void) {
        pressed = .settle
        Task {
            await work()
            pressed = nil
        }
    }
}

/// A proposal on two or three lines, for lists that open the full card.
struct AgentProposalRow: View {
    let proposal: AgentProposal

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack(alignment: .firstTextBaseline, spacing: 6) {
                // The dot asks for a decision, so a proposal past its time loses it and keeps its gray deadline.
                TimelineView(.everyMinute) { context in
                    if proposal.expiry.map({ $0 > context.date }) ?? true {
                        Circle()
                            .fill(Color.pendingOrange)
                            .frame(width: 7, height: 7)
                            .accessibilityHidden(true)
                    }
                }
                Text(verbatim: proposal.title)
                    .font(.headline)
            }
            if !proposal.reason.isEmpty {
                Text(verbatim: proposal.reason)
                    .font(.subheadline)
                    .foregroundStyle(Color.secondaryText)
                    .lineLimit(2)
            }
            if let due = proposal.due {
                DueLabel(due: due)
            }
        }
        .padding(.vertical, 4)
    }
}

/// Today's 비서 제안: what waits for the owner, each row opening its card.
struct AgentProposalSection: View {
    @State private var center = AgentCenter.shared

    var body: some View {
        let proposals = center.waiting
        if !proposals.isEmpty || center.proposalsFailed {
            CardSection {
                ForEach(proposals.prefix(3)) { proposal in
                    NavigationLink {
                        AgentProposalListView(first: proposal.id)
                    } label: {
                        AgentProposalRow(proposal: proposal)
                    }
                    .accessibilityIdentifier("agent.proposal.row.\(proposal.id)")
                }
                if proposals.count > 3 {
                    NavigationLink("모두 보기") { AgentProposalListView() }
                        .accessibilityIdentifier("agent.proposals.all")
                }
                if center.proposalsFailed {
                    LabeledContent {
                        Button("다시 시도") { Task { await center.loadProposals() } }
                    } label: {
                        Text("\(AssistantIdentity.name) 제안을 불러오지 못했어요")
                            .foregroundStyle(Color.secondaryText)
                    }
                }
            } header: {
                // A failed load knows no count, so the header gives none.
                Text(proposals.isEmpty ? "\(AssistantIdentity.name) 제안" : "\(AssistantIdentity.name) 제안 \(proposals.count)건")
                    .font(.headline)
                    .foregroundStyle(Color.primary)
                    .textCase(nil)
                    .accessibilityIdentifier("agent.proposals.header")
            }
        }
    }
}

/// The assistant sheet's one line for proposals that are not in the conversation on screen.
struct AgentProposalBanner: View {
    let count: Int

    var body: some View {
        NavigationLink {
            AgentProposalListView(onPage: false)
        } label: {
            HStack(spacing: 8) {
                Circle()
                    .fill(Color.pendingOrange)
                    .frame(width: 7, height: 7)
                    .accessibilityHidden(true)
                Text("기다리는 제안 \(count)건")
                    .font(.subheadline.weight(.semibold))
                    .foregroundStyle(Color.primary)
                Spacer(minLength: 8)
                Image(systemName: "chevron.forward")
                    .font(.footnote.weight(.semibold))
                    .foregroundStyle(.tertiary)
                    .accessibilityHidden(true)
            }
            .padding(.horizontal, 14)
            .frame(minHeight: 44)
            .background(AppPalette.card, in: .card)
            .contentShape(.rect)
        }
        .buttonStyle(.plain)
        .padding(.horizontal, 16)
        .padding(.bottom, 4)
        .accessibilityIdentifier("agent.proposals.banner")
    }
}

/// Every waiting proposal as a full card. A proposal settled here stays in place with its result.
struct AgentProposalListView: View {
    /// The proposal the owner tapped, shown first.
    var first: AgentProposal.ID?
    /// False inside the assistant sheet, which keeps its own background.
    var onPage = true
    /// Loads like every other server-backed screen, so an outage shows the connection line and the screen
    /// reconnects by itself.
    @State private var loader = Loader<[AgentProposal]>()
    @State private var center = AgentCenter.shared
    @State private var shown: [AgentProposal] = []
    /// A TimelineView around the list loops with the collapsing title, so a minute timer moves the clock here.
    @State private var now = Date.now
    @Environment(AppModel.self) private var app

    var body: some View {
        // Read here: the content runs in another view's body, where a change to `shown` would redraw nothing.
        let shown = shown
        LoadableContent(loader: loader, retry: load) { _ in
            if !shown.isEmpty {
                let primary = shown.first { center.standing(of: $0, at: now) == .open }?.id
                List {
                    ForEach(shown) { proposal in
                        CardSection {
                            AgentProposalCard(proposal: proposal, isPrimary: proposal.id == primary)
                        }
                    }
                }
                .cardList(onPage: onPage)
                .scrollDismissesKeyboard(.interactively)
                .refreshable { await load() }
                .onReceive(Timer.publish(every: 60, on: .main, in: .common).autoconnect()) { now = $0 }
            } else {
                ContentUnavailableView {
                    Label("기다리는 제안이 없어요", systemImage: "checkmark.circle")
                } description: {
                    Text(verbatim: "\(AssistantIdentity.name)가 승인받을 일이 생기면 여기에 올려요.")
                        .foregroundStyle(Color.secondaryText)
                }
                .accessibilityIdentifier("agent.proposals.empty")
            }
        }
        .navigationTitle("\(AssistantIdentity.name) 제안")
        .navigationBarTitleDisplayMode(.inline)
        .invoiceFilePicking(onPage: onPage)
        .task(id: app.dataVersion) { await load() }
        .onChange(of: center.waiting, initial: true) { _, listed in include(listed) }
    }

    private func include(_ listed: [AgentProposal]) {
        let new = listed.filter { proposal in !shown.contains { $0.id == proposal.id } }
        shown = shown.isEmpty
            ? new.filter { $0.id == first } + new.filter { $0.id != first }
            : shown + new
    }

    private func load() async {
        await loader.load { try await RoundupAPI.agentProposals() }
        if loader.errorMessage == nil, let listed = loader.value { center.adopt(listed) }
    }
}
