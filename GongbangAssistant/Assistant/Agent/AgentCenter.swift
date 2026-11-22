import Foundation
import Observation

/// What one agent run did or proposed, kept with the answer it belongs to.
struct AgentRecord: Codable, Hashable {
    let runID: String
    var status: AgentRunStatus
    var steps: [AgentStep]
    var proposals: [AgentProposal]

    /// True when a step changed a row, so the screens that show it must reload.
    var changedData: Bool { steps.contains { $0.ran && !$0.isRead } }
}

extension AgentRecord {
    init(_ run: AgentRun) {
        self.init(runID: run.id, status: run.status, steps: run.steps, proposals: run.proposals)
    }
}

/// One answer to the owner: from the agent while it is on, from `/ask` otherwise.
struct AssistantAnswer {
    let text: String
    let items: [WorkItem]
    /// Nil when `/ask` answered, which changes nothing.
    let agent: AgentRecord?
}

extension AgentStep {
    private static let reads: Set<String> = [
        "find_bookings", "find_orders", "find_shipments", "find_inquiries", "find_sessions", "read_calendar",
        "read_fact_cards", "read_rules", "find_quotes", "recall",
    ]

    /// A lookup changes nothing, so answers list lookups on one line instead of a row each.
    var isRead: Bool { decision == .auto && Self.reads.contains(tool) }

    /// The step ran: at once, or later when the owner approved its proposal. An approved step keeps the
    /// decision `proposed`, so there it shows in that it can be, or has been, undone.
    var ran: Bool { decision == .auto || undoable || undone }
}

extension AgentProposal {
    private static let valueTools: Set<String> = ["register_invoice", "record_quote_outcome"]

    func wasRaised(by step: AgentStep) -> Bool { stepId == step.id }

    /// The one proposal an imported carrier export leaves behind. It registers nothing without the file itself,
    /// because the server kept only the file's fingerprint.
    var isInvoiceFile: Bool { tool == "register_invoice" && target == nil }

    /// Approving cannot run a proposal that lacks the value it would write: a tracking number nobody gave, or
    /// an institution's answer to a quote. The owner says it instead, as a turn of their own.
    var needsOwnerWords: Bool { !isInvoiceFile && Self.valueTools.contains(tool) && !evidenceNeeded.isEmpty }

    /// The owner's own turn that names this proposal's row and gives the value it waits for.
    func ownerTurn(saying value: String) -> String {
        [target?.label, evidenceNeeded.first, value].compactMap { $0 }.joined(separator: " ")
    }
}

extension AgentSettings {
    mutating func apply(_ change: AgentSettingsChange) {
        switch change {
        case .mode(let mode): self.mode = mode
        case .proactive(let isOn): proactive = isOn
        case .tool(let name, let mode):
            if let index = tools.firstIndex(where: { $0.tool == name }) { tools[index].mode = mode }
        case .dailyCap(let cap): dailyCap = cap
        case .quietHours(let hours): quietHours = hours
        }
    }
}

/// The assistant agent's shared state: the owner's switches, the proposals waiting for a yes, and what was
/// decided on this device. The chat sheet, the live voice mode, Today, and the settings screen all read it.
@MainActor
@Observable
final class AgentCenter {
    static let shared = AgentCenter()

    enum ProposalStanding: Equatable {
        case open
        /// The step the approval ran comes with the server's answer; a proposal approved elsewhere has none here.
        case approved(AgentStep?)
        case dismissed
        case expired
        /// No longer listed as open, and this device did not decide it.
        case closed
    }

    /// The owner's switches as last read; nil until the server has answered once.
    private(set) var settings: AgentSettings?
    /// Why the last change of a switch was refused, in the server's words.
    private(set) var settingsWarning: String?
    /// Open proposals as the server lists them, soonest to expire first.
    private(set) var proposals: [AgentProposal] = []
    private(set) var proposalsFailed = false
    private var hasLoadedProposals = false
    private var decided: [AgentProposal.ID: ProposalStanding] = [:]
    /// What the assistant answered when the owner gave a proposal its missing value and that did not settle it.
    private(set) var replies: [AgentProposal.ID: String] = [:]
    /// Steps as an undo on this device left them, until the list that shows them has reloaded.
    private var changedSteps: [AgentStep.ID: AgentStep] = [:]
    @ObservationIgnored private var supplied: [AgentProposal.ID: (turn: String, requestID: String)] = [:]
    @ObservationIgnored private var settingsWork: Task<Void, Never>?
    @ObservationIgnored private var waitingSettingsChanges = 0

