import SwiftUI

struct BK06PolicyRow: View {
    @State private var loader = Loader<[BK06PolicyVersion]>()
    @Environment(AppModel.self) private var app

    var body: some View {
        NavigationLink { BK06PolicyView() } label: {
            LabeledContent {
                if let version = loader.value?.first?.version { Text("\(version)번째 규정") }
            } label: {
                // Named apart from 예약·환불 규정 (what the assistant quotes): this table is what refunds are computed from.
                Label {
                    Text("환불 금액 계산기")
                    Text("손님 취소 문자를 보고 돌려드릴 금액을 알려 드려요")
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
                    Label("아직 만들어 둔 규정이 없어요", systemImage: "doc.text")
                } description: {
                    Text(verbatim: "손님께 늘 안내하시던 취소, 환불 규정을\n불러 주시거나 붙여 넣어 주세요. 깔끔한 표로 바꿔 드릴게요.")
                        .foregroundStyle(Color.secondaryText)
                } actions: {
                    BK06PrimaryButton(title: "규정 말하기", identifier: "k06.policy.start") { isEditing = true }
                        .fixedSize()
                }
            }
        }
        .navigationTitle("환불 금액 계산기")
        .navigationBarTitleDisplayMode(.inline)
        .task(id: app.dataVersion) { await load() }
        .navigationDestination(isPresented: $isEditing) { BK06PolicyEditor() }
    }

    private func load() async {
        await loader.load { try await RoundupAPI.k06Policies() }
    }

    private func list(_ current: BK06PolicyVersion, _ versions: [BK06PolicyVersion]) -> some View {
        List {
            BK06PolicyTable(version: current, title: "현재 \(current.version)번째 규정")
            CardSection {
                BK06PrimaryButton(title: "규정 말하기", identifier: "k06.policy.start") { isEditing = true }
            }
            CardSection("이전 규정 기록") {
                ForEach(versions) { version in
                    NavigationLink {
                        List { BK06PolicyTable(version: version, title: "\(version.version)번째 규정") }
                            .cardList()
                            .navigationTitle("\(version.version)번째 규정")
                            .navigationBarTitleDisplayMode(.inline)
                    } label: {
                        VStack(alignment: .leading, spacing: 4) {
                            Text("\(version.version)번째 규정 · \(BK06Format.when(version.approvedAt))")
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
            CardSection("한 번 더 봐 주실 문장") {
                ForEach(version.unread, id: \.self) { BK06PendingLabel(text: $0) }
            }
        }
        CardSection("지각 기준") {
            if let late = version.late {
                BK06ValueRow(label: "\(late.lateMinutes)분 넘게 늦으면", value: "노쇼")
                if !late.note.isEmpty { Text(verbatim: late.note).font(.subheadline).foregroundStyle(Color.secondaryText) }
            } else {
                BK06PendingLabel(text: "아직 안 정했어요")
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
                TextField("예: 수업 3일 전까지는 전액 환불, 당일에는 환불 불가", text: $text, axis: .vertical)
                    .lineLimit(5...14)
                    .accessibilityLabel("규정 내용")
                    .accessibilityIdentifier("k06.policy.text")
            } header: {
                Text("규정 내용")
            } footer: {
                Text("키보드 마이크 버튼을 눌러 말씀하시거나 평소 보내시던 안내 문구를 통째로 붙여 넣어 주세요.")
            }
            if let errorMessage {
                CardSection { BK06ErrorRow(message: errorMessage) }
            }
            if isReading {
                CardSection { GeneratingIndicator(label: "받은 규정을 표에 옮겨 담는 중이에요") }
            } else if hasTable {
                table
            } else {
                CardSection {
                    BK06PrimaryButton(title: "표로 만들기", identifier: "k06.policy.extract") { extract() }
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
            Button("줄 추가", systemImage: "plus") { addRule() }
        } header: {
            Text("환불 규정표")
        } footer: {
            Text("고치고 싶은 줄을 톡 눌러 보세요. 빈칸으로 둔 경우는 앱이 멋대로 계산하지 않고 사장님 뜻을 물어볼게요.")
        }
        if !unread.isEmpty {
            CardSection {
                ForEach(unread, id: \.self) { line in
                    VStack(alignment: .leading, spacing: 8) {
                        BK06PendingLabel(text: line)
                        Button("표에 넣었어요") { unread.removeAll { $0 == line } }
                            .buttonStyle(.bordered)
                    }
                }
            } header: {
                Text("한 번 더 봐 주실 문장")
            } footer: {
                Text("옮기지 못한 글에 환불이나 취소 이야기가 있으면 얼마를 돌려줄지 비워 둘게요. 위쪽 표부터 손본 다음 눌러 주세요.")
            }
        }
        CardSection("지각 기준") {
            Toggle("늦게 오시면 노쇼로 치기", isOn: Binding(
                get: { late != nil }, set: { late = $0 ? BK06LateRule(lateMinutes: 15, note: "") : nil }))
            if let current = late {
                Stepper("\(current.lateMinutes)분 넘게 늦으면 노쇼", value: Binding(
                    get: { current.lateMinutes },
                    // The quoted sentence no longer matches a changed threshold.
                    set: { late = BK06LateRule(lateMinutes: $0, note: "") }), in: 5...180, step: 5)
            }
        }
        CardSection {
            BK06PrimaryButton(title: "이 규정 저장하기", isBusy: app.isRunning("k06.policy"), identifier: "k06.policy.save") { save() }
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
                errorMessage = "규정을 못 읽었어요. 조금 있다가 한 번 더 눌러 주세요."
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
                    if takenDays.contains(rule.daysBefore) { BK06ErrorRow(message: "그 날짜로 만든 줄이 벌써 있어요.") }
                    Toggle("환불 비율 고르기", isOn: Binding(
                        get: { rule.refundPercent != nil }, set: { rule.refundPercent = $0 ? 50 : nil }))
                    if let percent = rule.refundPercent {
                        Stepper(rule.outcomeText, value: Binding(
                            get: { percent }, set: { rule.refundPercent = $0 }), in: 0...100, step: 5)
                    }
                    Toggle("재료비 빼기", isOn: $rule.deductMaterial)
                    Toggle("다음 수업으로 넘기기 가능", isOn: $rule.carryOverAllowed)
                }
            }
            .cardList()
            .navigationTitle("규정 한 줄")
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
                ContentUnavailableView("아직 쌓인 기록이 없어요", systemImage: "tray")
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
                        Text("손님이 남은 기록을 없애 달라고 하셨나요? 그 예약을 왼쪽으로 쓸어 넘기면 한 번에 사라져요. 다른 공방에는 이 기록이 보이지 않아요.")
                    }
                }
                .cardList()
            }
        }
        .navigationTitle("취소·노쇼 기록")
        .navigationBarTitleDisplayMode(.inline)
        .task(id: app.dataVersion) { await load() }
        .confirmationDialog("여기 남은 이 예약 기록을 전부 지울까요?", isPresented: Binding(
            get: { removing != nil }, set: { if !$0 { removing = nil } }), titleVisibility: .visible) {
            Button("기록 지우기", role: .destructive) {
                guard let id = removing?.bookingId else { return }
                Task { await app.run(id: "k06.remove") { try await RoundupAPI.k06RemoveCases(bookingID: id) } }
            }
        }
    }

    private func load() async { await loader.load { try await RoundupAPI.k06Cases() } }
}
