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
    @Environment(InquiryStore.self) private var store
    @Environment(AppModel.self) private var app
    @Environment(\.scenePhase) private var scenePhase

    private var failureIsPresented: Binding<Bool> {
        Binding(get: { app.failureMessage != nil }, set: { if !$0 { app.failureMessage = nil } })
    }

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
            .badge(app.attentionCount ?? 0)
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
        .overlay(alignment: .bottom) {
            // Over the assistant bar's own slot, so the notice never hides the row that just changed.
            ToastHost()
                .padding(.bottom, 58)
        }
        // Server-phrased dates (오늘, 내일) are rebuilt by reloading once the day turns over.
        // Inquiries load on every tab, so their recovery is the app's "back online" moment.
        .onChange(of: store.inquiryLoadError == nil) { wasOK, isOK in
            if isOK && !wasOK { app.showToast("다시 연결됐어요", seconds: 2) }
        }
        .onReceive(NotificationCenter.default.publisher(for: .NSCalendarDayChanged)) { _ in
            app.dataDidChange()
        }
        .task(id: app.dataVersion) {
            await store.loadInquiries()
            await app.refreshAttention()
        }
        .onChange(of: scenePhase) { _, phase in
            if phase == .active { app.dataDidChange() }
        }
        .sensoryFeedback(.success, trigger: app.successCount)
        .alert("처리하지 못했어요", isPresented: failureIsPresented) {
            Button("확인", role: .cancel) {}
        } message: {
            Text(app.failureMessage ?? "")
        }
    }
}
