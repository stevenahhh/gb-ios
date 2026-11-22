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
                    Label("수업부터 하나 캘린더에 넣어 주세요", systemImage: "calendar")
                } description: {
                    Text(verbatim: "수업을 만들고 나면 손님 답장에 들어갈 정보를 여기서 채울 수 있어요.")
                        .foregroundStyle(Color.secondaryText)
                } actions: {
                    Button("캘린더 열기") { tab = .calendar }
                        .buttonStyle(.borderedProminent)
                        .controlSize(.large)
                }
                .accessibilityIdentifier("bk25.cards.empty")
            } else {
                list(cards)
            }
        }
        .navigationTitle("수업 정보")
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
                Text("예약 장부와 아래 칸에 적힌 것만 가지고 답장을 써요. 칸을 채울수록 ‘알아보고 연락드릴게요’ 같은 답이 줄어요.")
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
            PhraseText(text: "\(card.filledCount)/5칸 채움 · 내가 정한 규칙 \(card.ruleCount)개")
                .font(.subheadline)
                .foregroundStyle(Color.secondaryText)
        }
        .padding(.vertical, 4)
    }

    private func status(of card: BK25FactCardSummary) -> Status {
        if card.filledCount == 0 { return Status(text: "하나도 없어요", tone: .neutral) }
        return card.filledCount < BK25FactField.allCases.count
            ? Status(text: "빈칸이 있어요", tone: .attention) : Status(text: "다 채웠어요", tone: .done)
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
                Text("답장에 넣을 수업 정보")
            } footer: {
                Text("비워 둔 칸 내용은 답장에 넣지 않아요. 손님이 그걸 물어보면 그때 사장님께 먼저 여쭤볼게요.")
            }

            if form.emptyFields.isEmpty {
                saveSection
            } else {
                CardSection {
                    Button {
                        isInterviewing = true
                    } label: {
                        Text(card.revision == 0 && !isDirty ? "물어보며 채우기" : "빈 칸만 물어보며 채우기")
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
                    Text("규칙이 하나도 없어요. 손님 질문에 답을 주시면 그 답이 규칙으로 바뀌어 이곳에 쌓여요.")
                        .foregroundStyle(Color.secondaryText)
                } else {
                    ForEach(card.rules) { rule in
                        VStack(alignment: .leading, spacing: 4) {
                            Text(verbatim: rule.ruleText)
                            Text(rule.className.map { "\($0) 전용 규칙" } ?? "모든 수업 공통 규칙")
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
                Text("사장님 답으로 생긴 규칙 모음이에요. 왼쪽으로 쓸면 지울 수 있어요.")
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
                    Text("하나도 없어요")
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
                CardSection("한 분 가격", footer: "금액은 숫자로만 넣으면 돼요. 손님께 갈 초안에 적힌 가격이 이 숫자와 같은지 대조해 드릴게요.") {
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
            app.showToast("수업 정보 저장 완료")
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
                app.showToast("규칙 삭제 완료")
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
                    CardSection("지금 적힌 값") {
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
                GeneratingIndicator(label: "말씀하신 답을 칸마다 나눠 정리하고 있어요")
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
                message = "한 번 더 말씀하시거나 키보드로 적어 보세요"
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
                        Text("건너뛴 칸 내용을 손님이 물어 오면 그때 사장님께 다시 여쭤볼게요.")
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
