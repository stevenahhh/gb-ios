import SwiftUI

/// "비서가 한 일": each run of the assistant with its steps and their undo, and each draft or notice it wrote
/// this week with the facts it used.
struct AssistantActivityView: View {
    @State private var loader = Loader<ActivityFeed>()
    @State private var filter = ActivityFilter.all
    @Environment(AppModel.self) private var app

    var body: some View {
        LoadableContent(loader: loader, retry: load) { feed in
            if feed.entries.isEmpty {
                ContentUnavailableView(ActivityFilter.all.emptyTitle, systemImage: "clock")
                    .accessibilityIdentifier("activity.empty")
            } else {
                ActivityFeedList(entries: feed.entries, filter: $filter, reload: load) { ActivityRow(activity: $0) }
            }
        }
        .navigationTitle("\(AssistantIdentity.name)가 한 일")
        .navigationBarTitleDisplayMode(.inline)
        .task(id: app.dataVersion) { await load() }
    }

    private func load() async {
        await loader.load {
            async let runs = RoundupAPI.agentRuns()
            async let records = RoundupAPI.assistantActivities()
            return try await ActivityFeed(runs: runs, records: records)
        }
    }
}

extension Date {
    /// 24-hour, like the rest of the app ("15:02").
    var clockTime: String {
        let parts = Calendar.workshop.dateComponents([.hour, .minute], from: self)
        return String(format: "%02d:%02d", parts.hour ?? 0, parts.minute ?? 0)
    }
}

private struct ActivityRow: View {
    let activity: AssistantActivity

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack(alignment: .firstTextBaseline, spacing: 10) {
                Text(activity.date?.clockTime ?? "")
                    .font(.subheadline.monospacedDigit())
                    .foregroundStyle(Color.secondaryText)
                // The badge sits under the sentence, so the sentence keeps the row's width.
                VStack(alignment: .leading, spacing: 6) {
                    Text(verbatim: activity.summary)
                        .font(.body)
                    if let status = activity.status {
                        StatusBadge(Status(text: status, tone: .attention))
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
            }
            NavigationLink {
                ActivityEvidenceView(activity: activity)
            } label: {
                Text("왜 그랬는지")
                    .font(.subheadline.weight(.semibold))
                    .frame(minHeight: 44, alignment: .leading)
            }
            .accessibilityIdentifier("activity.evidence.\(activity.id)")
        }
        .padding(.vertical, 2)
    }
}

/// The facts the assistant used, like 답변 근거 on a draft, and a way to the item itself.
struct ActivityEvidenceView: View {
    let activity: AssistantActivity

    var body: some View {
        List {
            CardSection("\(AssistantIdentity.name)가 한 일") {
                Text(verbatim: activity.summary)
            }
            CardSection("이유", footer: "일하면서 \(AssistantIdentity.name)가 들여다본 우리 공방 정보예요.") {
                ForEach(activity.evidence, id: \.self) { Text(verbatim: $0) }
            }
            CardSection {
                NavigationLink("펼쳐 보기", value: activity.route)
            }
        }
        .cardList()
        .navigationTitle("이유")
        .navigationBarTitleDisplayMode(.inline)
    }
}

/// "비서에게 맡기기": how far the assistant may go on each kind of work. Stored on this device.
struct AssistantDelegationView: View {
    enum Level: String, CaseIterable, Identifiable {
        case alone = "혼자"
        case ask = "물어보고"
        case never = "안 함"
        var id: Self { self }
    }

    struct Job: Identifiable {
        let key: String
        let title: String
        let defaultLevel: Level
        /// Sending needs a connected channel, so the choice is saved now and applies later.
        let needsChannel: Bool
        var id: String { key }
    }

    static let jobs = [
        Job(key: "draftReplies", title: "문의 답장 초안 준비", defaultLevel: .alone, needsChannel: false),
        Job(key: "sendReplies", title: "손님께 답장 전송", defaultLevel: .ask, needsChannel: true),
        Job(key: "depositNotices", title: "예약금 안내 문자 전송", defaultLevel: .ask, needsChannel: true),
        Job(key: "invoices", title: "송장 등록", defaultLevel: .ask, needsChannel: false),
        Job(key: "posts", title: "홍보 글 게시", defaultLevel: .never, needsChannel: true),
    ]

    var body: some View {
        List {
            CardSection("일마다 어디까지 맡길지", footer: "돈이 오가거나 밖으로 나가는 일, 그러니까 보내기와 결제, 전화는 설정에 상관없이 매번 사장님께 물어봐요.") {
                ForEach(Self.jobs) { DelegationRow(job: $0) }
            }
        }
        .cardList()
        .navigationTitle("\(AssistantIdentity.name)에게 맡길 일")
        .navigationBarTitleDisplayMode(.inline)
    }
}

private struct DelegationRow: View {
    let job: AssistantDelegationView.Job
    @AppStorage private var level: String

    init(job: AssistantDelegationView.Job) {
        self.job = job
        _level = AppStorage(wrappedValue: job.defaultLevel.rawValue, "delegation.\(job.key)")
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(job.title)
            Picker(job.title, selection: $level) {
                ForEach(AssistantDelegationView.Level.allCases) { Text($0.rawValue).tag($0.rawValue) }
            }
            .pickerStyle(.segmented)
            .accessibilityIdentifier("delegation.\(job.key)")
            if job.needsChannel && level != AssistantDelegationView.Level.never.rawValue {
                Text("채널을 연결해야 실제로 움직여요")
                    .font(.subheadline)
                    .foregroundStyle(Color.secondaryText)
            }
        }
        .padding(.vertical, 4)
    }
}
