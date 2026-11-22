import RoundupCore
import SwiftUI

/// 수업 사실 카드: every class of the calendar with how much of its facts the owner has filled in.
struct BK25FactCardListView: View {
    @State private var loader = Loader<[BK25FactCardSummary]>()
    @SceneStorage("root.tab") private var tab: AppTab = .today
    @Environment(AppModel.self) private var app

    var body: some View {
        LoadableContent(loader: loader, retry: load) { cards in
            if cards.isEmpty {
                ContentUnavailableView {
                    Label("캘린더에 수업을 먼저 넣어 주세요", systemImage: "calendar")
                } description: {
                    Text(verbatim: "수업이 생기면 여기에서 손님 답장에 쓸 사실을 채울 수 있어요.")
                        .foregroundStyle(Color.secondaryText)
                } actions: {
                    Button("캘린더로 가기") { tab = .calendar }
                        .buttonStyle(.borderedProminent)
                        .controlSize(.large)
                }
                .accessibilityIdentifier("bk25.cards.empty")
            } else {
                list(cards)
            }
        }
        .navigationTitle("수업 사실 카드")
        .navigationBarTitleDisplayMode(.inline)
        .task(id: app.dataVersion) { await load() }
    }

    private func load() async {
        await loader.load { try await BK25API.factCards() }
    }

    private func list(_ cards: [BK25FactCardSummary]) -> some View {
        List {
            CardSection {
                ForEach(cards) { card in
                    NavigationLink {
                        BK25FactCardView(summary: card)
                    } label: {
                        row(card)
                    }
                    .accessibilityIdentifier("bk25.card.\(card.className)")
                }
            } header: {
                EmptyView()
            } footer: {
                Text("비서는 여기에 적힌 사실과 예약 장부만 보고 답장을 써요. 답장 초안이 확인해 보겠다고만 쓰는 일을 줄여요.")
            }
        }
        .cardList()
        .refreshable { await load() }
    }

    private func row(_ card: BK25FactCardSummary) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack(alignment: .firstTextBaseline, spacing: 8) {
                Text(verbatim: card.className)
                    .font(.headline)
                Spacer(minLength: 8)
                StatusBadge(status(of: card), isPlain: true)
            }
            PhraseText(text: "5칸 중 \(card.filledCount)칸 · 내 규칙 \(card.ruleCount)개")
                .font(.subheadline)
                .foregroundStyle(Color.secondaryText)
        }
        .padding(.vertical, 4)
    }

    private func status(of card: BK25FactCardSummary) -> Status {
        if card.filledCount == 0 { return Status(text: "아직 없음", tone: .neutral) }
        return card.filledCount < BK25FactField.allCases.count
            ? Status(text: "빈 칸 있음", tone: .attention) : Status(text: "모두 채움", tone: .done)
    }
}

/// One class's facts, its interview, and the owner's own rules for it.
struct BK25FactCardView: View {
    let summary: BK25FactCardSummary
    @State private var loader = Loader<BK25FactCard>()
    @Environment(AppModel.self) private var app

    var body: some View {
        LoadableContent(loader: loader, retry: load) { card in
            BK25FactCardEditor(card: card, reload: load)
                .id(card.revision)
        }
        .navigationTitle(summary.className)
        .navigationBarTitleDisplayMode(.inline)
        .task(id: app.dataVersion) { await load() }
    }

    private func load() async {
        await loader.load { try await BK25API.factCard(summary.id) }
    }
}

/// The owner's working copy of a card's facts.
struct BK25CardForm: Equatable {
    var durationMinutes: Int?
    var capacity: Int?
    var includedMaterials: String
    var parking: String
    var refundPolicy: String
    var priceWon: Int?

    init(_ card: BK25FactCard) {
        durationMinutes = card.durationMinutes
        capacity = card.capacity
        includedMaterials = card.includedMaterials ?? ""
        parking = card.parking ?? ""
        refundPolicy = card.refundPolicy ?? ""
        priceWon = card.priceWon
    }

