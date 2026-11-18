import SwiftUI
import RoundupCore

enum AppTab: String, Hashable {
    case today
    case calendar
    case operations
    case settings
}

enum AssistantLaunch: String, Identifiable {
    case text
    case voice

    var id: Self { self }
}

struct RootTabView: View {
    @SceneStorage("root.tab") private var selection: AppTab = .today
    @State private var assistant: AssistantLaunch?
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @Environment(DemoStore.self) private var store
    @Environment(\.scenePhase) private var scenePhase

    var body: some View {
        TabView(selection: $selection) {
            Tab("오늘", systemImage: "house", value: AppTab.today) {
                TodayView()
            }
            Tab("캘린더", systemImage: "calendar", value: AppTab.calendar) {
                CalendarScreen()
            }
            Tab("운영", systemImage: "square.grid.2x2", value: AppTab.operations) {
                OperationsView()
            }
            .badge(SampleData.attentionCount(pendingInquiries: store.pendingCount))
            Tab("설정", systemImage: "gearshape", value: AppTab.settings) {
                SettingsView()
            }
        }
        .tabViewStyle(.sidebarAdaptable)
        .tabBarMinimizeBehavior(reduceMotion ? .never : .onScrollDown)
        .tabViewBottomAccessory {
            AssistantAccessory(
                openText: { assistant = .text },
                openVoice: { assistant = .voice }
            )
        }
        .sheet(item: $assistant) { launch in
            AssistantSheet(launch: launch)
                .environment(store)
        }
        .safeAreaInset(edge: .top) {
            InquirySyncStatus()
        }
        .task { await store.loadInquiries() }
        .onChange(of: scenePhase) { _, phase in
            if phase == .active {
                Task { await store.loadInquiries() }
            }
        }
    }
}

#Preview {
    RootTabView()
        .environment(DemoStore())
}
