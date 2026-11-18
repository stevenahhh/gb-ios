import Observation
import SwiftUI

/// App-wide mutation state: screens reload whenever `dataVersion` changes.
@MainActor
@Observable
final class AppModel {
    private(set) var dataVersion = 0
    private(set) var successCount = 0
    private(set) var attentionCount: Int?
    private(set) var runningIDs: Set<String> = []
    var failureMessage: String?

    func isRunning(_ id: String) -> Bool { runningIDs.contains(id) }

    /// Runs one write per item; a second tap while it is in flight does nothing.
    @discardableResult
    func run(id: String, _ operation: @escaping () async throws -> Void) async -> Bool {
        guard !runningIDs.contains(id) else { return false }
        runningIDs.insert(id)
        defer { runningIDs.remove(id) }
        do {
            try await operation()
            successCount += 1
            dataDidChange()
            return true
        } catch is CancellationError {
            return false
        } catch {
            failureMessage = error.localizedDescription
            if (error as? RoundupAPIError)?.isConflict == true { dataDidChange() }
            return false
        }
    }

    func dataDidChange() {
        dataVersion += 1
    }

    func refreshAttention() async {
        attentionCount = try? await RoundupAPI.operations(month: nil).attentionCount
    }

    func updateAttention(_ count: Int) {
        attentionCount = count
    }
}

/// Holds the last server response for a screen, so a failed refresh keeps visible data.
@MainActor
@Observable
final class Loader<Value> {
    private(set) var value: Value?
    private(set) var errorMessage: String?
    private(set) var loadedAt: Date?

    func load(_ fetch: @escaping () async throws -> Value) async {
        // A detached child survives SwiftUI cancelling `refreshable` when state changes.
        await Task {
            do {
                value = try await fetch()
                loadedAt = .now
                errorMessage = nil
            } catch is CancellationError {
                return
            } catch {
                errorMessage = error.localizedDescription
            }
        }.value
    }
}

/// Standard loading, error/retry, and loaded presentation for a server-backed screen.
struct LoadableContent<Value, Content: View>: View {
    let loader: Loader<Value>
    let retry: () async -> Void
    @ViewBuilder let content: (Value) -> Content

    var body: some View {
        if let value = loader.value {
            content(value)
                .safeAreaInset(edge: .top) {
                    if let message = loader.errorMessage {
                        RefreshFailureBanner(message: message, retry: retry)
                    }
                }
        } else if let message = loader.errorMessage {
            LoadErrorView(message: message) { Task { await retry() } }
        } else {
            ProgressView("불러오는 중이에요")
                .frame(maxWidth: .infinity, maxHeight: .infinity)
                .accessibilityIdentifier("screen.loading")
        }
    }
}

struct RefreshFailureBanner: View {
    let message: String
    let retry: () async -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Label(message, systemImage: "exclamationmark.circle")
            Text("화면의 내용은 마지막으로 불러온 값이에요.")
                .foregroundStyle(.secondary)
            Button("다시 불러오기") { Task { await retry() } }
                .buttonStyle(.bordered)
        }
        .font(.subheadline)
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding()
        .background(.bar)
        .accessibilityIdentifier("screen.refreshError")
    }
}
