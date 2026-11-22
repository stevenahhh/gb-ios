import SwiftUI

struct OverdueEntry: Identifiable {
    let kind: EventKind
    let item: TaskItem
    var id: String { item.id }

    static func collect(_ groups: [TaskGroup], now: Date) -> [OverdueEntry] {
        groups.flatMap { group in
            group.items.filter { $0.isDone != true && $0.due?.isOverdue(at: now) == true }
                .map { OverdueEntry(kind: group.kind, item: $0) }
        }
        .sorted { ($0.item.due?.date ?? .distantPast) < ($1.item.due?.date ?? .distantPast) }
    }

    /// Tasks and parcels due before the workshop's today began. Work that became late earlier today stays in 할 일,
    /// and a class is never carried.
    static func beforeToday(_ groups: [TaskGroup], now: Date) -> [OverdueEntry] {
        let today = Calendar.workshop.startOfDay(for: now)
        return collect(groups, now: now).filter { entry in
            guard CarryOverTarget(entry.item) != nil, let date = entry.item.due?.date else { return false }
            return date < today
        }
    }
}

struct CarryOverQuestion: Identifiable {
    let id: String
    let isYesterday: Bool
    let entries: [OverdueEntry]

    var isCarried: Bool { entries.allSatisfy { $0.item.carriedOver == true } }

    var title: String {
        "\(isYesterday ? "어제 하지 못한 일을" : "지난 일을") 오늘 할 일에 \(isCarried ? "넣었어요" : "넣을까요?")"
    }

    var detail: String {
        guard let first = entries.first else { return "" }
        return entries.count == 1 ? first.item.title : "\(first.item.title) 외 \(entries.count - 1)건"
    }

    var targets: [CarryOverTarget] { entries.compactMap { CarryOverTarget($0.item) } }

    static func collect(_ groups: [TaskGroup], now: Date) -> [CarryOverQuestion] {
        make(OverdueEntry.beforeToday(groups, now: now).filter { $0.item.carriedOver != true }, now: now)
    }

    /// Answered questions, read from the server so their undo outlives the toast and a relaunch. One with work still
    /// waiting is left out: its question is on screen under the same id, and its list takes single items back.
    static func carried(_ groups: [TaskGroup], now: Date) -> [CarryOverQuestion] {
        let waiting = Set(collect(groups, now: now).map(\.id))
        return make(OverdueEntry.beforeToday(groups, now: now).filter { $0.item.carriedOver == true }, now: now)
            .filter { !waiting.contains($0.id) }
    }

    private static func make(_ entries: [OverdueEntry], now: Date) -> [CarryOverQuestion] {
        let yesterday = entries.filter { $0.item.due?.date?.isWorkshopYesterday(at: now) == true }
        let older = entries.filter { $0.item.due?.date?.isWorkshopYesterday(at: now) == false }
        return [
            CarryOverQuestion(id: "carryover.yesterday", isYesterday: true, entries: yesterday),
            CarryOverQuestion(id: "carryover.older", isYesterday: false, entries: older),
        ].filter { !$0.entries.isEmpty }
    }
}

private extension Date {
    func isWorkshopYesterday(at now: Date) -> Bool {
        let calendar = Calendar.workshop
        guard let yesterday = calendar.date(byAdding: .day, value: -1, to: now) else { return false }
        return calendar.isDate(self, inSameDayAs: yesterday)
    }
}

struct CarryOverRow: View {
    let question: CarryOverQuestion
    @State private var showsList = false
    @Environment(AppModel.self) private var app

    private var isRunning: Bool { app.isRunning(question.id) }

    var body: some View {
        AttentionRow(title: question.title, detail: question.detail, isOverdue: !question.isCarried) {
            if question.isCarried {
                AttentionButton(title: "되돌리기", isProminent: false, isBusy: isRunning) {
                    app.takeBack(question.targets, id: question.id)
                }
                .disabled(isRunning)
                .accessibilityIdentifier("carryover.undo.\(question.id)")
            } else {
                AttentionButton(title: "승인", isProminent: true, isBusy: isRunning) {
                    app.carryOver(question.targets, id: question.id)
                }
                .disabled(isRunning)
                .accessibilityIdentifier("carryover.approve.\(question.id)")
                AttentionButton(title: "고치기", isProminent: false, isBusy: false) {
                    showsList = true
                }
                .disabled(isRunning)
                .accessibilityIdentifier("carryover.edit.\(question.id)")
            }
        }
        .contentShape(.rect)
        .onTapGesture { showsList = true }
        .accessibilityAction(named: "목록 보기") { showsList = true }
        .navigationDestination(isPresented: $showsList) { OverdueListView() }
    }
}

