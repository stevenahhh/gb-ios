import SwiftUI

/// Everything the agent adds to the assistant sheet, kept in one modifier so the sheet itself gains one line:
/// the line for proposals waiting elsewhere, 파일 불러오기 with the screen that reviews the file, and reading the
/// owner's switches and open proposals when the sheet opens.
struct AssistantAgentSurfaces: ViewModifier {
    @State private var center = AgentCenter.shared
    @State private var connection = ServerConnection.shared
    @Environment(AppModel.self) private var app
    private let store = ConversationStore.shared

    /// Proposals waiting for the owner that the conversation on screen does not already show as cards.
    private var waitingElsewhere: Int {
        let shown = Set(store.current?.turns.flatMap { $0.agent?.proposals ?? [] }.map(\.id) ?? [])
        return center.waiting.filter { !shown.contains($0.id) }.count
    }

    func body(content: Content) -> some View {
        content
            .safeAreaInset(edge: .top, spacing: 0) {
                if waitingElsewhere > 0 {
                    AgentProposalBanner(count: waitingElsewhere)
                }
            }
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    InvoiceFileButton()
                }
            }
            .invoiceFilePicking(onPage: false)
            .onAppear {
                store.app = app
                store.isChatVisible = true
            }
            .onDisappear {
                store.isChatVisible = false
            }
            // Runs again when the server is reached after an outage, so the sheet catches up without a tap.
            .task(id: connection.isServerUnreachable) {
                guard !connection.isServerUnreachable else { return }
                await center.loadSettings()
                await center.loadProposals()
            }
    }
}

/// 파일 불러오기. It sits inside the picking modifier, so the pick it asks for is the sheet's own.
private struct InvoiceFileButton: View {
    @Environment(\.pickInvoiceFile) private var pickInvoiceFile

    var body: some View {
        Button("파일 불러오기", systemImage: "doc.badge.plus") { pickInvoiceFile?(nil) }
            .accessibilityHint("택배사가 보내 준 엑셀에서 송장을 가져와요.")
            .accessibilityIdentifier("assistant.import")
    }
}

extension View {
    func assistantAgent() -> some View {
        modifier(AssistantAgentSurfaces())
    }
}
