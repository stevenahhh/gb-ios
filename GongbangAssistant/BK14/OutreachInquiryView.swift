import RoundupCore
import SwiftUI

/// The fields of one inquiry while the owner checks them.
struct OutreachForm {
    var fields = OutreachFields()
    var headcount: Int?
    var signals: [OutreachSignal] = []
    var classID: String?
    var assistants = 0
    var travelMinutes: Int?
    var distanceKm: Int?
    /// Names of the fields still holding the assistant's reading.
    var read: Set<String> = []
    /// Names of the fields whose value was read without confidence.
    var unsure: Set<String> = []

    init() {}

    init(_ extraction: OutreachExtraction) {
        let source = extraction.fields
        fields = OutreachFields(
            orgType: source.orgType, orgName: source.orgName, budgetKrw: source.budgetKrw,
            budgetVat: source.budgetVat, date: source.date, dateText: source.dateText, timeRange: source.timeRange,
            locationText: source.locationText, classHint: source.classHint, contactKind: source.contactKind)
        headcount = source.headcount
        signals = extraction.signals
        read = Set(extraction.confidence.filter { $0.value == .high }.keys)
        unsure = Set(extraction.confidence.filter { $0.value == .low }.keys)
    }

    /// What the owner confirmed as the total travel time one way.
    var canQuote: Bool { classID != nil && (headcount ?? 0) > 0 }
}

struct OutreachInquiryView: View {
    let onCreated: (OutreachOpened) -> Void
    @State private var text = ""
    @State private var form: OutreachForm?
    @State private var isReading = false
    @State private var readFailed = false
    @State private var isVerified = false
    @State private var isCreating = false
    @State private var errorMessage: String?
    @State private var classes: [OutreachClassCost] = []
    @State private var startedAt = Date.now
    @Environment(InquiryStore.self) private var store
    @Environment(AppModel.self) private var app
    @Environment(\.dismiss) private var dismiss

    private var isBlank: Bool { text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty }

    var body: some View {
        NavigationStack {
            List {
                inquirySection
                if isReading {
                    CardSection { GeneratingIndicator(label: "비서가 문의를 읽고 있어요") }
                }
                if form != nil { formSections }
            }
            .cardList()
            .scrollDismissesKeyboard(.interactively)
            .navigationTitle("새 견적")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("닫기") { dismiss() }
                }
            }
        }
        .interactiveDismissDisabled(!isBlank)
        .task { await loadClasses() }
    }

    private var inquirySection: some View {
        CardSection {
            KoreanTextEditor(text: $text)
                .frame(minHeight: 120)
                .accessibilityLabel("받은 문의")
                .accessibilityIdentifier("outreach.text")
            HStack {
                // The system paste control reads the clipboard only when tapped.
                PasteButton(payloadType: String.self) { strings in
                    if let pasted = strings.first { text = String(pasted.prefix(2000)) }
                }
                .buttonBorderShape(.capsule)
                Spacer()
                if !store.inquiries.isEmpty {
                    Menu("앱에 온 문의") {
                        ForEach(store.inquiries) { inquiry in
                            Button(inquiry.subject) { text = String(inquiry.question.prefix(2000)) }
                        }
                    }
                    .menuStyle(.button)
                    .buttonStyle(.bordered)
                    .accessibilityIdentifier("outreach.existing")
                }
            }
            if form == nil {
                readButton.buttonStyle(.borderedProminent)
                Button("비서 없이 직접 입력") { form = OutreachForm() }
                    .buttonStyle(.bordered)
                    .accessibilityIdentifier("outreach.manual")
            } else {
                readButton.buttonStyle(.bordered)
            }
        } header: {
            Text("받은 문의")
        } footer: {
            Text("문의 원문은 저장하지 않고 전화번호와 이메일은 가린 뒤에 읽어요.")
        }
    }

    private var readButton: some View {
        Button {
            read()
        } label: {
            BusyLabel(title: form == nil ? "문의 읽기" : "다시 읽기", isBusy: isReading, isProminent: form == nil)
                .frame(maxWidth: .infinity)
        }
        .controlSize(.large)
        .disabled(isBlank || isReading)
        .accessibilityIdentifier("outreach.read")
    }

    // MARK: Checked fields

    @ViewBuilder
    private var formSections: some View {
        if readFailed {
            CardSection {
                Label {
                    Text("문의를 읽지 못했습니다. 직접 입력해 주세요.")
                } icon: {
                    Image(systemName: "exclamationmark.circle")
                }
                .accessibilityIdentifier("outreach.readFailed")
            }
        }
        if let form, !form.signals.isEmpty {
            OutreachWarningCard(signals: form.signals, isVerified: isVerified, isBusy: false) { isVerified = true }
        }
        if let binding = Binding($form) {
            OutreachFieldsSection(form: binding)
            OutreachClassSection(form: binding, classes: classes)
        }
        CardSection {
            if let errorMessage {
                Label(errorMessage, systemImage: "exclamationmark.circle")
            }
            Button(action: create) {
                BusyLabel(title: "견적 계산하기", isBusy: isCreating, isProminent: true)
                    .frame(maxWidth: .infinity)
            }
            .buttonStyle(.borderedProminent)
            .controlSize(.large)
            .disabled(form?.canQuote != true || isCreating)
            .accessibilityIdentifier("outreach.create")
        } header: {
            EmptyView()
        } footer: {
            Text("인원과 수업을 정하면 계산해요.")
        }
    }

    // MARK: Work

    private func loadClasses() async {
        classes = (try? await RoundupAPI.outreachCosts())?.classes ?? []
    }

    private func read() {
        let source = String(text.prefix(2000))
        // The keyboard would cover the warning card that arrives below the text.
        UIApplication.shared.sendAction(#selector(UIResponder.resignFirstResponder), to: nil, from: nil, for: nil)
        Task {
            isReading = true
            defer { isReading = false }
            isVerified = false
            do {
                let extraction = try await RoundupAPI.extractOutreach(text: source)
                var next = OutreachForm(extraction)
                next.classID = match(extraction.fields.classHint)
                form = next
                readFailed = extraction.error != nil
            } catch {
                form = OutreachForm()
                readFailed = true
            }
            if classes.isEmpty { await loadClasses() }
        }
    }

    /// Picks a class only when the inquiry's own words name exactly one.
    private func match(_ hint: String?) -> String? {
        guard let hint, !hint.isEmpty else { return nil }
        let found = classes.filter { $0.title.contains(hint) || hint.contains($0.title) }
        return found.count == 1 ? found.first?.classId : nil
    }

    private func create() {
        guard let form, let classID = form.classID, let headcount = form.headcount else { return }
        let request = OutreachQuoteRequest(
            fields: form.fields, classId: classID, headcount: headcount, assistants: form.assistants,
            travelMinutes: form.travelMinutes, distanceKm: form.distanceKm, signals: form.signals)
        Task {
            isCreating = true
            defer { isCreating = false }
            do {
                let quote = try await RoundupAPI.createOutreachQuote(request)
                // A failed confirmation leaves the quote locked; its own screen offers the button again.
                if isVerified && quote.locked { try? await RoundupAPI.verifyOutreachOrg(id: quote.id) }
                app.dataDidChange()
                dismiss()
                onCreated(OutreachOpened(id: quote.id, startedAt: startedAt))
            } catch {
                errorMessage = error.localizedDescription
            }
        }
    }
}

