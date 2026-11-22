import Foundation
import RoundupCore

/// One service's stored value from /connections. Stored never means connected: only GET /collectors/status can say
/// a source is collecting.
struct ServiceConnection: Decodable, Identifiable, Hashable {
    let service: String
    let value: String?
    /// "saved" or "none"; kept as text so a state a newer server adds does not fail the whole list.
    let state: String
    /// ISO 8601 text; kept as text because the write routes are decoded without a date strategy.
    let updatedAt: String?
    let revision: Int

    var id: String { service }
    var isSaved: Bool { state == "saved" && value != nil }
}

/// What the connections screen shows: stored values, and what the collectors are really doing.
struct ConnectionsData {
    let items: [ServiceConnection]
    /// Sources by id from GET /collectors/status; empty when that route could not be read.
    let sources: [String: CollectorStatus.Source]
    /// True when the status route failed, so the screen says that no row can show 수집 중 right now.
    let statusFailed: Bool

    /// The server's slot for a service; nil when the service is planned or this server does not list it.
    func item(for service: ConnectionService) -> ServiceConnection? {
        guard service.availability == .savable else { return nil }
        return items.first { $0.service == service.id }
    }

    func source(for service: ConnectionService) -> CollectorStatus.Source? {
        service.collectorSource.flatMap { sources[$0] }
    }

    /// The collector's own words for a source that cannot run, such as what the owner must set up first.
    func note(for service: ConnectionService) -> String? {
        guard let source = source(for: service),
              source.state == .error || source.state == .needsConnection else { return nil }
        return source.message
    }
}

extension RoundupAPI {
    private struct ConnectionValue: Encodable { let value: String; let expectedRevision: Int }
    private struct ConnectionRevision: Encodable { let expectedRevision: Int }
    private struct ConnectionList: Decodable { let items: [ServiceConnection] }

    static func connections() async throws -> [ServiceConnection] {
        let list: ConnectionList = try await get("connections")
        return list.items
    }

    /// Stored values joined with collector states. A cached answer carries no collector state, because an old
    /// status must never make a row say 수집 중.
    static func connectionsScreen() async throws -> ConnectionsData {
        let items = try await connections()
        guard ResponseCache.probe == nil else {
            return ConnectionsData(items: items, sources: [:], statusFailed: false)
        }
        do {
            let status = try await collectorStatus()
            let sources = Dictionary(status.sources.map { ($0.id, $0) }, uniquingKeysWith: { first, _ in first })
            return ConnectionsData(items: items, sources: sources, statusFailed: false)
        } catch is CancellationError {
            throw CancellationError()
        } catch {
            // The stored values are still true without the status; the screen says the status is unknown.
            return ConnectionsData(items: items, sources: [:], statusFailed: true)
        }
    }

    /// Stores a value. Use revision 0 for the first save; the returned value is the normalised one to show.
    static func saveConnection(service: String, value: String, revision: Int) async throws -> ServiceConnection {
        try await send(method: "PUT", path: "connections/\(service)",
                       body: ConnectionValue(value: value, expectedRevision: revision))
    }

    /// Clears a stored value. The returned revision is the one a later save must send.
    static func deleteConnection(service: String, revision: Int) async throws -> ServiceConnection {
        try await send(method: "DELETE", path: "connections/\(service)",
                       body: ConnectionRevision(expectedRevision: revision))
    }

    /// Words for a failed connection write. The transport already words refusals; anything else did not reach
    /// the server.
    static func connectionFailureText(_ error: any Error) -> String {
        (error as? RoundupAPIError)?.message ?? "지금 연결이 안 돼요. 와이파이나 데이터가 켜져 있는지 보신 뒤 다시 시도해 주세요."
    }
}
