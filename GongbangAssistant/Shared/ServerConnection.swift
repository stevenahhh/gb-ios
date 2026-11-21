import Network
import Observation
import RoundupCore
import SwiftUI
import os

/// The server could not be reached, or answered that it is briefly unavailable (502-504).
/// Screens retry these by themselves; HTTP answers such as 401, 404, 409, or 422 are never retried.
struct ConnectionError: LocalizedError, TransientFailure {
    var errorDescription: String? { "서버에 연결하지 못했어요. 잠시 후 다시 시도해 주세요." }
}

/// App-wide connection state: whether the device has a network path, and whether the last request reached the server.
@MainActor
@Observable
final class ServerConnection {
    static let shared = ServerConnection()

    private(set) var hasNetworkPath = true
    /// Increments each time the network path comes back, so waiting screens retry at once.
    private(set) var pathRestorations = 0
    private(set) var isServerUnreachable = false
    /// Called once when a request reaches the server after a connection failure.
    @ObservationIgnored var onRecovered: (@MainActor () -> Void)?
    @ObservationIgnored private let monitor = NWPathMonitor()

    static let logger = Logger(subsystem: "GongbangAssistant", category: "network")

    /// Request lines carry only the method, path, status, and timing, never bodies or keys.
    static func log(_ line: String) {
        logger.info("\(line, privacy: .public)")
    }

    private init() {
        Self.start(monitor) { satisfied in
            Task { @MainActor in ServerConnection.shared.pathChanged(satisfied: satisfied) }
        }
    }

    private nonisolated static func start(_ monitor: NWPathMonitor, onChange: @escaping @Sendable (Bool) -> Void) {
        monitor.pathUpdateHandler = { path in onChange(path.status == .satisfied) }
        monitor.start(queue: DispatchQueue(label: "GongbangAssistant.path", qos: .utility))
    }

    private func pathChanged(satisfied: Bool) {
        guard satisfied != hasNetworkPath else { return }
        hasNetworkPath = satisfied
        Self.logger.info("path \(satisfied ? "satisfied" : "unsatisfied", privacy: .public)")
        if satisfied { pathRestorations += 1 }
    }

    func requestReachedServer() {
        guard isServerUnreachable else { return }
        isServerUnreachable = false
        Self.logger.info("server reachable again")
        onRecovered?()
    }

    func requestFailedToReachServer() {
        isServerUnreachable = true
    }
}

/// Exponential backoff with jitter for automatic reconnects: about 1, 2, 4, 8, 16, then 30 seconds.
enum ReconnectBackoff {
    static func delay(afterFailures failures: Int) -> Duration {
        let base = min(30, pow(2, Double(max(failures, 1) - 1)))
        return .milliseconds(Int(base * Double.random(in: 0.8...1.2) * 1000))
    }
}

/// Retries a screen that failed for a connection reason, and inquiries that failed the same way, while the view is
/// on screen: after a backoff delay, at once when the network path comes back, and never for other errors.
/// Leaving the screen cancels the pending retry.
struct AutoReconnect: ViewModifier {
    /// The screen's consecutive connection failures; zero when its last load succeeded or failed for another reason.
    let screenFailures: Int
    let retry: () async -> Void
    @Environment(InquiryStore.self) private var store
    @State private var connection = ServerConnection.shared
    @State private var handledRestorations = ServerConnection.shared.pathRestorations

    private struct Trigger: Equatable {
        let screenFailures: Int
        let inquiriesFailing: Bool
        let restorations: Int
    }

    private var inquiriesFailing: Bool { store.inquiryLoadError != nil && store.inquiryLoadIsTransient }

    func body(content: Content) -> some View {
        content.task(id: Trigger(
            screenFailures: screenFailures, inquiriesFailing: inquiriesFailing,
            restorations: connection.pathRestorations
        )) {
            await reconnect()
        }
    }

    private func reconnect() async {
        var failures = max(screenFailures, 1)
        while screenFailures > 0 || inquiriesFailing {
            // Without a network path a retry cannot succeed; its return changes the trigger and restarts this task.
            guard connection.hasNetworkPath else { return }
            if connection.pathRestorations == handledRestorations {
                do { try await Task.sleep(for: ReconnectBackoff.delay(afterFailures: failures)) } catch { return }
            }
            handledRestorations = connection.pathRestorations
            ServerConnection.logger.info("reconnect.attempt failures=\(failures, privacy: .public)")
            // Inquiries go first: a screen retry that fails again changes `screenFailures`, which cancels this task
            // and restarts it with a longer delay.
            if inquiriesFailing { await store.loadInquiries() }
            if screenFailures > 0 { await retry() }
            if Task.isCancelled { return }
            failures += 1
        }
    }
}

extension View {
    func autoReconnect(screenFailures: Int, retry: @escaping () async -> Void) -> some View {
        modifier(AutoReconnect(screenFailures: screenFailures, retry: retry))
    }
}