/// K15: risk wording found in the inquiry. It never says the inquiry is a scam.
struct OutreachWarningCard: View {
    let signals: [OutreachSignal]
    let isVerified: Bool
    let isBusy: Bool
    let verify: () -> Void

    var body: some View {
        CardSection {
            Label {
                Text("확인하고 진행하세요").font(.headline)
            } icon: {
                Image(systemName: "exclamationmark.shield").foregroundStyle(.primary)
            }
            .accessibilityIdentifier("outreach.warning")
            ForEach(signals, id: \.self) { signal in
                Text(verbatim: signal.text)
            }
            if isVerified {
                Label("기관 대표번호로 확인했어요", systemImage: "checkmark.circle")
                    .foregroundStyle(Color.secondaryText)
            } else {
                Button(action: verify) {
                    BusyLabel(title: "기관 대표번호로 확인함", isBusy: isBusy)
                        .frame(maxWidth: .infinity)
                }
                .buttonStyle(.bordered)
                .controlSize(.large)
                .disabled(isBusy)
                .accessibilityIdentifier("outreach.verify")
            }
        }
    }
}

/// A field that says whether the assistant read it or the owner still has to check it.
private struct FieldNote: View {
    let isRead: Bool
    let needsCheck: Bool

    var body: some View {
        if isRead {
            Text("\(AssistantIdentity.name)가 읽은 값")
                .font(.subheadline)
                .foregroundStyle(Color.secondaryText)
        } else if needsCheck {
            Text("확인 필요")
                .font(.subheadline)
                .foregroundStyle(Color.secondaryText)
        }
    }
}

struct OutreachFieldsSection: View {
    @Binding var form: OutreachForm

