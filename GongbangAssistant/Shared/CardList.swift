import SwiftUI
import UIKit

enum AppPalette {
    static let listBackground = Color(uiColor: UIColor { @Sendable traits in
        traits.userInterfaceStyle == .dark
            ? UIColor(red: 16 / 255, green: 16 / 255, blue: 18 / 255, alpha: 1)
            : .systemGroupedBackground
    })
    static let card = Color(uiColor: UIColor { @Sendable traits in
        traits.userInterfaceStyle == .dark
            ? UIColor(red: 26 / 255, green: 26 / 255, blue: 29 / 255, alpha: 1)
            : .secondarySystemGroupedBackground
    })
}

extension EnvironmentValues {
    @Entry var cardSeparators: Visibility = .automatic
}

extension View {
    // Inset-grouped lists clip rows to a fixed system radius, so cards are drawn per row instead.
    func cardList(separators: Visibility = .automatic) -> some View {
        listStyle(.grouped)
            .scrollContentBackground(.hidden)
            .background(AppPalette.listBackground)
            .contentMargins(.horizontal, 16, for: .scrollContent)
            .listSectionSpacing(20)
            .environment(\.cardSeparators, separators)
    }
}

struct CardSection<Content: View, Header: View, Footer: View>: View {
    private let content: Content
    private let header: Header
    private let footer: Footer
    @Environment(\.cardSeparators) private var separators
    @Environment(\.colorScheme) private var colorScheme

    init(@ViewBuilder content: () -> Content,
         @ViewBuilder header: () -> Header,
         @ViewBuilder footer: () -> Footer) {
        self.content = content()
        self.header = header()
        self.footer = footer()
    }

    var body: some View {
        Section {
            Group(subviews: content) { rows in
                ForEach(rows) { row in
                    row
                        .listRowBackground(background(isFirst: row.id == rows.first?.id, isLast: row.id == rows.last?.id))
                        .listRowSeparator(separators)
                }
            }
        } header: {
            header
        } footer: {
            footer
        }
        .listSectionSeparator(.hidden)
    }

    private func background(isFirst: Bool, isLast: Bool) -> some View {
        let radius: CGFloat = colorScheme == .dark ? 14 : 26
        return UnevenRoundedRectangle(
            topLeadingRadius: isFirst ? radius : 0,
            bottomLeadingRadius: isLast ? radius : 0,
            bottomTrailingRadius: isLast ? radius : 0,
            topTrailingRadius: isFirst ? radius : 0,
            style: .continuous
        )
        .fill(AppPalette.card)
    }
}

extension CardSection where Header == EmptyView, Footer == EmptyView {
    init(@ViewBuilder content: () -> Content) {
        self.init(content: content, header: { EmptyView() }, footer: { EmptyView() })
    }
}

extension CardSection where Footer == EmptyView {
    init(@ViewBuilder content: () -> Content, @ViewBuilder header: () -> Header) {
        self.init(content: content, header: header, footer: { EmptyView() })
    }
}

extension CardSection where Header == Text, Footer == EmptyView {
    init(_ title: String, @ViewBuilder content: () -> Content) {
        self.init(content: content, header: { Text(title) }, footer: { EmptyView() })
    }
}

extension CardSection where Header == Text, Footer == Text {
    init(_ title: String, footer: String, @ViewBuilder content: () -> Content) {
        self.init(content: content, header: { Text(title) }, footer: { Text(footer) })
    }
}