    static func runID(_ proposal: AgentProposal) -> String { "agent.proposal.\(proposal.id)" }
    static func runID(_ step: AgentStep) -> String { "agent.step.\(step.id)" }

    /// Proposals still waiting for the owner: the server's open ones without those settled on this device.
    var waiting: [AgentProposal] { proposals.filter { decided[$0.id] == nil } }

    // MARK: Answering

    /// Answers through the agent while it is on. `requestID` names this one send: the server returns the same
    /// run for the same id, so a send whose answer was lost is repeated as it is, once here and again when the
    /// caller asks again with that id. `/ask` answers only when the server itself says no run started: the agent
    /// is off, its settings cannot be read, or the server has no agent route.
    func answer(_ question: String, history: [RoundupAPI.ChatTurn], source: AgentRunSource,
                requestID: String, mayQueue: Bool = true) async throws -> AssistantAnswer {
        guard try await isOn() else { return try await ask(question, history: history) }
        var lost: any Error = ConnectionError()
        for _ in 0..<2 {
            do {
                let reply = try await RoundupAPI.agentRun(
                    question: question, history: history, source: source,
                    background: mayQueue && source == .chat && Self.namesSeveralJobs(question), requestID: requestID)
                // A mode the owner changed meanwhile is still on its way to the server.
                if waitingSettingsChanges == 0 { settings?.mode = reply.mode }
                noteRaised(reply.proposals)
                return AssistantAnswer(text: reply.answer ?? "", items: [], agent: AgentRecord(
                    runID: reply.runId, status: reply.status, steps: reply.steps, proposals: reply.proposals))
            } catch is CancellationError {
                throw CancellationError()
            } catch let error as RoundupAPIError where error.isMissing {
                settings = nil
                return try await ask(question, history: history)
            } catch let error as ConnectionError {
                lost = error
            }
        }
        throw lost
    }

    /// Several order or tracking numbers, or several lines, are several jobs: that run is left to the server,
    /// so the owner need not keep the screen open while it works through them.
    static func namesSeveralJobs(_ question: String) -> Bool {
        question.contains(where: \.isNewline) || question.matches(of: /\d{4,}/).count > 1
    }

    private func isOn() async throws -> Bool {
        if settings == nil {
            do {
                adopt(try await RoundupAPI.agentSettings())
            } catch is RoundupAPIError {
                // The server answered without settings, so no run starts. A lost connection says nothing of the sort.
            }
        }
        return settings.map { $0.mode != .off } ?? false
    }

    private func ask(_ question: String, history: [RoundupAPI.ChatTurn]) async throws -> AssistantAnswer {
        let reply = try await RoundupAPI.ask(question: question, history: history)
        return AssistantAnswer(text: reply.answer, items: reply.items, agent: nil)
    }

    // MARK: Proposals

    func loadProposals() async {
        do {
            adopt(try await RoundupAPI.agentProposals())
        } catch is CancellationError {
            return
        } catch is ConnectionError {
            // The screen's own connection line already says so, and its reconnect loads these again.
            return
        } catch {
            proposalsFailed = true
        }
    }

    /// Takes the open proposals a screen read for itself.
    func adopt(_ listed: [AgentProposal]) {
        proposals = listed
        proposalsFailed = false
        hasLoadedProposals = true
    }

    /// A run just raised these, so they are open before the next list load says so.
    func noteRaised(_ raised: [AgentProposal]) {
        let new = raised.filter { proposal in
            proposal.state == .open && !proposals.contains { $0.id == proposal.id }
        }
        guard !new.isEmpty else { return }
        proposals = (proposals + new).sorted { ($0.expiry ?? .distantFuture) < ($1.expiry ?? .distantFuture) }
    }

    func standing(of proposal: AgentProposal, at now: Date) -> ProposalStanding {
        if let standing = decided[proposal.id] { return standing }
        let listed = proposals.first { $0.id == proposal.id } ?? proposal
        switch listed.state {
        case .approved: return .approved(listed.step)
        case .dismissed: return .dismissed
        case .expired: return .expired
        case .open: break
        }
        if let expiry = proposal.expiry, expiry <= now { return .expired }
        let isListed = proposals.contains { $0.id == proposal.id }
        return !isListed && hasLoadedProposals ? .closed : .open
    }

