import SwiftUI

struct BK06PolicyRow: View {
    @State private var loader = Loader<[BK06PolicyVersion]>()
    @Environment(AppModel.self) private var app

    var body: some View {
        NavigationLink { BK06PolicyView() } label: {
            LabeledContent {
                if let version = loader.value?.first?.version { Text("\(version)판") }
            } label: {
                // Named apart from 예약·환불 규정 (what the assistant quotes): this table is what refunds are computed from.
                Label {
                    Text("환불 계산표")
                    Text("취소 문자에서 환불액을 계산해요")
                        .foregroundStyle(Color.secondaryText)
                } icon: { MenuIcon(systemName: "doc.text") }
            }
        }
        .accessibilityIdentifier("settings.k06Policy")
        .task(id: app.dataVersion) { await loader.load { try await RoundupAPI.k06Policies() } }
    }
}

struct BK06PolicyView: View {
    @State private var loader = Loader<[BK06PolicyVersion]>()
    @State private var isEditing = false
    @Environment(AppModel.self) private var app

    var body: some View {
        LoadableContent(loader: loader, retry: load) { versions in
            if let current = versions.first {
                list(current, versions)
            } else {
                ContentUnavailableView {
                    Label("아직 정한 규정이 없어요", systemImage: "doc.text")
                } description: {
                    Text(verbatim: "평소 안내하는 취소·환불 규정을\n말하거나 붙여넣으면 표로 정리해요.")
                        .foregroundStyle(Color.secondaryText)
                } actions: {
                    BK06PrimaryButton(title: "규정 말하기", identifier: "k06.policy.start") { isEditing = true }
                        .fixedSize()
                }
            }
        }
        .navigationTitle("환불 계산표")
        .navigationBarTitleDisplayMode(.inline)
        .task(id: app.dataVersion) { await load() }
        .navigationDestination(isPresented: $isEditing) { BK06PolicyEditor() }
    }

    private func load() async {
        await loader.load { try await RoundupAPI.k06Policies() }
    }

    private func list(_ current: BK06PolicyVersion, _ versions: [BK06PolicyVersion]) -> some View {
        List {
            BK06PolicyTable(version: current, title: "지금 규정 \(current.version)판")
            CardSection {
                BK06PrimaryButton(title: "규정 말하기", identifier: "k06.policy.start") { isEditing = true }
            }
            CardSection("판 이력") {
                ForEach(versions) { version in
                    NavigationLink {
                        List { BK06PolicyTable(version: version, title: "\(version.version)판") }
                            .cardList()
                            .navigationTitle("\(version.version)판")
                            .navigationBarTitleDisplayMode(.inline)
                    } label: {
                        VStack(alignment: .leading, spacing: 4) {
                            Text("\(version.version)판 · \(BK06Format.when(version.approvedAt))")
                            PhraseText(text: version.change).font(.subheadline).foregroundStyle(Color.secondaryText)
                        }
                    }
                }
            }
            CardSection {
                NavigationLink("취소·노쇼 기록") { BK06CaseListView() }
                    .accessibilityIdentifier("k06.cases")
            } footer: {
                BK06Disclaimer()
            }
        }
        .cardList()
        .refreshable { await load() }
    }
}

struct BK06PolicyTable: View {
    let version: BK06PolicyVersion
    let title: String

    var body: some View {
        CardSection {
            ForEach(version.rules, id: \.daysBefore) { BK06RuleRow(rule: $0) }
        } header: {
            Text(verbatim: title)
        }
        if !version.unread.isEmpty {
            CardSection("확인할 문장") {
                ForEach(version.unread, id: \.self) { BK06PendingLabel(text: $0) }
            }
        }
        CardSection("지각 기준") {
            if let late = version.late {
                BK06ValueRow(label: "\(late.lateMinutes)분 넘으면", value: "노쇼")
                if !late.note.isEmpty { Text(verbatim: late.note).font(.subheadline).foregroundStyle(Color.secondaryText) }
            } else {
                BK06PendingLabel(text: "정하지 않음")
            }
        }
    }
}

struct BK06RuleRow: View {
    let rule: BK06Rule

