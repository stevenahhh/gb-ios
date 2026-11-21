import Observation
import RoundupCore
import SwiftUI

/// App-wide mutation state: screens reload whenever `dataVersion` changes.
@MainActor
@Observable
final class AppModel {
    private(set) var dataVersion = 0
    private(set) var successCount = 0
    private(set) var attentionCount: Int?
    private(set) var runningIDs: Set<String> = []
    private(set) var ownerEditedDraftIDs: Set<String> = []
    var failureMessage: String?
    /// One short notice above the assistant bar, optionally with 되돌리기.
    var toast: AppToast?
    /// The assistant bar's frame in window coordinates. The toast covers exactly this slot.
    var accessorySlot: CGRect?
    /// The data version the badge count was last read at, so a screen that already returned it saves a request.
    @ObservationIgnored private var attentionVersion: Int?

    init() {
        ServerConnection.shared.onRecovered = { [weak self] in
            self?.showToast("다시 연결됐어요", seconds: 2)
        }
    }

    /// A plain notice that is already on screen is not shown again, so several screens recovering together
    /// produce one "다시 연결됐어요".
    func showToast(_ message: String, seconds: Int = 7, undo: (@MainActor () async -> Void)? = nil) {
        if undo == nil, let toast, toast.undo == nil, toast.message == message { return }
        toast = AppToast(message: message, seconds: seconds, undo: undo)
    }

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

    func markDraftEdited(_ id: String) {
        ownerEditedDraftIDs.insert(id)
    }

    func refreshAttention() async {
        let version = dataVersion
        guard attentionVersion != version,
              let count = try? await RoundupAPI.operations(period: nil).attentionCount else { return }
        attentionCount = count
        attentionVersion = version
    }

    func updateAttention(_ count: Int) {
        attentionCount = count
        attentionVersion = dataVersion
    }
}

/// Holds the last server response for a screen, so a failed refresh keeps visible data.
@MainActor
@Observable
final class Loader<Value> {
    private(set) var value: Value?
    private(set) var errorMessage: String?
    private(set) var loadedAt: Date?
    /// Loads in a row that failed to reach the server; while above zero the screen reconnects by itself.
    private(set) var connectionFailures = 0

    func load(_ fetch: @escaping () async throws -> Value) async {
        // A cold launch shows today's last response from disk at once, then replaces it with the fresh one.
        // Reading it here, before the child task below, keeps it in the caller's main-actor turn.
        if value == nil, let cached = await ResponseCache.cachedValue(fetch) {
            value = cached.value
            loadedAt = cached.savedAt
            LaunchTiming.firstContent(Value.self, source: "cache")
        }
        // A detached child survives SwiftUI cancelling `refreshable` when state changes.
        await Task {
            do {
                let fetched = try await fetch()
                // Rows that arrive or leave animate the way a native list's do.
                withAnimation(UIAccessibility.isReduceMotionEnabled ? nil : .snappy(duration: 0.25)) {
                    value = fetched
                    loadedAt = .now
                    errorMessage = nil
                }
                connectionFailures = 0
                LaunchTiming.firstContent(Value.self, source: "network")
            } catch is CancellationError {
                return
            } catch {
                errorMessage = error.localizedDescription
                connectionFailures = error is any TransientFailure ? connectionFailures + 1 : 0
            }
        }.value
    }
}

/// Standard loading, error/retry, and loaded presentation for a server-backed screen.
struct LoadableContent<Value, Content: View>: View {
    let loader: Loader<Value>
    let retry: () async -> Void
    @ViewBuilder let content: (Value) -> Content
    @Environment(InquiryStore.self) private var store
    @State private var showsSpinner = false

    var body: some View {
        Group {
            if let value = loader.value {
                content(value)
                    .safeAreaInset(edge: .top) {
                        if loader.errorMessage != nil || store.inquiryLoadError != nil || store.requiresInquiryReload {
                            ConnectionNotice(retry: retry, screenFailures: loader.connectionFailures) {
                                loader.errorMessage != nil || store.inquiryLoadError != nil
                            }
                        }
                    }
            } else if loader.connectionFailures > 0 {
                ReconnectingView(retry: retry, screenFailures: loader.connectionFailures)
            } else if let message = loader.errorMessage {
                LoadErrorView(message: message) { Task { await retry() } }
            } else {
                // A load that finishes within a moment shows no spinner at all.
                ProgressView("불러오는 중이에요")
                    .opacity(showsSpinner ? 1 : 0)
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
                    .accessibilityIdentifier("screen.loading")
                    .task {
                        try? await Task.sleep(for: .milliseconds(350))
                        withAnimation { showsSpinner = true }
                    }
            }
        }
        .animation(.easeOut(duration: 0.2), value: loader.value == nil)
    }
}

