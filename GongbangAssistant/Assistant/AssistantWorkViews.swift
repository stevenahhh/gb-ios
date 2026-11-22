import SwiftUI

/// "비서가 한 일": what the assistant drafted or noticed this week, each with the facts it used.
struct AssistantActivityView: View {
    @State private var loader = Loader<[AssistantActivity]>()
    @Environment(AppModel.self) private var app

    var body: some View {
        LoadableContent(loader: loader, retry: load) { activities in
            if activities.isEmpty {
                ContentUnavailableView("이번 주에 \(AssistantIdentity.name)가 한 일이 없어요", systemImage: "clock")
            } else {
                List {
                    ForEach(Self.days(activities), id: \.title) { day in
                        CardSection(day.title) {
                            ForEach(day.items) { ActivityRow(activity: $0) }
                        }
                    }
                }
                .cardList()
                .refreshable { await load() }
            }
        }
        .navigationTitle("\(AssistantIdentity.name)가 한 일")
        .navigationBarTitleDisplayMode(.inline)
        .task(id: app.dataVersion) { await load() }
    }

    private func load() async {
        await loader.load { try await RoundupAPI.assistantActivities() }
    }

    /// 오늘, 어제, then the rest of the week, keeping the server's newest-first order.
    static func days(_ activities: [AssistantActivity], now: Date = .now) -> [(title: String, items: [AssistantActivity])] {
        let calendar = Calendar.workshop
        func title(_ activity: AssistantActivity) -> String {
            guard let date = activity.date else { return "이번 주" }
            if calendar.isDate(date, inSameDayAs: now) { return "오늘" }
            if let yesterday = calendar.date(byAdding: .day, value: -1, to: now), calendar.isDate(date, inSameDayAs: yesterday) {
                return "어제"
            }
            return "이번 주"
        }
        return ["오늘", "어제", "이번 주"].compactMap { name in
            let items = activities.filter { title($0) == name }
            return items.isEmpty ? nil : (name, items)
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
                Text("이유 보기")
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
            CardSection("이유", footer: "\(AssistantIdentity.name)가 참고한 공방 정보예요.") {
                ForEach(activity.evidence, id: \.self) { Text(verbatim: $0) }
            }
            CardSection {
                NavigationLink("자세히 보기", value: activity.route)
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
        Job(key: "draftReplies", title: "문의 답변 초안 쓰기", defaultLevel: .alone, needsChannel: false),
        Job(key: "sendReplies", title: "손님에게 답변 보내기", defaultLevel: .ask, needsChannel: true),
        Job(key: "depositNotices", title: "예약금 안내 보내기", defaultLevel: .ask, needsChannel: true),
        Job(key: "invoices", title: "송장 등록", defaultLevel: .ask, needsChannel: false),
        Job(key: "posts", title: "홍보 글 올리기", defaultLevel: .never, needsChannel: true),
    ]

    var body: some View {
        List {
            CardSection("일마다 맡길 범위", footer: "보내기·결제·전화는 설정과 상관없이 항상 한 번 더 확인받아요.") {
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
                Text("채널을 연결하면 적용돼요")
                    .font(.subheadline)
                    .foregroundStyle(Color.secondaryText)
            }
        }
        .padding(.vertical, 4)
    }
}
