#if BUILD_B
import SwiftUI

/// The 운영 row that opens the outreach quotes.
struct OutreachQuoteLink: View {
    var body: some View {
        NavigationLink {
            OutreachQuoteListView()
        } label: {
            Label {
                Text("출강 견적")
                Text("기관 문의를 읽고 받을지 판단해요")
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
            Label { Text("수업별 원가") } icon: { MenuIcon(systemName: "wonsign.circle") }
        }
        .accessibilityIdentifier("settings.classCosts")
    }
}
#endif
