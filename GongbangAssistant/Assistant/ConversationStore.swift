import Foundation
import Observation
import os

/// The assistant's conversations, saved on this device so they outlive the sheet and a relaunch.
/// The chat sheet and the live voice mode share this one instance.
@MainActor
@Observable
final class ConversationStore {
    static let shared = ConversationStore()

    enum Role: String, Codable {
        case owner
        case assistant
        case failure
    }

    struct Turn: Identifiable, Codable {
        let id: UUID
        let role: Role
        /// Empty while the answer of a run that goes on at the server has not arrived.
        var text: String
        /// The cards an answer named, as they were when it arrived; `refreshCards` brings them up to date.
        var items: [WorkItem]
        let date: Date
        /// What the agent did or proposed for this answer; `refreshRuns` brings it up to date.
        var agent: AgentRecord?
        /// The id a question went out with. Asking it again sends the same id, so the server answers with the
        /// run it already made instead of making another.
        var requestID: String?

        /// Failed turns stay on screen but never reach the model, and neither does an answer without words yet.
        var apiTurn: RoundupAPI.ChatTurn? {
            switch role {
            case .owner: RoundupAPI.ChatTurn(role: .owner, text: text)
            case .assistant: text.isEmpty ? nil : RoundupAPI.ChatTurn(role: .assistant, text: text)
            case .failure: nil
            }
        }
    }

    struct Conversation: Identifiable, Codable {
        let id: UUID
        /// The owner's first question on one line; empty until the owner has asked something.
        var title: String
        let createdAt: Date
        var updatedAt: Date
        var turns: [Turn]

        /// The question to send again: the conversation ended on it, or on its failure.
        var unansweredQuestion: Turn? {
            let asked = turns.last?.role == .failure ? turns.dropLast().last : turns.last
            return asked?.role == .owner ? asked : nil
        }
    }

    /// Most recently used first.
    private(set) var conversations: [Conversation]
    private(set) var currentID: Conversation.ID?
    private var answering: Set<Conversation.ID> = []
    /// True while the chat sheet is on screen; a run that ends meanwhile needs no notice.
    var isChatVisible = false
    /// Set by the chat sheet when it opens. Screens reload through it when a run changed a row, and a run that
    /// ends while the sheet is closed says so with its toast.
    @ObservationIgnored weak var app: AppModel?
    /// One reader per run that goes on at the server.
    @ObservationIgnored private var following: [String: Task<Void, Never>] = [:]
    /// File work runs off the main actor, one job after another, so a later save never lands before an earlier one.
    @ObservationIgnored private var fileWork: Task<Void, Never>?

    private static let limit = 100
    private static let resumeWindow: TimeInterval = 30 * 60
    private static let followInterval: Duration = .milliseconds(1500)
    private static let directory = URL.applicationSupportDirectory.appending(path: "Conversations", directoryHint: .isDirectory)
    private nonisolated static let log = Logger(subsystem: Bundle.main.bundleIdentifier ?? "GongbangAssistant", category: "conversations")

    private static let encoder: JSONEncoder = {
        let encoder = JSONEncoder()
        encoder.dateEncodingStrategy = .iso8601
        return encoder
    }()

    private static let decoder: JSONDecoder = {
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .iso8601
        return decoder
    }()

    private init() {
        conversations = Self.load()
        // After a relaunch the newest conversation is the one to pick back up; `resume` decides if it is recent enough.
        currentID = conversations.first?.id
    }

    var current: Conversation? {
        conversations.first { $0.id == currentID }
    }

    /// True while the current conversation waits for an answer; the next question waits until it lands.
    var isAnswering: Bool {
        currentID.map(answering.contains) ?? false
    }

    /// The current conversation as `/ask` takes it, so a follow-up question keeps its context.
    var currentAPIHistory: [RoundupAPI.ChatTurn] {
        current?.turns.compactMap(\.apiTurn) ?? []
    }

    /// Adds a turn that just happened to the current conversation, starting one if there is none.
    func recordLiveTurn(role: Role, text: String, items: [WorkItem], agent: AgentRecord? = nil) {
        let turn = Turn(role: role, text: text, items: items, agent: agent)
        record(turn, in: currentID ?? begin())
        settle(turn)
    }

