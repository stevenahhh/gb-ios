import SwiftUI

/// The 운영 row that opens the outreach quotes.
struct OutreachQuoteLink: View {
    var body: some View {
        NavigationLink {
            OutreachQuoteListView()
        } label: {
            Label {
                Text("출장 수업 견적")
                Text("기관에서 온 문의를 읽고 맡을 만한지 따져 봐요")
                    .foregroundStyle(Color.secondaryText)
            } icon: {
                MenuIcon(systemName: "doc.text")
            }
        }
        .accessibilityIdentifier("operations.outreach")
    }
}

/// The 설정 row that opens the class cost cards.
struct OutreachCostLink: View {
    var body: some View {
        NavigationLink {
            ClassCostListView()
        } label: {
            Label { Text("수업마다 드는 돈") } icon: { MenuIcon(systemName: "wonsign.circle") }
        }
        .accessibilityIdentifier("settings.classCosts")
    }
}