/// A screen with nothing loaded yet whose server is unreachable: it reconnects by itself and says so.
struct ReconnectingView: View {
    let retry: () async -> Void
    let screenFailures: Int
    @State private var connection = ServerConnection.shared

    var body: some View {
        ContentUnavailableView {
            Label {
                Text(connection.hasNetworkPath ? "다시 연결하는 중" : "인터넷 연결을 기다리는 중")
            } icon: {
                ProgressView()
                    .controlSize(.large)
            }
        } description: {
            Text(keepingWords: "서버에 연결하지 못했어요. 연결되면 자동으로 불러와요.")
        } actions: {
            Button("지금 다시 시도") { Task { await retry() } }
                .buttonStyle(.bordered)
                .controlSize(.large)
                .accessibilityIdentifier("screen.retry")
        }
        .accessibilityIdentifier("screen.reconnecting")
        .autoReconnect(screenFailures: screenFailures, retry: retry)
    }
}

/// The single connection line under the title. Whatever failed (this screen, inquiries, or both), there is one row,
/// one retry for everything, and it never covers the title or the back button. Connection failures retry by
/// themselves while the row is visible; the button stays as a manual retry.
struct ConnectionNotice: View {
    let retry: () async -> Void
    /// The screen's consecutive connection failures; zero when only inquiries failed.
    var screenFailures = 0
    let isFailing: @MainActor () -> Bool
    @Environment(InquiryStore.self) private var store
    @Environment(AppModel.self) private var app
    @State private var connection = ServerConnection.shared
    @State private var isRetrying = false
    @State private var isStillOffline = false

    private var isReconnecting: Bool {
        isFailing() && (screenFailures > 0 || (store.inquiryLoadError != nil && store.inquiryLoadIsTransient))
    }

    var body: some View {
        HStack(spacing: 8) {
            if isReconnecting && connection.hasNetworkPath {
                ProgressView()
                    .controlSize(.small)
                    .accessibilityHidden(true)
            } else {
                Image(systemName: "exclamationmark.circle")
                    .accessibilityHidden(true)
            }
            message
            Spacer(minLength: 8)
            Button {
                Task { await retryAll() }
            } label: {
                HStack(spacing: 6) {
                    if isRetrying {
                        ProgressView()
                            .controlSize(.small)
                    }
                    Text(isRetrying ? "다시 시도하는 중" : "다시 시도")
                }
                .frame(minHeight: 44)
                .contentShape(.rect)
            }
            .buttonStyle(.bordered)
            .buttonBorderShape(.capsule)
            .disabled(isRetrying)
            .accessibilityIdentifier("connection.retry")
        }
        .font(.subheadline)
        .padding(.leading, 14)
        .padding(.trailing, 6)
        .padding(.vertical, 4)
        .background(AppPalette.card, in: .card)
        .padding(.horizontal, 16)
        .padding(.vertical, 4)
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("connection.notice")
        .autoReconnect(screenFailures: screenFailures, retry: retry)
    }

    private var message: Text {
        if !isFailing() && store.requiresInquiryReload {
            return Text("저장 결과를 확인해야 해요")
        }
        let lead = if isReconnecting {
            Text(connection.hasNetworkPath ? "다시 연결하는 중" : "인터넷 연결을 기다리는 중")
        } else {
            Text(isStillOffline ? "아직 연결이 안 돼요" : "연결이 끊겼어요")
        }
        return Text("\(lead) \(Text("· 마지막 정보예요").foregroundStyle(Color.secondaryText))")
    }

    private func retryAll() async {
        let inquiriesWereFailing = store.inquiryLoadError != nil
        isRetrying = true
        await retry()
        await store.loadInquiries()
        isRetrying = false
        isStillOffline = isFailing()
        // When inquiries recover, the root view already says so.
        if !isStillOffline && !inquiriesWereFailing {
            app.showToast("다시 연결됐어요", seconds: 2)
        }
    }
}
