import SwiftUI

struct OutreachQuoteListView: View {
    @State private var loader = Loader<[OutreachQuoteRow]>()
    @State private var isReading = false
    @State private var opened: OutreachOpened?
    @Environment(AppModel.self) private var app

    var body: some View {
        LoadableContent(loader: loader, retry: load) { quotes in
            if quotes.isEmpty {
                ContentUnavailableView {
                    Label("아직 들어온 출장 수업 문의가 없어요", systemImage: "doc.text.magnifyingglass")
                } description: {
                    Text(verbatim: "기관에서 온 글을 붙이시면 금액을 뽑고 맡아도 괜찮을지까지 알려 드려요")
                        .foregroundStyle(Color.secondaryText)
                } actions: {
                    Button {
                        isReading = true
                    } label: {
                        Text("견적 새로 내기").foregroundStyle(Color(.systemBackground))
                    }
                    .buttonStyle(.borderedProminent)
                    .controlSize(.large)
                    .accessibilityIdentifier("outreach.new")
                }
            } else {
                list(quotes)
            }
        }
        .navigationTitle("출장 수업 견적")
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            if loader.value?.isEmpty == false {
                ToolbarItem(placement: .primaryAction) {
                    Button("견적 새로 내기", systemImage: "plus") { isReading = true }
                        .accessibilityIdentifier("outreach.new")
                }
            }
        }
        .sheet(isPresented: $isReading) {
            OutreachInquiryView { opened = $0 }
        }
        .navigationDestination(item: $opened) { OutreachQuoteDetailView(opened: $0) }
        .task(id: app.dataVersion) { await load() }
    }

    private func load() async {
        await loader.load { try await RoundupAPI.outreachQuotes() }
    }

    private func list(_ quotes: [OutreachQuoteRow]) -> some View {
        List {
            CardSection {
                ForEach(quotes) { quote in
                    NavigationLink {
                        OutreachQuoteDetailView(opened: OutreachOpened(id: quote.id, startedAt: nil))
                    } label: {
                        row(quote)
                    }
                    .accessibilityIdentifier("outreach.quote")
                }
            }
        }
        .cardList()
        .refreshable { await load() }
    }

    private func row(_ quote: OutreachQuoteRow) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            ViewThatFits(in: .horizontal) {
                HStack(alignment: .firstTextBaseline) {
                    Text(verbatim: quote.title).font(.headline)
                    Spacer()
                    StatusBadge(quote.status.badge)
                }
                VStack(alignment: .leading, spacing: 6) {
                    Text(verbatim: quote.title).font(.headline)
                    StatusBadge(quote.status.badge)
                }
            }
            PhraseText(text: quote.detail)
                .font(.subheadline)
                .foregroundStyle(Color.secondaryText)
            Text(OutreachFormat.won(quote.totalKrw))
                .monospacedDigit()
            if let due = quote.followUpDue {
                DueLabel(due: due)
            }
        }
    }
}
