import SwiftUI

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
            .badge(SampleData.attentionCount)
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
        }
    }
}

#Preview {
    RootTabView()
}
