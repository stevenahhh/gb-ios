import SwiftUI

/// Everything the assistant did, newest first: its runs from the chat, from the voice mode, and of its own
/// accord, together with the drafts and notices it wrote this week.
struct ActivityFeed {
    enum Entry: Identifiable {
        case run(AgentRun)
        case record(AssistantActivity)

        var id: String {
            switch self {
            case .run(let run): "run.\(run.id)"
            case .record(let activity): "record.\(activity.id)"
            }
        }

        var date: Date? {
            switch self {
            case .run(let run): run.date
            case .record(let activity): activity.date
            }
        }

        /// A draft or notice the assistant wrote unasked counts as its own initiative.
        var source: AgentRunSource {
            switch self {
            case .run(let run): run.source
            case .record: .proactive
            }
        }
    }

    let entries: [Entry]

    init(runs: [AgentRun], records: [AssistantActivity]) {
        // A run that looked and found nothing to do or to say is not something the assistant did.
        let told = runs.filter { run in
            !run.steps.isEmpty || run.answer?.isEmpty == false || run.status != .done
        }
        entries = (told.map(Entry.run) + records.map(Entry.record))
            .sorted { ($0.date ?? .distantPast) > ($1.date ?? .distantPast) }
    }

    /// 오늘, 어제, then earlier days, each keeping its newest entry first.
    static func days(_ entries: [Entry], now: Date = .now) -> [(title: String, items: [Entry])] {
        Dictionary(grouping: entries) { Calendar.workshop.startOfDay(for: $0.date ?? now) }
            .sorted { $0.key > $1.key }
            .map { (RelativeDayFormatter.day($0.key, now: now), $0.value) }
    }
}

enum ActivityFilter: String, CaseIterable, Identifiable {
    case all = "전체"
    case chat = "채팅"
    case voice = "음성"
    case proactive = "먼저 챙김"

    var id: Self { self }

    func includes(_ source: AgentRunSource) -> Bool {
        switch self {
        case .all: true
        case .chat: source == .chat
        case .voice: source == .voice
        case .proactive: source == .proactive
        }
    }

    var emptyTitle: String {
        switch self {
        case .all: "이번 주에 \(AssistantIdentity.name)가 한 일이 없어요"
        case .chat: "채팅으로 맡긴 일이 없어요"
        case .voice: "말로 맡긴 일이 없어요"
        case .proactive: "\(AssistantIdentity.name)가 먼저 챙긴 일이 없어요"
        }
    }
}

extension AgentRunSource {
    var label: String {
        switch self {
        case .chat: ActivityFilter.chat.rawValue
        case .voice: ActivityFilter.voice.rawValue
        case .proactive: ActivityFilter.proactive.rawValue
        }
    }
}

/// The history as a list: the source filter, then each day's runs and records. `record` draws a draft or notice
/// the way the screen that owns those rows already does.
struct ActivityFeedList<Record: View>: View {
    let entries: [ActivityFeed.Entry]
    @Binding var filter: ActivityFilter
    let reload: () async -> Void
    @ViewBuilder let record: (AssistantActivity) -> Record

    var body: some View {
        let shown = entries.filter { filter.includes($0.source) }
        List {
            Section {
                Picker("보기", selection: $filter) {
                    ForEach(ActivityFilter.allCases) { Text($0.rawValue).tag($0) }
                }
                .adaptivePickerStyle()
                .accessibilityIdentifier("activity.filter")
                .listRowInsets(EdgeInsets())
                .listRowBackground(Color.clear)
            }
            .listSectionSeparator(.hidden)

            if shown.isEmpty {
                Section {
                    ContentUnavailableView {
                        Label(filter.emptyTitle, systemImage: "tray")
                    } actions: {
                        Button("전체 보기") { filter = .all }
                            .buttonStyle(.bordered)
                            .controlSize(.large)
                    }
                    .listRowBackground(Color.clear)
                    .accessibilityIdentifier("activity.filter.empty")
                }
                .listSectionSeparator(.hidden)
            } else {
                ForEach(ActivityFeed.days(shown), id: \.title) { day in
                    CardSection(day.title) {
                        ForEach(day.items) { entry in
                            switch entry {
                            case .run(let run): ActivityRunRow(run: run)
                            case .record(let activity): record(activity)
                            }
                        }
                    }
                }
            }
        }
        .cardList()
        .refreshable { await reload() }
    }
}

/// One run: when and how it was asked, the owner's words, the assistant's answer, then each step it took.
private struct ActivityRunRow: View {
    let run: AgentRun
    @Environment(\.dynamicTypeSize) private var dynamicTypeSize

    var body: some View {
        let layout = dynamicTypeSize.isAccessibilitySize
            ? AnyLayout(VStackLayout(alignment: .leading, spacing: 4))
            : AnyLayout(HStackLayout(alignment: .firstTextBaseline, spacing: 10))
        layout {
            Text(run.date?.clockTime ?? "")
                .font(.subheadline.monospacedDigit())
                .foregroundStyle(Color.secondaryText)
            VStack(alignment: .leading, spacing: 10) {
                VStack(alignment: .leading, spacing: 2) {
                    Text(verbatim: run.question)
                        .font(.body)
                    Text(run.source.label)
                        .font(.subheadline)
                        .foregroundStyle(Color.secondaryText)
                    if let answer = run.answer, !answer.isEmpty {
                        Text(AssistantSheet.rendered(answer))
                            .font(.subheadline)
                            .foregroundStyle(Color.secondaryText)
                            .lineLimit(3)
                    }
                }
                .accessibilityElement(children: .combine)
                .accessibilityIdentifier("activity.run.\(run.id)")
                status
                if !run.steps.isEmpty {
                    AgentStepList(steps: run.steps, proposals: run.proposals)
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        .padding(.vertical, 4)
    }

    @ViewBuilder
    private var status: some View {
        switch run.status {
        case .queued, .running:
            StatusBadge(Status(text: "처리 중", tone: .progress))
        case .stopped:
            note("\(AssistantIdentity.name)를 멈춰서 여기까지만 했어요.", symbol: "pause.circle")
        case .failed:
            note("끝까지 처리하지 못했어요.", symbol: "exclamationmark.circle")
        case .done, .fallback:
            EmptyView()
        }
    }

    private func note(_ text: String, symbol: String) -> some View {
        HStack(alignment: .firstTextBaseline, spacing: 6) {
            Image(systemName: symbol)
                .foregroundStyle(Color.secondaryText)
                .accessibilityHidden(true)
            Text(verbatim: text)
        }
        .font(.subheadline)
    }
}
