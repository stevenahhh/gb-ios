import SwiftUI

struct SettingsView: View {
    private struct Row: Identifiable {
        let title: String
        let systemImage: String
        var id: String { title }
    }

    private let studioRows = [
        Row(title: "공방 정보", systemImage: "storefront"),
        Row(title: "예약·환불 규정", systemImage: "doc.text"),
        Row(title: "고객 안내 문구", systemImage: "text.bubble"),
        Row(title: "채널 연결", systemImage: "link"),
    ]

    private let teamRows = [
        Row(title: "직원·권한", systemImage: "person.2"),
    ]

    private let personalRows = [
        Row(title: "알림", systemImage: "bell"),
        Row(title: "계정", systemImage: "person.crop.circle"),
    ]

    var body: some View {
        NavigationStack {
            List {
                Section {
                    Label {
                        VStack(alignment: .leading, spacing: 2) {
                            Text("오롯 공방")
                                .font(.headline)
                            Text("사장님")
                                .font(.subheadline)
                                .foregroundStyle(.secondary)
                        }
                    } icon: {
                        Image(systemName: "storefront.circle.fill")
                            .font(.largeTitle)
                            .foregroundStyle(.tint)
                    }
                    .accessibilityElement(children: .combine)
                }

                Section("공방") {
                    rows(studioRows)
                }

                Section("팀") {
                    rows(teamRows)
                }

                Section("나") {
                    rows(personalRows)
                }

                Section {
                    rows([Row(title: "도움말", systemImage: "questionmark.circle")])
                }
            }
            .listStyle(.insetGrouped)
            .navigationTitle("설정")
        }
    }

    private func rows(_ rows: [Row]) -> some View {
        ForEach(rows) { row in
            NavigationLink {
                if row.title == "공방 정보" {
                    WorkshopInfoView()
                } else {
                    PlaceholderScreen(title: row.title, systemImage: row.systemImage)
                }
            } label: {
                Label(row.title, systemImage: row.systemImage)
            }
        }
    }
}

#Preview {
    SettingsView()
}