    var body: some View {
        LabeledContent {
            VStack(alignment: .trailing, spacing: 2) {
                if rule.refundPercent == nil {
                    BK06PendingLabel(text: rule.outcomeText)
                } else {
                    Text(verbatim: rule.outcomeText).foregroundStyle(Color.primary)
                }
                if !rule.extrasText.isEmpty {
                    Text(verbatim: rule.extrasText).font(.subheadline).foregroundStyle(Color.secondaryText)
                }
            }
        } label: {
            Text(verbatim: rule.dayText)
        }
    }
}

struct BK06PolicyEditor: View {
    @State private var text = ""
    @State private var rules: [BK06Rule] = []
    @State private var late: BK06LateRule?
    @State private var unread: [String] = []
    @State private var hasTable = false
    @State private var isReading = false
    @State private var errorMessage: String?
    @State private var editedDay: BK06EditedDay?
    @Environment(AppModel.self) private var app
    @Environment(\.dismiss) private var dismiss

    private var trimmed: String { text.trimmingCharacters(in: .whitespacesAndNewlines) }

    var body: some View {
        List {
            CardSection {
                TextField("3일 전까지 전액 환불, 당일 환불 불가처럼 적어 주세요", text: $text, axis: .vertical)
                    .lineLimit(5...14)
                    .accessibilityLabel("규정 문장")
                    .accessibilityIdentifier("k06.policy.text")
            } header: {
                Text("규정 문장")
            } footer: {
                Text("키보드의 마이크로 말하거나 지금 쓰는 안내문을 붙여넣어 주세요.")
            }
            if let errorMessage {
                CardSection { BK06ErrorRow(message: errorMessage) }
            }
            if isReading {
                CardSection { GeneratingIndicator(label: "규정을 표로 옮기고 있어요") }
            } else if hasTable {
                table
            } else {
                CardSection {
                    BK06PrimaryButton(title: "규정표 만들기", identifier: "k06.policy.extract") { extract() }
                        .disabled(trimmed.isEmpty)
                }
            }
        }
        .cardList()
        .navigationTitle("규정 말하기")
        .navigationBarTitleDisplayMode(.inline)
        .sheet(item: $editedDay) { day in
            BK06RuleEditor(rule: rules[day.index], takenDays: Set(rules.map(\.daysBefore)).subtracting([rules[day.index].daysBefore])) { rules[day.index] = $0 }
        }
    }

    @ViewBuilder
    private var table: some View {
        CardSection {
            ForEach(Array(rules.enumerated()), id: \.element.daysBefore) { index, rule in
                Button { editedDay = BK06EditedDay(index: index) } label: { BK06RuleRow(rule: rule) }
                    .foregroundStyle(Color.primary)
            }
            Button("행 추가", systemImage: "plus") { addRule() }
        } header: {
            Text("규정표")
        } footer: {
            Text("행을 누르면 고칠 수 있어요. 정하지 않은 조건은 계산하지 않고 사장님께 여쭤 봐요.")
        }
        if !unread.isEmpty {
            CardSection {
                ForEach(unread, id: \.self) { line in
                    VStack(alignment: .leading, spacing: 8) {
                        BK06PendingLabel(text: line)
                        Button("표에 반영했어요") { unread.removeAll { $0 == line } }
                            .buttonStyle(.bordered)
                    }
                }
            } header: {
                Text("확인할 문장")
            } footer: {
                Text("환불이나 취소에 관한 문장이 남아 있으면 금액을 정하지 않아요. 위 표를 고친 뒤 눌러 주세요.")
            }
        }
        CardSection("지각 기준") {
            Toggle("늦으면 노쇼로 보기", isOn: Binding(
                get: { late != nil }, set: { late = $0 ? BK06LateRule(lateMinutes: 15, note: "") : nil }))
            if let current = late {
                Stepper("\(current.lateMinutes)분 넘으면 노쇼", value: Binding(
                    get: { current.lateMinutes },
                    // The quoted sentence no longer matches a changed threshold.
                    set: { late = BK06LateRule(lateMinutes: $0, note: "") }), in: 5...180, step: 5)
            }
        }
        CardSection {
            BK06PrimaryButton(title: "이 규정으로 저장", isBusy: app.isRunning("k06.policy"), identifier: "k06.policy.save") { save() }
                .disabled(rules.isEmpty)
            Button("문장 다시 읽기") { extract() }
                .disabled(trimmed.isEmpty)
        } footer: {
            BK06Disclaimer()
        }
    }

