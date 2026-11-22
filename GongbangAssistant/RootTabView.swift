import SwiftUI
import RoundupCore

enum AppTab: String, Hashable {
    case today
    case calendar
    case operations
    case settings
}

struct RootTabView: View {
    @SceneStorage("root.tab") private var selection: AppTab = .today
    @State private var isAssistantPresented = false
    @State private var isLiveVoicePresented = false
    @State private var onboarding = OnboardingState.shared
    @State private var wasInBackground = false
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @Environment(InquiryStore.self) private var store
    @Environment(AppModel.self) private var app
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
            .badge(app.attentionCount ?? 0)
            Tab("설정", systemImage: "gearshape", value: AppTab.settings) {
                SettingsView()
            }
        }
        .tabViewStyle(.sidebarAdaptable)
        .tabBarMinimizeBehavior(reduceMotion ? .never : .onScrollDown)
        .tabViewBottomAccessory {
            // The toast covers this slot, so the bar's own controls leave while one is up: the system-hosted
            // accessory ignores accessibilityHidden, and its text would show through the glass.
            ZStack {
                if app.toast == nil {
                    AssistantAccessory(
                        openText: { isAssistantPresented = true },
                        openVoice: {
                            // The live view reads the history once as it starts, so the chat is chosen before it opens.
                            ConversationStore.shared.resume()
                            isLiveVoicePresented = true
                        }
                    )
                }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
            .onGeometryChange(for: CGRect.self) { $0.frame(in: .global) } action: { app.accessorySlot = $0 }
        }
        .tutorialOverlay(selection: $selection)
        .sheet(isPresented: $isAssistantPresented) {
            AssistantSheet()
                .failureAlert()
        }
        .fullScreenCover(isPresented: $onboarding.isPresented) {
            OnboardingFlow()
        }
        // A tour the owner started but did not finish comes back at the next launch.
        .task { if onboarding.isTutorialActive { TutorialState.shared.start() } }
        // Spoken turns join the same saved chat the sheet shows, so the owner can read them back later.
        .fullScreenCover(isPresented: $isLiveVoicePresented) {
            AssistantLiveView(
                history: { ConversationStore.shared.currentAPIHistory },
                onTurn: { turn in
                    ConversationStore.shared.recordLiveTurn(
                        role: turn.role == .owner ? .owner : .assistant, text: turn.text, items: turn.items,
                        agent: turn.agent
                    )
                }
            )
        }
        // Over the assistant bar's own slot, so the notice never hides the row that just changed.
        // The overlay spans the window, so it takes touches only while a toast is on screen.
        // While the first-launch cover is up, it draws the toast itself.
        .overlay { if !onboarding.isPresented { ToastHost().allowsHitTesting(app.toast != nil) } }
        // Server-phrased dates (오늘, 내일) are rebuilt by reloading once the day turns over.
        // Inquiries load on every tab, so their recovery is the app's "back online" moment.
        .onChange(of: store.inquiryLoadError == nil) { wasOK, isOK in
            if isOK && !wasOK { app.showToast("연결이 돌아왔어요", seconds: 2) }
        }
        .onReceive(NotificationCenter.default.publisher(for: .NSCalendarDayChanged)) { _ in
            app.dataDidChange()
        }
        .task(id: app.dataVersion) {
            await store.loadInquiries()
            await app.refreshAttention()
        }
        // Launch already loads every screen, so only a return from the background reloads.
        .onChange(of: scenePhase) { _, phase in
            switch phase {
            case .background:
                wasInBackground = true
            case .active where wasInBackground:
                wasInBackground = false
                app.dataDidChange()
            default:
                break
            }
        }
        .sensoryFeedback(.success, trigger: app.successCount)
        // An alert here would close a sheet or cover this view presents, so each of those shows its own.
        .failureAlert(isActive: !isAssistantPresented && !isLiveVoicePresented)
    }
}
