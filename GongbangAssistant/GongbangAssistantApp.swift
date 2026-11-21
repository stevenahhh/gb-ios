import SwiftUI
import RoundupCore

@main
struct GongbangAssistantApp: App {
    @State private var store = InquiryStore(repository: APIInquiryRepository())
    @State private var app = AppModel()

    init() {
        LaunchTiming.appDidInit()
    }

    var body: some Scene {
        WindowGroup {
            RootTabView()
                .environment(store)
                .environment(app)
        }
    }
}
