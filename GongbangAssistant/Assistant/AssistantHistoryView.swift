import SwiftUI

/// "지난 대화": saved conversations by the day they were last used. Picking one returns to the chat with it open.
struct AssistantHistoryView: View {
    @Environment(\.dismiss) private var dismiss
    private let store = ConversationStore.shared

    var body: some View {
        Group {
            if store.conversations.isEmpty {
                ContentUnavailableView {
                    Label("아직 나눈 이야기가 없어요", systemImage: "clock.arrow.circlepath")
                } description: {
                    Text("궁금해서 \(AssistantIdentity.name)에게 여쭤보신 것들이 차곡차곡 쌓이는 곳이에요.")
                        .foregroundStyle(Color.secondaryText)
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity)
            } else {
                List {
                    ForEach(Self.days(store.conversations), id: \.title) { day in
                        CardSection(day.title) {
                            ForEach(day.conversations) { conversation in
                                Button {
                                    store.open(conversation.id)
                                    dismiss()
                                } label: {
                                    HistoryRow(conversation: conversation)
                                }
                                .swipeActions(edge: .trailing, allowsFullSwipe: false) {
                                    Button("대화 지우기", systemImage: "trash", role: .destructive) {
                                        store.delete(conversation.id)
                                    }
                                }
                                .accessibilityIdentifier("history.\(conversation.id.uuidString)")
                            }
                        }
                    }
                }
                .cardList(onPage: false)
            }
        }
        .navigationTitle("이전 대화 목록")
        .navigationBarTitleDisplayMode(.inline)
    }

    /// 오늘, 어제, then earlier days, keeping the store's most-recent-first order.
    static func days(_ conversations: [ConversationStore.Conversation], now: Date = .now)
        -> [(title: String, conversations: [ConversationStore.Conversation])] {
        Dictionary(grouping: conversations) { Calendar.workshop.startOfDay(for: $0.updatedAt) }
            .sorted { $0.key > $1.key }
            .map { (RelativeDayFormatter.day($0.key, now: now), $0.value) }
    }
}

private struct HistoryRow: View {
    let conversation: ConversationStore.Conversation

    /// The start of the last answer, without its Markdown marks.
    private var preview: String? {
        conversation.turns.last { $0.role == .assistant }
            .map { String(AssistantSheet.rendered($0.text).characters).replacingOccurrences(of: "\n", with: " ") }
    }

    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: 10) {
            Text(conversation.updatedAt.clockTime)
                .font(.subheadline.monospacedDigit())
                .foregroundStyle(Color.secondaryText)
            VStack(alignment: .leading, spacing: 2) {
                Text(verbatim: conversation.title.isEmpty ? "새 대화" : conversation.title)
                    .font(.body.weight(.medium))
                    .foregroundStyle(.primary)
                    .lineLimit(2)
                if let preview {
                    Text(preview)
                        .font(.subheadline)
                        .foregroundStyle(Color.secondaryText)
                        .lineLimit(1)
                }
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .contentShape(.rect)
        .accessibilityElement(children: .combine)
    }
}
