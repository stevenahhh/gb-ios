import SwiftUI

struct MoreView: View {
    private struct Row: Identifiable {
        let title: String
        let systemImage: String
        var id: String { title }
    }

    private let workRows = [
        Row(title: "기회", systemImage: "sparkles"),
        Row(title: "리포트", systemImage: "chart.bar.xaxis"),
    ]

    private let settingRows = [
        Row(title: "공방 정보", systemImage: "storefront"),
        Row(title: "규정", systemImage: "doc.text"),
        Row(title: "알림 문구", systemImage: "text.bubble"),
        Row(title: "연결", systemImage: "link"),
        Row(title: "직원·권한", systemImage: "person.2"),
        Row(title: "내 계정", systemImage: "person.crop.circle"),
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
                }

                Section("공방 운영") {
                    rows(workRows)
                }

                Section("설정") {
                    rows(settingRows)
                }

                Section {
                    rows([Row(title: "도움말", systemImage: "questionmark.circle")])
                }
            }
            .listStyle(.insetGrouped)
            .navigationTitle("더보기")
        }
    }

    private func rows(_ rows: [Row]) -> some View {
        ForEach(rows) { row in
            NavigationLink {
                PlaceholderScreen(title: row.title, systemImage: row.systemImage)
            } label: {
                Label(row.title, systemImage: row.systemImage)
            }
        }
    }
}

#Preview {
    MoreView()
}