    func text(of field: BK25FactField) -> String {
        switch field {
        case .durationMinutes: durationMinutes.map { "\($0)분" } ?? ""
        case .capacity: capacity.map { "\($0)명" } ?? ""
        case .includedMaterials: includedMaterials
        case .parking: parking
        case .refundPolicy: refundPolicy
        }
    }

    mutating func set(_ field: BK25FactField, to value: String) {
        switch field {
        case .durationMinutes: durationMinutes = Int(value)
        case .capacity: capacity = Int(value)
        case .includedMaterials: includedMaterials = value
        case .parking: parking = value
        case .refundPolicy: refundPolicy = value
        }
    }

    var emptyFields: [BK25FactField] {
        BK25FactField.allCases.filter { text(of: $0).isEmpty }
    }

    func update(for card: BK25FactCard) -> BK25FactCardUpdate {
        BK25FactCardUpdate(className: card.className, expectedRevision: card.revision,
                           durationMinutes: durationMinutes, capacity: capacity,
                           includedMaterials: includedMaterials.isEmpty ? nil : includedMaterials,
                           parking: parking.isEmpty ? nil : parking,
                           refundPolicy: refundPolicy.isEmpty ? nil : refundPolicy, priceWon: priceWon)
    }
}

struct BK25FactCardEditor: View {
    let card: BK25FactCard
    let reload: () async -> Void
    @State private var form: BK25CardForm
    @State private var freshFields: Set<BK25FactField> = []
    @State private var editing: BK25FactField?
    @State private var isEditingPrice = false
    @State private var isInterviewing = false
    @State private var isSaving = false
    @State private var priceText = ""
    @Environment(AppModel.self) private var app

    init(card: BK25FactCard, reload: @escaping () async -> Void) {
        self.card = card
        self.reload = reload
        _form = State(initialValue: BK25CardForm(card))
    }

    private var isDirty: Bool { form != BK25CardForm(card) }

    var body: some View {
        List {
            CardSection {
                ForEach(BK25FactField.allCases) { field in
                    Button {
                        editing = field
                    } label: {
                        factRow(field.title, value: form.text(of: field), isFresh: freshness(of: field))
                    }
                    .buttonStyle(.plain)
                    .accessibilityIdentifier("bk25.fact.\(field.rawValue)")
                }
                Button {
                    priceText = form.priceWon.map(String.init) ?? ""
                    isEditingPrice = true
                } label: {
                    factRow("가격", value: form.priceWon.map { "\($0.formatted())원" } ?? "", isFresh: .constant(false))
                }
                .buttonStyle(.plain)
                .accessibilityIdentifier("bk25.fact.priceWon")
            } header: {
                Text("답장에 쓰는 사실")
            } footer: {
                Text("비어 있는 칸은 답장에 쓰지 않아요. 비어 있으면 손님이 물을 때 판단 필요로 알려 드려요.")
            }

            if form.emptyFields.isEmpty {
                saveSection
            } else {
                CardSection {
                    Button {
                        isInterviewing = true
                    } label: {
                        Text(card.revision == 0 && !isDirty ? "인터뷰로 채우기" : "빈 칸 인터뷰로 채우기")
                            .frame(maxWidth: .infinity, minHeight: 30)
                    }
                    .buttonStyle(.bordered)
                    .controlSize(.large)
                    .accessibilityIdentifier("bk25.interview.start")
                }
                if isDirty { saveSection }
            }

            CardSection {
                if card.rules.isEmpty {
                    Text("아직 규칙이 없어요. 판단 필요에 답하면 여기에 쌓여요.")
                        .foregroundStyle(Color.secondaryText)
                } else {
                    ForEach(card.rules) { rule in
                        VStack(alignment: .leading, spacing: 4) {
                            Text(verbatim: rule.ruleText)
                            Text(rule.className.map { "\($0)에 쓰는 규칙" } ?? "공방 전체에 쓰는 규칙")
                                .font(.subheadline)
                                .foregroundStyle(Color.secondaryText)
                        }
                        .padding(.vertical, 2)
                        .accessibilityIdentifier("bk25.rule.\(rule.id)")
                        .swipeActions(edge: .trailing, allowsFullSwipe: true) {
                            Button("지우기", role: .destructive) { retire(rule) }
                        }
                    }
                }
            } header: {
                Text("내 규칙")
            } footer: {
                Text("판단 필요에 답하면서 만든 규칙이에요. 옆으로 밀면 지워져요.")
            }
        }
        .cardList()
        .sheet(item: $editing) { field in
            BK25FieldSheet(field: field, cardID: card.id, current: form.text(of: field)) { value in
                freshFields.remove(field)
                form.set(field, to: value)
            }
        }
        .sheet(isPresented: $isEditingPrice) { priceSheet }
        .fullScreenCover(isPresented: $isInterviewing) {
            BK25InterviewView(cardID: card.id, className: card.className,
                              fields: form.emptyFields) { values in
                for (field, value) in values {
                    form.set(field, to: value)
                    freshFields.insert(field)
                }
            }
        }
    }