    /// A chat surface opened: the conversation stays if it was used in the last 30 minutes, otherwise a new one starts.
    func resume(now: Date = .now) {
        guard let current, !answering.contains(current.id),
              now.timeIntervalSince(current.updatedAt) > Self.resumeWindow else { return }
        currentID = nil
    }

    func startNew() {
        currentID = nil
    }

    func open(_ id: Conversation.ID) {
        currentID = id
    }

    func delete(_ id: Conversation.ID) {
        conversations.removeAll { $0.id == id }
        if currentID == id { currentID = nil }
        let file = Self.file(id)
        enqueue { try FileManager.default.removeItem(at: file) }
    }

    /// Sends a question in the current conversation. The reply is recorded even if the sheet closes before it lands.
    func ask(_ question: String) {
        let history = currentAPIHistory
        let id = currentID ?? begin()
        let requestID = UUID().uuidString
        record(Turn(role: .owner, text: question, items: [], requestID: requestID), in: id)
        request(question, history: history, in: id, requestID: requestID)
    }

    /// Asks the current conversation's unanswered question again, replacing its failure.
    func retry() {
        guard var conversation = current, !answering.contains(conversation.id),
              let question = conversation.unansweredQuestion else { return }
        conversation.turns.removeAll { $0.date > question.date }
        replace(conversation)
        request(question.text, history: conversation.turns.dropLast().compactMap(\.apiTurn), in: conversation.id,
                requestID: question.requestID ?? UUID().uuidString)
    }

    /// Adds an exchange that did not come from a typed question, such as approved invoice rows and what the
    /// assistant then did with them.
    func recordExchange(_ request: String, answer: AssistantAnswer) {
        let id = currentID ?? begin()
        record(Turn(role: .owner, text: request, items: []), in: id)
        let turn = Turn(role: .assistant, text: answer.text, items: answer.items, agent: answer.agent)
        record(turn, in: id)
        settle(turn)
    }

    /// Brings the current conversation's runs up to date. One still going is followed again, and one whose
    /// step can still be undone is read again, so 되돌리기 is offered only while the server allows it.
    func refreshRuns() async {
        let records = current?.turns.compactMap(\.agent) ?? []
        for record in records where record.status.isUnfinished {
            follow(record.runID)
        }
        let undoable = records.filter { record in
            !record.status.isUnfinished && record.steps.contains { $0.undoable && !$0.undone }
        }
        await withTaskGroup(of: AgentRun?.self) { group in
            for record in undoable.suffix(5) {
                group.addTask { try? await RoundupAPI.agentRun(id: record.runID) }
            }
            for await run in group {
                if let run { apply(run) }
            }
        }
    }

    /// Writes a step an undo changed into the answer that shows it.
    func update(_ step: AgentStep) {
        for conversation in conversations {
            guard let turn = conversation.turns.firstIndex(where: { turn in
                turn.agent?.steps.contains { $0.id == step.id } == true
            }), let index = conversation.turns[turn].agent?.steps.firstIndex(where: { $0.id == step.id }) else {
                continue
            }
            var changed = conversation
            changed.turns[turn].agent?.steps[index] = step
            replace(changed)
            return
        }
    }

    /// Re-reads the current conversation's cards that the server can load one at a time, so a card acted on here or
    /// elsewhere shows its present state. A card that cannot be re-read keeps what it showed when its answer arrived.
    func refreshCards() async {
        guard let id = currentID, let stored = current?.turns.flatMap(\.items) else { return }
        var fresh: [String: WorkItem] = [:]
        await withTaskGroup(of: WorkItem?.self) { group in
            var requested: Set<String> = []
            for item in stored {
                guard case .work(let kind, let id) = item.route, requested.insert(id).inserted else { continue }
                group.addTask { try? await RoundupAPI.card(kind: kind, id: id) }
            }
            for await item in group {
                if let item { fresh[item.id] = item }
            }
        }
        // A turn may have arrived meanwhile, so the answer is applied to the conversation as it is now.
        guard var conversation = conversations.first(where: { $0.id == id }) else { return }
        var changed = false
        for turn in conversation.turns.indices {
            for item in conversation.turns[turn].items.indices {
                let old = conversation.turns[turn].items[item]
                guard let new = fresh[old.id], new.kind == old.kind, new != old else { continue }
                conversation.turns[turn].items[item] = new
                changed = true
            }
        }
        if changed { replace(conversation) }
    }