/// Loads its own copy of the today screen, so checks made here show up without leaving the list.
/// Rows it has shown stay put once finished (the server drops a finished task's deadline), so a check can be undone in place.
struct OverdueListView: View {
    private struct Shown {
        let id: String
        /// Kept from before the row was finished, so it stays in its section.
        let due: Date
    }

    @State private var loader = Loader<TodayScreenData>()
    @State private var shown: [Shown] = []
    @Environment(AppModel.self) private var app

    var body: some View {
        LoadableContent(loader: loader, retry: load) { today in
            let rows = Dictionary(today.tasks.groups.flatMap { group in
                group.items.map { ($0.id, OverdueEntry(kind: group.kind, item: $0)) }
            }, uniquingKeysWith: { first, _ in first })
            let now = Date.now
            let yesterday = shown.filter { $0.due.isWorkshopYesterday(at: now) }.compactMap { rows[$0.id] }
            let older = shown.filter { !$0.due.isWorkshopYesterday(at: now) }.compactMap { rows[$0.id] }
            if yesterday.isEmpty && older.isEmpty {
                ContentUnavailableView("기한 지난 일이 없어요", systemImage: "checkmark.circle")
            } else {
                List {
                    section("어제 하지 못한 일", yesterday)
                    section("지난 일", older)
                }
                .cardList()
                .refreshable { await load() }
            }
        }
        .navigationTitle("기한 지난 일")
        .navigationBarTitleDisplayMode(.inline)
        .task(id: app.dataVersion) { await load() }
    }

    @ViewBuilder
    private func section(_ title: String, _ entries: [OverdueEntry]) -> some View {
        if !entries.isEmpty {
            CardSection {
                ForEach(entries) { OverdueListRow(entry: $0) }
            } header: {
                SectionHeader(title: "\(title) \(entries.filter { $0.item.isDone != true }.count)건")
            }
        }
    }

    private func load() async {
        await loader.load { try await RoundupAPI.today() }
        guard let groups = loader.value?.tasks.groups else { return }
        for entry in OverdueEntry.beforeToday(groups, now: .now) where !shown.contains(where: { $0.id == entry.id }) {
            guard let due = entry.item.due?.date else { continue }
            shown.append(Shown(id: entry.id, due: due))
        }
    }
}

private struct OverdueListRow: View {
    let entry: OverdueEntry
    @Environment(AppModel.self) private var app

    private var item: TaskItem { entry.item }
    private var isRunning: Bool { app.isRunning(item.id) }

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            TaskRow(item: item, kind: entry.kind, isInOverdueGroup: true)
            if item.isDone != true, let target = CarryOverTarget(item) {
                if item.carriedOver == true {
                    choice("되돌리기", identifier: "carryover.undo.\(item.id)") {
                        app.takeBack([target], id: item.id)
                    }
                } else {
                    choice("오늘 할 일에 넣기", identifier: "carryover.approve.\(item.id)") {
                        app.carryOver([target], id: item.id)
                    }
                }
            }
        }
    }

    private func choice(_ title: String, identifier: String, action: @escaping () -> Void) -> some View {
        AttentionButton(title: title, isProminent: false, isBusy: isRunning, action: action)
            .disabled(isRunning)
            .frame(maxWidth: .infinity, alignment: .trailing)
            .accessibilityLabel("\(item.title), \(title)")
            .accessibilityIdentifier(identifier)
    }
}

private extension AppModel {
    func carryOver(_ targets: [CarryOverTarget], id: String) {
        Task {
            guard await run(id: id, { try await RoundupAPI.carryOver(targets) }) else { return }
            showToast("오늘 할 일에 넣었어요") { [self] in
                await run(id: id) { try await RoundupAPI.undoCarryOver(targets) }
            }
        }
    }

    func takeBack(_ targets: [CarryOverTarget], id: String) {
        Task {
            guard await run(id: id, { try await RoundupAPI.undoCarryOver(targets) }) else { return }
            showToast("오늘 할 일에서 뺐어요") { [self] in
                await run(id: id) { try await RoundupAPI.carryOver(targets) }
            }
        }
    }
}
