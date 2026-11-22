import RoundupCore
import SwiftUI

extension View {
    func todayGreeting(pendingCount: Int, updated: String, now: Date) -> some View {
        modifier(TodayGreetingHeader(pendingCount: pendingCount, updated: updated, now: now))
    }
}

private struct TodayGreetingHeader: ViewModifier {
    let pendingCount: Int
    let updated: String
    let now: Date
    @State private var loader = Loader<SettingsData>()
    @Environment(AppModel.self) private var app

    func body(content: Content) -> some View {
        content
            .navigationTitle(TodayGreeting.title(ownerName: workshop?.ownerTitle, workshopName: workshop?.name))
            .toolbar {
                ToolbarItem(placement: .largeSubtitle) {
                    VStack(alignment: .leading, spacing: 2) {
                        Text(TodayGreeting.line(pendingCount: pendingCount, now: now))
                            .font(.subheadline)
                            .accessibilityIdentifier("today.greeting.line")
                        Text(updated)
                            .font(.subheadline)
                            .foregroundStyle(.secondary)
                    }
                    .fixedSize(horizontal: false, vertical: true)
                    .accessibilityIdentifier("today.greeting")
                }
            }
            .task(id: app.dataVersion) { await loader.load { try await RoundupAPI.settings() } }
    }

    private var workshop: WorkshopProfile? { loader.value?.workshop }
}
