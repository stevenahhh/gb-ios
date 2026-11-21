import SwiftUI

/// Every tab sits on the calendar's page: plain white (black in dark mode), with cards drawn as its light pinned boxes.
enum AppPalette {
    static let listBackground = CalendarTokens.background
    static let card = CalendarTokens.pinned
    /// The system inset-grouped radius (26pt on iOS 26 and 27), so a drawn box matches the list cards.
    static let cardRadius: CGFloat = 26
    /// A box that sits inside a card, such as draft text or a map.
    static let innerRadius: CGFloat = 18
}

extension Shape where Self == RoundedRectangle {
    static var card: RoundedRectangle { RoundedRectangle(cornerRadius: AppPalette.cardRadius, style: .continuous) }
    static var inner: RoundedRectangle { RoundedRectangle(cornerRadius: AppPalette.innerRadius, style: .continuous) }
}

extension EnvironmentValues {
    @Entry var cardSeparators: Visibility = .automatic
    /// Set when every card in a list has the same status, which the list then states once.
    @Entry var hidesCardStatus = false
}

extension View {
    // The inset-grouped style rounds every card with the system radius, the same in light and dark mode.
    func cardList(separators: Visibility = .automatic) -> some View {
        listStyle(.insetGrouped)
            .scrollContentBackground(.hidden)
            .background(AppPalette.listBackground)
            .listSectionSpacing(20)
            .environment(\.cardSeparators, separators)
    }
}

struct CardSection<Content: View, Header: View, Footer: View>: View {
    private let content: Content
    private let header: Header
    private let footer: Footer
    @Environment(\.cardSeparators) private var separators

    init(@ViewBuilder content: () -> Content,
         @ViewBuilder header: () -> Header,
         @ViewBuilder footer: () -> Footer) {
        self.content = content()
        self.header = header()
        self.footer = footer()
    }

    var body: some View {
        Section {
            ForEach(subviews: content) { row in
                row
                    .listRowBackground(AppPalette.card)
                    .listRowSeparator(separators)
            }
        } header: {
            // The system's grouped header gray measures about 3.7:1; headers that set their own color keep it.
            header.foregroundStyle(Color.secondaryText)
        } footer: {
            footer.foregroundStyle(Color.secondaryText)
        }
        .listSectionSeparator(.hidden)
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
