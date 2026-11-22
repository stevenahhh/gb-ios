import Foundation

/// What a collector reports for its source. Raw values are the server's codes.
public enum CollectorState: String, Codable, Sendable {
    case collecting
    case idle
    case needsConnection = "needs_connection"
    case error
}

/// What the collection rings show: the server's states, or a sample and the reason for it.
/// Sample and real states are never mixed; it is one or the other for every ring.
public enum CollectionDisplay: Equatable, Sendable {
    /// The server's states.
    case live
    /// The sample, because the server gave nothing to show: no endpoint, a failed request, or an empty list.
    case sampleWithoutStatus
    /// The sample, because every source still waits for the owner to connect it.
    case sampleBeforeConnection

    /// `states` is nil when the last answer could not be used. One source that collects, waits, or failed means a
    /// channel is connected, and from then on the real states show, including the ones still unconnected.
    public static func choose(states: [CollectorState]?) -> CollectionDisplay {
        guard let states, !states.isEmpty else { return .sampleWithoutStatus }
        return states.contains { $0 != .needsConnection } ? .live : .sampleBeforeConnection
    }
}
