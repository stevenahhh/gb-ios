import SwiftUI

struct SettingsView: View {
    @State private var loader = Loader<SettingsData>()
    @Environment(AppModel.self) private var app

    var body: some View {
        NavigationStack {
            LoadableContent(loader: loader, retry: load) { data in
                list(data)
            }
            .navigationTitle("설정")
            .navigationSubtitle(loader.value?.workshop?.name ?? "")
            .appDestinations()
        }
        .task(id: app.dataVersion) { await load() }
    }

    private func load() async {
        await loader.load { try await RoundupAPI.settings() }
    }

    private func list(_ data: SettingsData) -> some View {
        let sections = Dictionary(grouping: data.items, by: \.section)
        return List {
            CardSection {
                Label {
                    VStack(alignment: .leading, spacing: 2) {
                        Text(data.workshop?.name ?? "공방 정보를 입력해 주세요")
                            .font(.headline)
                        if let owner = data.workshop?.ownerTitle {
                            Text(owner)
                                .font(.subheadline)
                                .foregroundStyle(Color.secondaryText)
                        }
                    }
                } icon: {
                    Image(systemName: "storefront")
                        // A list multiplies a label icon's font by the large symbol scale; medium keeps title2 at 28pt.
                        .font(.title2)
                        .imageScale(.medium)
                        .symbolRenderingMode(.monochrome)
                        .foregroundStyle(.primary)
                }
                .accessibilityElement(children: .combine)
            }

            CardSection("공방") {
                NavigationLink {
                    WorkshopInfoView(workshop: data.workshop)
                } label: {
                    Label { Text("공방 정보") } icon: { MenuIcon(systemName: "storefront") }
                }
                .accessibilityIdentifier("settings.workshop")
                #if BUILD_B
                BK06PolicyRow()
                NavigationLink {
                    BK25FactCardListView()
                } label: {
                    Label { Text("수업 사실 카드") } icon: { MenuIcon(systemName: "list.bullet.rectangle") }
                }
                .accessibilityIdentifier("settings.factCards")
                #endif
                rows(sections["공방"] ?? [])
                NavigationLink {
                    ChannelStatusView(channels: data.channels)
                } label: {
                    Label { Text("채널 연결") } icon: { MenuIcon(systemName: "link") }
                }
                NavigationLink {
                    AssistantDelegationView()
                } label: {
                    Label { Text("\(AssistantIdentity.name)에게 맡기기") } icon: { MenuIcon(systemName: "hand.raised") }
                }
                .accessibilityIdentifier("settings.delegation")
                NavigationLink {
                    AssistantActivityView()
                } label: {
                    Label { Text("\(AssistantIdentity.name)가 한 일") } icon: { MenuIcon(systemName: "clock.arrow.circlepath") }
                }
                .accessibilityIdentifier("settings.activities")
                #if BUILD_B
                OutreachCostLink()
                #endif
            }

            if let support = sections["지원"] {
                CardSection { rows(support) }
            }
        }
        .cardList()
        .refreshable { await load() }
    }

    private func rows(_ items: [SettingItem]) -> some View {
        ForEach(items) { item in
            NavigationLink {
                SettingTextView(item: item)
            } label: {
                Label { Text(item.title) } icon: { MenuIcon(systemName: item.symbol) }
            }
        }
    }
}

struct ChannelStatusView: View {
    let channels: [WorkItem]

    var body: some View {
        List {
            CardSection {
                ForEach(channels) { WorkCard(item: $0) }
            } header: {
                if channels.allChannelsUnconnected { UnconnectedChannelsNote() }
            }
            .environment(\.hidesCardStatus, channels.allChannelsUnconnected)
        }
        .cardList()
        .navigationTitle("채널 연결")
        .navigationBarTitleDisplayMode(.inline)
    }
}

struct SettingTextView: View {
    let item: SettingItem
    @State private var text: String
    @Environment(AppModel.self) private var app
    @Environment(\.dismiss) private var dismiss

    init(item: SettingItem) {
        self.item = item
        _text = State(initialValue: item.body)
    }

    private var runID: String { "setting.\(item.key)" }

    var body: some View {
        List {
            CardSection {
                if item.isEditable {
                    KoreanTextEditor(text: $text)
                        .frame(minHeight: 200)
                        .accessibilityLabel(item.title)
                        .accessibilityIdentifier("setting.body")
                } else {
                    Text(item.body)
                        .textSelection(.enabled)
                }
            }
        }
        .cardList()
        .navigationTitle(item.title)
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            if item.isEditable {
                ToolbarItem(placement: .confirmationAction) {
                    // One button whose title is replaced by the spinner, so the toolbar item keeps its shape.
                    Button(action: save) {
                        BusyLabel(title: "저장", isBusy: app.isRunning(runID))
                    }
                    .disabled(app.isRunning(runID) || text == item.body
                        || text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                    .accessibilityIdentifier("setting.save")
                }
            }
        }
    }

    private func save() {
        let (key, body, revision) = (item.key, text, item.revision)
        Task {
            if await app.run(id: runID, {
                _ = try await RoundupAPI.saveSetting(key: key, body: body, revision: revision)
            }) { dismiss() }
        }
    }
}
