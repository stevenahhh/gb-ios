import SwiftUI

enum AppTab: Hashable {
    case today
    case calendar
    case operations
    case more
}

struct RootTabView: View {
    @State private var selection: AppTab = .today
    @State private var isAssistantPresented = false

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
            Tab("더보기", systemImage: "ellipsis", value: AppTab.more) {
                MoreView()
            }
        }
        .tabViewStyle(.sidebarAdaptable)
        .tabBarMinimizeBehavior(.onScrollDown)
        .tabViewBottomAccessory(isEnabled: selection == .today) {
            AssistantAccessory {
                isAssistantPresented = true
            }
        }
        .sheet(isPresented: $isAssistantPresented) {
            AssistantSheet()
        }
    }
}

#Preview {
    RootTabView()
}