    private func request(_ question: String, history: [RoundupAPI.ChatTurn], in id: Conversation.ID,
                         requestID: String) {
        answering.insert(id)
        Task {
            let turn: Turn
            do {
                let answer = try await AgentCenter.shared.answer(
                    question, history: history, source: .chat, requestID: requestID)
                turn = Turn(role: .assistant, text: answer.text, items: answer.items, agent: answer.agent)
            } catch {
                turn = Turn(role: .failure, text: error.localizedDescription, items: [])
            }
            answering.remove(id)
            record(turn, in: id)
            settle(turn)
        }
    }

    /// After an answer is recorded: screens reload when its run changed a row, and a run still going is followed.
    private func settle(_ turn: Turn) {
        guard let agent = turn.agent else { return }
        if agent.changedData { app?.dataDidChange() }
        if agent.status.isUnfinished { follow(agent.runID) }
    }

    /// Reads a run that goes on at the server until it ends, writing each finished step into its answer. It
    /// keeps going while the sheet is closed; after a relaunch `refreshRuns` picks the run up again.
    private func follow(_ runID: String) {
        guard following[runID] == nil else { return }
        following[runID] = Task {
            defer { following[runID] = nil }
            var failures = 0
            while !Task.isCancelled {
                do {
                    let run = try await RoundupAPI.agentRun(id: runID)
                    failures = 0
                    if apply(run), AgentRecord(run).changedData { app?.dataDidChange() }
                    guard run.status.isUnfinished else {
                        AgentCenter.shared.noteRaised(run.proposals)
                        if !isChatVisible { app?.showToast(Self.endNotice(for: run)) }
                        return
                    }
                    try await Task.sleep(for: Self.followInterval)
                } catch is CancellationError {
                    return
                } catch let error as RoundupAPIError where error.isMissing {
                    // The server no longer knows this run, so waiting longer would never end.
                    closeUnreadable(runID)
                    return
                } catch {
                    failures += 1
                    try? await Task.sleep(for: ReconnectBackoff.delay(afterFailures: failures))
                }
            }
        }
    }

    /// What to say when a run ends while the chat is closed. It claims the work only when every step that was
    /// asked for ran; a run that proposed, refused or asked back has an answer waiting and nothing more.
    private static func endNotice(for run: AgentRun) -> String {
        let asked = run.steps.filter { !$0.isRead }
        if run.status == .failed || run.status == .stopped {
            return "\(AssistantIdentity.name)가 부탁하신 일을 중간에 멈췄어요"
        }
        if !asked.isEmpty, asked.allSatisfy(\.ran) {
            return "\(AssistantIdentity.name)가 부탁하신 일을 모두 마쳤어요"
        }
        return "\(AssistantIdentity.name)의 답이 도착했어요"
    }

    /// Writes what the server knows of a run into the answer that belongs to it; false when nothing changed.
    @discardableResult
    private func apply(_ run: AgentRun) -> Bool {
        for conversation in conversations {
            guard let turn = conversation.turns.firstIndex(where: { $0.agent?.runID == run.id }) else { continue }
            let record = AgentRecord(run)
            let text = run.answer ?? conversation.turns[turn].text
            guard conversation.turns[turn].agent != record || conversation.turns[turn].text != text else { return false }
            var changed = conversation
            changed.turns[turn].agent = record
            changed.turns[turn].text = text
            replace(changed)
            return true
        }
        return false
    }

    private func closeUnreadable(_ runID: String) {
        for conversation in conversations {
            guard let turn = conversation.turns.firstIndex(where: { $0.agent?.runID == runID }) else { continue }
            var changed = conversation
            changed.turns[turn].agent?.status = .failed
            replace(changed)
            return
        }
    }

    private func begin() -> Conversation.ID {
        let conversation = Conversation(id: UUID(), title: "", createdAt: .now, updatedAt: .now, turns: [])
        conversations.insert(conversation, at: 0)
        for dropped in conversations.dropFirst(Self.limit) {
            let file = Self.file(dropped.id)
            enqueue { try FileManager.default.removeItem(at: file) }
        }
        conversations = Array(conversations.prefix(Self.limit))
        currentID = conversation.id
        return conversation.id
    }

