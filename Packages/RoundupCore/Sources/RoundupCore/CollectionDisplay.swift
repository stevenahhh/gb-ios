import Foundation

/// What a collector reports for its source. Raw values are the server's codes.
public enum CollectorState: String, Codable, Sendable {
    case collecting
    case idle
    case needsConnection = "needs_connection"
    case error
}

/// What 실시간 수집 현황 shows: the server's rows, or sample rows and the reason for them.
/// Sample and real numbers never share the card; it is one or the other for every row.
public enum CollectionDisplay: Equatable, Sendable {
    /// The server's rows, all of them.
    case live
    /// Sample rows, because the server gave nothing to show: no endpoint, a failed request, or an empty list.
    case sampleWithoutStatus
    /// Sample rows, because every source still waits for the owner to connect it.
    case sampleBeforeConnection

    /// `states` is nil when the last answer could not be used. One source that collects, waits, or failed means a
    /// channel is connected, and from then on the real rows show, including the ones still unconnected.
    public static func choose(states: [CollectorState]?) -> CollectionDisplay {
        guard let states, !states.isEmpty else { return .sampleWithoutStatus }
        return states.contains { $0 != .needsConnection } ? .live : .sampleBeforeConnection
    }
}
