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
        }
        .task(id: app.dataVersion) { await load() }
    }

    private func load() async {
        await loader.load { try await RoundupAPI.settings() }
    }

    private func list(_ data: SettingsData) -> some View {
        let sections = Dictionary(grouping: data.items, by: \.section)
        return List {
            Section {
                Label {
                    VStack(alignment: .leading, spacing: 2) {
                        Text(data.workshop?.name ?? "공방 정보를 입력해 주세요")
                            .font(.headline)
                        if let owner = data.workshop?.ownerTitle {
                            Text(owner)
                                .font(.subheadline)
                                .foregroundStyle(.secondary)
                        }
                    }
                } icon: {
                    Image(systemName: "storefront.circle.fill")
                        .font(.largeTitle)
                        .foregroundStyle(.tint)
                }
                .accessibilityElement(children: .combine)
            }

            Section("공방") {
                NavigationLink {
                    WorkshopInfoView(workshop: data.workshop)
                } label: {
                    Label("공방 정보", systemImage: "storefront")
                }
                .accessibilityIdentifier("settings.workshop")
                rows(sections["공방"] ?? [])
                NavigationLink {
                    ChannelStatusView(channels: data.channels)
                } label: {
                    Label("채널 연결", systemImage: "link")
                }
            }

            if let support = sections["지원"] {
                Section { rows(support) }
            }
        }
        .listStyle(.insetGrouped)
        .refreshable { await load() }
    }

    private func rows(_ items: [SettingItem]) -> some View {
        ForEach(items) { item in
            NavigationLink {
                SettingTextView(item: item)
            } label: {
                Label(item.title, systemImage: item.symbol)
            }
        }
    }
}

struct ChannelStatusView: View {
    let channels: [WorkItem]

    var body: some View {
        List {
            Section {
                ForEach(channels) { WorkCard(item: $0) }
            } footer: {
                Text("채널 자동 연동은 아직 지원하지 않아요. 주문과 문의는 이 앱에 등록된 내용만 보여요.")
            }
        }
        .listStyle(.insetGrouped)
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
            if item.isEditable {
                TextEditor(text: $text)
                    .frame(minHeight: 200)
                    .accessibilityLabel(item.title)
                    .accessibilityIdentifier("setting.body")
            } else {
                Text(item.body)
                    .textSelection(.enabled)
            }
        }
        .listStyle(.insetGrouped)
        .navigationTitle(item.title)
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            if item.isEditable {
                ToolbarItem(placement: .confirmationAction) {
                    if app.isRunning(runID) {
                        ProgressView()
                    } else {
                        Button("저장", action: save)
                            .disabled(text == item.body || text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                            .accessibilityIdentifier("setting.save")
                    }
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