    private func record(_ turn: Turn, in id: Conversation.ID) {
        // Missing means it was deleted while its answer was on the way.
        guard let index = conversations.firstIndex(where: { $0.id == id }) else { return }
        var conversation = conversations.remove(at: index)
        if conversation.title.isEmpty, turn.role == .owner {
            conversation.title = turn.text.split(whereSeparator: \.isWhitespace).joined(separator: " ")
        }
        conversation.turns.append(turn)
        conversation.updatedAt = turn.date
        conversations.insert(conversation, at: 0)
        save(conversation)
    }

    private func replace(_ conversation: Conversation) {
        guard let index = conversations.firstIndex(where: { $0.id == conversation.id }) else { return }
        conversations[index] = conversation
        save(conversation)
    }

    private func save(_ conversation: Conversation) {
        let file = Self.file(conversation.id)
        do {
            // Encoded here because the cards' coding is bound to the main actor; only the write leaves it.
            let data = try Self.encoder.encode(conversation)
            enqueue {
                try FileManager.default.createDirectory(at: file.deletingLastPathComponent(), withIntermediateDirectories: true)
                try data.write(to: file, options: .atomic)
            }
        } catch {
            Self.log.error("A conversation could not be encoded: \(error.localizedDescription, privacy: .public)")
        }
    }

    private func enqueue(_ work: @escaping @Sendable () throws -> Void) {
        let previous = fileWork
        fileWork = Task.detached(priority: .utility) {
            await previous?.value
            do {
                try work()
            } catch {
                Self.log.error("Conversation file work failed: \(error.localizedDescription, privacy: .public)")
            }
        }
    }

    private static func file(_ id: Conversation.ID) -> URL {
        directory.appending(path: "\(id.uuidString).json")
    }

    private static func load() -> [Conversation] {
        let files: [URL]
        do {
            files = try FileManager.default.contentsOfDirectory(at: directory, includingPropertiesForKeys: nil)
        } catch let error as CocoaError where error.code == .fileReadNoSuchFile {
            // Nothing has been saved yet.
            return []
        } catch {
            log.error("Saved conversations could not be listed: \(error.localizedDescription, privacy: .public)")
            return []
        }
        let loaded = files.filter { $0.pathExtension == "json" }.compactMap { file -> Conversation? in
            do {
                return try decoder.decode(Conversation.self, from: Data(contentsOf: file))
            } catch {
                log.error("\(file.lastPathComponent, privacy: .public) could not be read: \(error.localizedDescription, privacy: .public)")
                return nil
            }
        }
        return Array(loaded.sorted { $0.updatedAt > $1.updatedAt }.prefix(limit))
    }
}

extension ConversationStore.Turn {
    init(role: ConversationStore.Role, text: String, items: [WorkItem], agent: AgentRecord? = nil,
         requestID: String? = nil) {
        self.init(id: UUID(), role: role, text: text, items: items, date: .now, agent: agent, requestID: requestID)
    }

    init(from decoder: any Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        id = try container.decode(UUID.self, forKey: .id)
        role = try container.decode(ConversationStore.Role.self, forKey: .role)
        text = try container.decode(String.self, forKey: .text)
        date = try container.decode(Date.self, forKey: .date)
        // Cards and the agent's record follow the server's shape. When an app update can no longer read a stored
        // one, the turn keeps its text.
        items = (try? container.decode([WorkItem].self, forKey: .items)) ?? []
        agent = try? container.decodeIfPresent(AgentRecord.self, forKey: .agent)
        requestID = try? container.decodeIfPresent(String.self, forKey: .requestID)
    }
}

/// `CardDue` is declared outside the assistant's files, so its encoding is written out here instead of synthesized.
extension CardDue: Encodable {
    private enum Key: String, CodingKey {
        case at, prefix, suffix, missed
    }

    func encode(to encoder: any Encoder) throws {
        var container = encoder.container(keyedBy: Key.self)
        try container.encode(at, forKey: .at)
        try container.encodeIfPresent(prefix, forKey: .prefix)
        try container.encode(suffix, forKey: .suffix)
        try container.encodeIfPresent(missed, forKey: .missed)
    }
}