    func approve(_ proposal: AgentProposal, app: AppModel) async {
        var approved: AgentProposal?
        let ran = await app.run(id: Self.runID(proposal)) { approved = try await RoundupAPI.approve(proposal) }
        if ran { decided[proposal.id] = .approved(approved?.step) }
        await loadProposals()
    }

    func dismiss(_ proposal: AgentProposal, app: AppModel) async {
        let dismissed = await app.run(id: Self.runID(proposal)) { try await RoundupAPI.dismiss(proposal) }
        if dismissed { decided[proposal.id] = .dismissed }
        await loadProposals()
    }

    /// Sends the value a proposal lacks as the owner's own new turn, where the server's evidence rules decide.
    /// The exchange joins the chat. The card shows the step when that turn settled the matter, and the
    /// assistant's reply when it did not.
    func supply(_ value: String, for proposal: AgentProposal, app: AppModel) async {
        let turn = proposal.ownerTurn(saying: value)
        // The same value after a lost reply is the same send, so the server does not run it twice.
        let requestID = supplied[proposal.id].flatMap { $0.turn == turn ? $0.requestID : nil } ?? UUID().uuidString
        supplied[proposal.id] = (turn, requestID)
        var answer: AssistantAnswer?
        let sent = await app.run(id: Self.runID(proposal)) { [self] in
            answer = try await self.answer(turn, history: [], source: .chat, requestID: requestID, mayQueue: false)
        }
        guard sent, let answer else { return }
        supplied[proposal.id] = nil
        ConversationStore.shared.recordExchange(turn, answer: answer)
        let settled = answer.agent?.steps.first { step in
            step.ran && step.tool == proposal.tool && step.target?.id == proposal.target?.id
        }
        if let settled {
            decided[proposal.id] = .approved(settled)
            replies[proposal.id] = nil
        } else {
            replies[proposal.id] = answer.text
        }
        await loadProposals()
    }

    /// An approved file proposal, as the invoice route answered it.
    func noteApproved(_ proposal: AgentProposal) {
        decided[proposal.id] = .approved(proposal.step)
    }

    // MARK: Undo

    func current(_ step: AgentStep) -> AgentStep { changedSteps[step.id] ?? step }

    func undo(_ step: AgentStep, app: AppModel) async {
        var result: AgentUndoResult?
        let undone = await app.run(id: Self.runID(step)) { result = try await RoundupAPI.undo(step) }
        guard undone, let result else { return }
        changedSteps[step.id] = result.step
        ConversationStore.shared.update(result.step)
        app.showToast(result.summary)
    }

    // MARK: Settings

    /// Unreadable settings leave the last known ones in place; with none, questions go to `/ask`.
    func loadSettings() async {
        guard let loaded = try? await RoundupAPI.agentSettings() else { return }
        adopt(loaded)
    }

    /// Takes freshly read settings, unless a change made here is still on its way to the server.
    func adopt(_ loaded: AgentSettings) {
        if waitingSettingsChanges == 0 { settings = loaded }
    }

    /// Shows a change at once and saves it. Changes are saved one after another, each with the revision the one
    /// before it produced. A refused change is taken back, and the server's reason is kept for the screen.
    func change(_ change: AgentSettingsChange) {
        guard var edited = settings else { return }
        edited.apply(change)
        settings = edited
        settingsWarning = nil
        waitingSettingsChanges += 1
        let earlier = settingsWork
        settingsWork = Task {
            await earlier?.value
            defer { waitingSettingsChanges -= 1 }
            guard let revision = settings?.revision else { return }
            do {
                let saved = try await RoundupAPI.saveAgentSettings(change, revision: revision)
                // A later change is still showing its own value, so only the revision moves until it lands.
                if waitingSettingsChanges == 1 { settings = saved } else { settings?.revision = saved.revision }
            } catch {
                settingsWarning = error.localizedDescription
                if let stored = try? await RoundupAPI.agentSettings() { settings = stored }
            }
        }
    }

    func rejectSetting(_ reason: String) {
        settingsWarning = reason
    }
}