    private var saveSection: some View {
        CardSection {
            Button {
                Task { await save() }
            } label: {
                BusyLabel(title: "저장", isBusy: isSaving, isProminent: true)
                    .frame(maxWidth: .infinity, minHeight: 30)
            }
            .buttonStyle(.borderedProminent)
            .controlSize(.large)
            .disabled(isSaving || !isDirty)
            .accessibilityIdentifier("bk25.card.save")
        }
    }

    private func freshness(of field: BK25FactField) -> Binding<Bool> {
        Binding(get: { freshFields.contains(field) }, set: { if !$0 { freshFields.remove(field) } })
    }

    private func factRow(_ title: String, value: String, isFresh: Binding<Bool>) -> some View {
        HStack(alignment: .firstTextBaseline) {
            VStack(alignment: .leading, spacing: 4) {
                Text(title)
                    .font(.subheadline)
                    .foregroundStyle(Color.secondaryText)
                if value.isEmpty {
                    Text("아직 없음")
                        .foregroundStyle(Color.secondaryText)
                } else if isFresh.wrappedValue {
                    GeneratedText(AttributedString(value), isFresh: isFresh)
                } else {
                    Text(verbatim: value)
                }
            }
            Spacer(minLength: 8)
            Image(systemName: "chevron.forward")
                .font(.footnote.weight(.semibold))
                .foregroundStyle(.tertiary)
                .accessibilityHidden(true)
        }
        .contentShape(.rect)
        .padding(.vertical, 2)
    }

    private var priceSheet: some View {
        NavigationStack {
            List {
                CardSection("한 사람 가격", footer: "숫자만 적으면 돼요. 초안의 가격을 이 값과 맞춰 봐요.") {
                    TextField("예: 38000", text: $priceText)
                        .keyboardType(.numberPad)
                        .accessibilityIdentifier("bk25.price.field")
                }
            }
            .cardList()
            .navigationTitle("가격")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("취소") { isEditingPrice = false } }
                ToolbarItem(placement: .confirmationAction) {
                    Button("확인") {
                        form.priceWon = Int(priceText.filter(\.isNumber)).flatMap { $0 > 0 ? $0 : nil }
                        isEditingPrice = false
                    }
                    .accessibilityIdentifier("bk25.price.confirm")
                }
            }
        }
        .presentationDetents([.medium])
    }

    private func save() async {
        isSaving = true
        defer { isSaving = false }
        do {
            _ = try await BK25API.saveFactCard(card.id, form.update(for: card))
            freshFields = []
            app.showToast("수업 사실 카드를 저장했어요")
            await reload()
        } catch {
            // The preview stays as it is, so nothing the owner said is lost.
            app.showToast(error.localizedDescription)
        }
    }

    private func retire(_ rule: BK25Rule) {
        Task {
            do {
                _ = try await BK25API.retireRule(rule.id)
                app.showToast("규칙을 지웠어요")
                await reload()
            } catch {
                app.showToast(error.localizedDescription)
            }
        }
    }
}

