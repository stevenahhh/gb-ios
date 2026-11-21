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
        let text: String
        /// The cards an answer named, as they were when it arrived; `refreshCards` brings them up to date.
        var items: [WorkItem]
        let date: Date

        /// Failed turns stay on screen but never reach the model.
        var apiTurn: RoundupAPI.ChatTurn? {
            switch role {
            case .owner: RoundupAPI.ChatTurn(role: .owner, text: text)
            case .assistant: RoundupAPI.ChatTurn(role: .assistant, text: text)
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
    /// File work runs off the main actor, one job after another, so a later save never lands before an earlier one.
    @ObservationIgnored private var fileWork: Task<Void, Never>?

    private static let limit = 100
    private static let resumeWindow: TimeInterval = 30 * 60
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
    func recordLiveTurn(role: Role, text: String, items: [WorkItem]) {
        record(Turn(role: role, text: text, items: items), in: currentID ?? begin())
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
        record(Turn(role: .owner, text: question, items: []), in: id)
        request(question, history: history, in: id)
    }

    /// Asks the current conversation's unanswered question again, replacing its failure.
    func retry() {
        guard var conversation = current, !answering.contains(conversation.id),
              let question = conversation.unansweredQuestion else { return }
        conversation.turns.removeAll { $0.date > question.date }
        replace(conversation)
        request(question.text, history: conversation.turns.dropLast().compactMap(\.apiTurn), in: conversation.id)
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

    private func request(_ question: String, history: [RoundupAPI.ChatTurn], in id: Conversation.ID) {
        answering.insert(id)
        Task {
            let turn: Turn
            do {
                let reply = try await RoundupAPI.ask(question: question, history: history)
                turn = Turn(role: .assistant, text: reply.answer, items: reply.items)
            } catch {
                turn = Turn(role: .failure, text: error.localizedDescription, items: [])
            }
            answering.remove(id)
            record(turn, in: id)
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
    init(role: ConversationStore.Role, text: String, items: [WorkItem]) {
        self.init(id: UUID(), role: role, text: text, items: items, date: .now)
    }

    init(from decoder: any Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        id = try container.decode(UUID.self, forKey: .id)
        role = try container.decode(ConversationStore.Role.self, forKey: .role)
        text = try container.decode(String.self, forKey: .text)
        date = try container.decode(Date.self, forKey: .date)
        // Cards follow the server's shape. When an app update can no longer read a stored one, the turn keeps its text.
        items = (try? container.decode([WorkItem].self, forKey: .items)) ?? []
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
