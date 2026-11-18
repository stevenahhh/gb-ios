import SwiftUI
import RoundupCore

@main
struct GongbangAssistantApp: App {
    @State private var store = ProcessInfo.processInfo.arguments.contains("-sampleInquiries")
        ? DemoStore() : DemoStore(repository: APIInquiryRepository())

    var body: some Scene {
        WindowGroup {
            RootTabView()
                .environment(store)
        }
    }
}