/// Edits one fact with the same words the interview uses.
struct BK25FieldSheet: View {
    let field: BK25FactField
    let cardID: String
    let current: String
    let onValue: (String) -> Void
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            List {
                CardSection(field.question) {
                    BK25FieldInput(field: field, cardID: cardID, submitTitle: "확인") { value in
                        onValue(value)
                        dismiss()
                    }
                }
                if !current.isEmpty {
                    CardSection("지금 값") {
                        Text(verbatim: current)
                    }
                }
            }
            .cardList()
            .navigationTitle(field.title)
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("닫기") { dismiss() } }
            }
        }
        .presentationDetents([.medium, .large])
    }
}

/// One spoken or typed answer, tidied by the server into a card value. An unclear answer keeps what the owner said.
struct BK25FieldInput: View {
    let field: BK25FactField
    let cardID: String
    let submitTitle: String
    let onValue: (String) -> Void
    @State private var text = ""
    @State private var isWorking = false
    @State private var message: String?

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            BK25VoiceField(text: $text, prompt: field.hint)
            if isWorking {
                GeneratingIndicator(label: "답을 칸에 맞게 정리하는 중이에요")
            }
            if let message {
                Label(message, systemImage: "exclamationmark.circle")
                    .font(.subheadline)
                    .accessibilityIdentifier("bk25.interview.message")
            }
            Button {
                Task { await submit() }
            } label: {
                Text(submitTitle)
                    .font(.subheadline.weight(.semibold))
                    .frame(maxWidth: .infinity, minHeight: 30)
            }
            .buttonStyle(.borderedProminent)
            .controlSize(.large)
            .disabled(isWorking || text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
            .accessibilityIdentifier("bk25.field.submit")
        }
        .padding(.vertical, 4)
    }

    private func submit() async {
        message = nil
        isWorking = true
        defer { isWorking = false }
        do {
            let read = try await BK25API.interview(cardID, field: field, answer: text)
            guard read.confidence == .clear, !read.value.isEmpty else {
                message = "다시 말하거나 글로 써 주세요"
                return
            }
            text = ""
            onValue(read.value)
        } catch {
            message = error.localizedDescription
        }
    }
}

/// The five questions in order. A skipped question stays empty, and a real customer question fills it later.
struct BK25InterviewView: View {
    let cardID: String
    let className: String
    let fields: [BK25FactField]
    let finish: ([BK25FactField: String]) -> Void
    @State private var index = 0
    @State private var values: [BK25FactField: String] = [:]
    @Environment(\.dismiss) private var dismiss

    private var field: BK25FactField? { fields.indices.contains(index) ? fields[index] : nil }

    var body: some View {
        NavigationStack {
            List {
                if let field {
                    CardSection {
                        VStack(alignment: .leading, spacing: 8) {
                            HStack(spacing: 8) {
                                ProgressView(value: Double(index + 1), total: Double(fields.count))
                                Text("\(index + 1)/\(fields.count)")
                                    .font(.subheadline.monospacedDigit())
                                    .foregroundStyle(Color.secondaryText)
                            }
                            Text(field.question)
                                .font(.title3.bold())
                        }
                        .padding(.vertical, 4)
                    }
                    CardSection {
                        BK25FieldInput(field: field, cardID: cardID, submitTitle: "다음") { value in
                            values[field] = value
                            advance()
                        }
                        .id(field)
                        Button("건너뛰기", action: advance)
                            .buttonStyle(.bordered)
                            .controlSize(.large)
                            .accessibilityIdentifier("bk25.interview.skip")
                    } header: {
                        EmptyView()
                    } footer: {
                        Text("건너뛴 칸은 손님이 물을 때 판단 필요로 다시 물어봐요.")
                    }
                }
            }
            .cardList()
            .navigationTitle(className)
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("닫기") { dismiss() }
                }
            }
        }
    }

    private func advance() {
        if index + 1 < fields.count {
            index += 1
        } else {
            finish(values)
            dismiss()
        }
    }
}