    var body: some View {
        CardSection("문의에서 읽은 내용") {
            row("orgType", isEmpty: form.fields.orgType == .unknown) {
                Picker("기관 유형", selection: edited(\.fields.orgType, "orgType")) {
                    ForEach(OutreachOrgType.allCases) { Text($0.label).tag($0) }
                }
            }
            row("orgName", isEmpty: form.fields.orgName == nil) {
                textField("기관 이름", edited(\.fields.orgName, "orgName"))
            }
            row("headcount", isEmpty: form.headcount == nil) {
                OutreachNumberField(title: "인원", value: edited(\.headcount, "headcount"), unit: "명", identifier: "outreach.headcount")
            }
            row("budgetKrw", isEmpty: form.fields.budgetKrw == nil) {
                OutreachNumberField(title: "예산", value: edited(\.fields.budgetKrw, "budgetKrw"), unit: "원", identifier: "outreach.budget")
            }
            row("budgetVat", isEmpty: form.fields.budgetVat == .unknown) {
                Picker("부가세", selection: edited(\.fields.budgetVat, "budgetVat")) {
                    ForEach(OutreachVat.allCases) { Text($0.label).tag($0) }
                }
            }
            row("date", isEmpty: form.fields.date == nil) { dateField }
            row("timeRange", isEmpty: form.fields.timeRange == nil) { timeField }
            row("locationText", isEmpty: form.fields.locationText == nil) {
                textField("장소", edited(\.fields.locationText, "locationText"))
            }
            row("contactKind", isEmpty: form.fields.contactKind == .unknown) {
                OutreachValueRow(title: "담당자 연락 방식", value: form.fields.contactKind.label)
            }
        }
    }

    private func row<Content: View>(_ name: String, isEmpty: Bool, @ViewBuilder content: () -> Content) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            content()
            FieldNote(isRead: form.read.contains(name), needsCheck: isEmpty || form.unsure.contains(name))
        }
    }

    /// Editing a value takes the assistant's mark off it.
    private func edited<Value>(_ path: WritableKeyPath<OutreachForm, Value>, _ name: String) -> Binding<Value> {
        Binding {
            form[keyPath: path]
        } set: {
            form[keyPath: path] = $0
            form.read.remove(name)
            form.unsure.remove(name)
        }
    }

    private func textField(_ title: String, _ value: Binding<String?>) -> some View {
        LabeledContent(title) {
            TextField("입력", text: Binding {
                value.wrappedValue ?? ""
            } set: {
                value.wrappedValue = $0.isEmpty ? nil : $0
            })
            .multilineTextAlignment(.trailing)
            .accessibilityLabel(title)
        }
    }

    @ViewBuilder
    private var dateField: some View {
        let day = edited(\.fields.date, "date")
        if let value = day.wrappedValue, let moment = OutreachFormat.moment(day: value) {
            DatePicker("희망 날짜", selection: Binding { moment } set: { day.wrappedValue = $0.dayKey },
                       displayedComponents: .date)
                .environment(\.timeZone, Calendar.workshop.timeZone)
        } else {
            LabeledContent("희망 날짜") {
                Button(form.fields.dateText ?? "날짜 고르기") { day.wrappedValue = Date.now.dayKey }
                    .buttonStyle(.bordered)
                    .accessibilityIdentifier("outreach.pickDate")
            }
        }
    }

    @ViewBuilder
    private var timeField: some View {
        let range = edited(\.fields.timeRange, "timeRange")
        if let value = range.wrappedValue {
            let parts = value.split(separator: "-").map(String.init)
            if parts.count == 2 {
                clockPicker("시작", parts[0]) { range.wrappedValue = "\($0)-\(parts[1])" }
                clockPicker("끝", parts[1]) { range.wrappedValue = "\(parts[0])-\($0)" }
            }
        } else {
            LabeledContent("시간") {
                Button("시간 고르기") { range.wrappedValue = "14:00-16:00" }
                    .buttonStyle(.bordered)
            }
        }
    }

    private func clockPicker(_ title: String, _ clock: String, set: @escaping (String) -> Void) -> some View {
        DatePicker(title, selection: Binding {
            OutreachFormat.moment(day: "2026-01-01", clock: clock) ?? .now
        } set: {
            set($0.formatted(OutreachFormat.clock))
        }, displayedComponents: .hourAndMinute)
        .environment(\.timeZone, Calendar.workshop.timeZone)
    }
}

struct OutreachClassSection: View {
    @Binding var form: OutreachForm
    let classes: [OutreachClassCost]

    var body: some View {
        CardSection {
            Picker("수업", selection: $form.classID) {
                Text("고르기").tag(String?.none)
                ForEach(classes) { Text(verbatim: $0.title).tag(Optional($0.classId)) }
            }
            .accessibilityIdentifier("outreach.class")
            if let chosen = classes.first(where: { $0.classId == form.classID }), chosen.isMissing {
                NavigationLink {
                    ClassCostEditView(item: chosen)
                } label: {
                    Label { Text("원가를 먼저 입력해 주세요") } icon: { MenuIcon(systemName: "square.and.pencil") }
                }
            }
            Stepper("보조 강사 \(form.assistants)명", value: $form.assistants, in: 0...20)
            OutreachNumberField(title: "편도 이동 시간", value: $form.travelMinutes, unit: "분", identifier: "outreach.travel")
            OutreachNumberField(title: "편도 거리", value: $form.distanceKm, unit: "km", identifier: "outreach.distance")
        } header: {
            Text("수업과 이동")
        } footer: {
            Text("이동 시간은 직접 입력해 주세요. 비워 두면 0분으로 계산하고 확인 필요로 표시해요.")
        }
    }
}