    private func addRule() {
        let used = Set(rules.map(\.daysBefore))
        guard let day = (0...365).first(where: { !used.contains($0) }) else { return }
        rules.append(BK06Rule(daysBefore: day))
        rules.sort { $0.daysBefore > $1.daysBefore }
        editedDay = rules.firstIndex { $0.daysBefore == day }.map(BK06EditedDay.init)
    }

    private func extract() {
        isReading = true
        errorMessage = nil
        Task {
            do {
                let draft = try await RoundupAPI.k06Extract(text: trimmed)
                (rules, late, unread) = (draft.rules, draft.late, draft.unread)
                hasTable = true
            } catch {
                errorMessage = "규정을 읽지 못했어요. 다시 시도해 주세요."
            }
            isReading = false
        }
    }

    private func save() {
        Task {
            if await app.run(id: "k06.policy", {
                _ = try await RoundupAPI.k06SavePolicy(rules: rules, late: late, unread: unread, sourceText: trimmed)
            }) { dismiss() }
        }
    }
}

struct BK06EditedDay: Identifiable {
    let index: Int
    var id: Int { index }
}

struct BK06RuleEditor: View {
    @State var rule: BK06Rule
    let takenDays: Set<Int>
    let onSave: (BK06Rule) -> Void
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            List {
                CardSection {
                    Stepper(rule.dayText, value: $rule.daysBefore, in: 0...365)
                    if takenDays.contains(rule.daysBefore) { BK06ErrorRow(message: "같은 날짜의 행이 이미 있어요.") }
                    Toggle("환불 비율 정하기", isOn: Binding(
                        get: { rule.refundPercent != nil }, set: { rule.refundPercent = $0 ? 50 : nil }))
                    if let percent = rule.refundPercent {
                        Stepper(rule.outcomeText, value: Binding(
                            get: { percent }, set: { rule.refundPercent = $0 }), in: 0...100, step: 5)
                    }
                    Toggle("재료비 공제", isOn: $rule.deductMaterial)
                    Toggle("이월 가능", isOn: $rule.carryOverAllowed)
                }
            }
            .cardList()
            .navigationTitle("규정 행")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("닫기") { dismiss() } }
                ToolbarItem(placement: .confirmationAction) {
                    Button("적용") {
                        onSave(rule)
                        dismiss()
                    }
                    .disabled(takenDays.contains(rule.daysBefore))
                }
            }
        }
    }
}

struct BK06CaseListView: View {
    @State private var loader = Loader<[BK06Case]>()
    @State private var removing: BK06Case?
    @Environment(AppModel.self) private var app

    var body: some View {
        LoadableContent(loader: loader, retry: load) { cases in
            if cases.isEmpty {
                ContentUnavailableView("아직 기록이 없어요", systemImage: "tray")
            } else {
                List {
                    CardSection {
                        ForEach(cases) { item in
                            VStack(alignment: .leading, spacing: 4) {
                                Text(verbatim: [item.customerName, item.title].compactMap { $0 }.joined(separator: " · "))
                                PhraseText(text: [BK06Format.day(item.decidedAt), item.reason].filter { !$0.isEmpty }
                                    .joined(separator: " · "))
                                    .font(.subheadline)
                                    .foregroundStyle(Color.secondaryText)
                            }
                            .swipeActions {
                                if item.bookingId != nil { Button("지우기", role: .destructive) { removing = item } }
                            }
                        }
                    } footer: {
                        Text("손님이 삭제를 요청하면 왼쪽으로 밀어 그 예약의 기록을 모두 지워 주세요. 이 기록은 우리 공방에서만 보여요.")
                    }
                }
                .cardList()
            }
        }
        .navigationTitle("취소·노쇼 기록")
        .navigationBarTitleDisplayMode(.inline)
        .task(id: app.dataVersion) { await load() }
        .confirmationDialog("이 예약의 기록을 모두 지울까요?", isPresented: Binding(
            get: { removing != nil }, set: { if !$0 { removing = nil } }), titleVisibility: .visible) {
            Button("기록 지우기", role: .destructive) {
                guard let id = removing?.bookingId else { return }
                Task { await app.run(id: "k06.remove") { try await RoundupAPI.k06RemoveCases(bookingID: id) } }
            }
        }
    }

    private func load() async { await loader.load { try await RoundupAPI.k06Cases() } }
}
