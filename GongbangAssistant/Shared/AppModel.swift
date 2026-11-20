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

    func showToast(_ message: String, seconds: Int = 7, undo: (@MainActor () async -> Void)? = nil) {
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
        attentionCount = try? await RoundupAPI.operations(period: nil).attentionCount
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
    @Environment(InquiryStore.self) private var store

    var body: some View {
        if let value = loader.value {
            content(value)
                .safeAreaInset(edge: .top) {
                    if loader.errorMessage != nil || store.inquiryLoadError != nil || store.requiresInquiryReload {
                        ConnectionNotice(retry: retry) {
                            loader.errorMessage != nil || store.inquiryLoadError != nil
                        }
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

/// The single connection line under the title. Whatever failed (this screen, inquiries, or both), there is one row,
/// one retry for everything, and it never covers the title or the back button.
struct ConnectionNotice: View {
    let retry: () async -> Void
    let isFailing: @MainActor () -> Bool
    @Environment(InquiryStore.self) private var store
    @Environment(AppModel.self) private var app
    @State private var isRetrying = false
    @State private var isStillOffline = false

    var body: some View {
        HStack(spacing: 8) {
            Image(systemName: "exclamationmark.circle")
                .accessibilityHidden(true)
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
        .background(AppPalette.card, in: .rect(cornerRadius: 16))
        .padding(.horizontal, 16)
        .padding(.vertical, 4)
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("connection.notice")
    }

    private var message: Text {
        if !isFailing() && store.requiresInquiryReload {
            return Text("저장 결과를 확인해야 해요")
        }
        let lead = Text(isStillOffline ? "아직 연결이 안 돼요" : "연결이 끊겼어요")
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

struct AppToast: Identifiable {
    let id = UUID()
    let message: String
    let seconds: Int
    let undo: (@MainActor () async -> Void)?
}

/// Covers the assistant bar for a moment instead of the list, so the changed row stays visible.
/// It leaves after 7 seconds, or stays until closed while VoiceOver is running.
struct ToastHost: View {
    @Environment(AppModel.self) private var app

    var body: some View {
        Group {
            if let toast = app.toast {
                HStack(spacing: 12) {
                    // Completion toasts carry the row's title; one line keeps 되돌리기 in reach.
                    Text(toast.message)
                        .lineLimit(1)
                    if let undo = toast.undo {
                        Button("되돌리기") {
                            app.toast = nil
                            Task { await undo() }
                        }
                        .fontWeight(.semibold)
                        .frame(minHeight: 44)
                        .accessibilityIdentifier("toast.undo")
                    }
                    Button("닫기", systemImage: "xmark") { app.toast = nil }
                        .labelStyle(.iconOnly)
                        .frame(minWidth: 32, minHeight: 44)
                }
                .font(.subheadline)
                .foregroundStyle(CalendarTokens.background)
                .padding(.horizontal, 18)
                .background(CalendarTokens.label, in: .capsule)
                .accessibilityElement(children: .contain)
                .transition(.move(edge: .bottom).combined(with: .opacity))
                .task(id: toast.id) {
                    guard !UIAccessibility.isVoiceOverRunning else { return }
                    try? await Task.sleep(for: .seconds(toast.seconds))
                    if app.toast?.id == toast.id { app.toast = nil }
                }
            }
        }
        .animation(.spring(duration: 0.25), value: app.toast?.id)
    }
}
