import SwiftUI

/// Shared chrome for short forms that save one thing to the server.
struct FormSheet<Fields: View>: View {
    let title: String
    let saveLabel: String
    let canSave: Bool
    let isSaving: Bool
    let save: () -> Void
    @ViewBuilder let fields: () -> Fields
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            Form { fields() }
                .navigationTitle(title)
                .navigationBarTitleDisplayMode(.inline)
                .toolbar {
                    ToolbarItem(placement: .cancellationAction) {
                        Button("취소") { dismiss() }
                    }
                    ToolbarItem(placement: .confirmationAction) {
                        if isSaving {
                            ProgressView()
                        } else {
                            Button(saveLabel, action: save)
                                .disabled(!canSave)
                                .accessibilityIdentifier("form.save")
                        }
                    }
                }
        }
        .interactiveDismissDisabled(isSaving)
    }
}

private func isFilled(_ text: String) -> Bool {
    !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
}

struct InvoiceSheet: View {
    let item: WorkItem
    @State private var carrier = "CJ대한통운"
    @State private var trackingNumber = ""
    @Environment(AppModel.self) private var app
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        FormSheet(
            title: "송장 등록", saveLabel: "등록",
            canSave: isFilled(carrier) && trackingNumber.trimmingCharacters(in: .whitespaces).count >= 4,
            isSaving: app.isRunning(item.id), save: save
        ) {
            Section(item.title) {
                TextField("택배사", text: $carrier)
                    .accessibilityIdentifier("invoice.carrier")
                TextField("운송장 번호", text: $trackingNumber)
                    .keyboardType(.numbersAndPunctuation)
                    .accessibilityIdentifier("invoice.number")
            }
        }
    }

    private func save() {
        let (item, carrier, number) = (item, carrier, trackingNumber)
        Task {
            if await app.run(id: item.id, {
                try await RoundupAPI.registerInvoice(item: item, carrier: carrier, trackingNumber: number)
            }) { dismiss() }
        }
    }
}

struct ContentReviewSheet: View {
    let item: WorkItem
    @State private var loader = Loader<ContentDetail>()
    @State private var text = ""
    @Environment(AppModel.self) private var app
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        FormSheet(
            title: "홍보 글 검토", saveLabel: "검토 완료",
            canSave: loader.value != nil && isFilled(text),
            isSaving: app.isRunning(item.id), save: save
        ) {
            if let detail = loader.value {
                Section {
                    TextEditor(text: $text)
                        .frame(minHeight: 200)
                        .accessibilityLabel("홍보 글 본문")
                        .accessibilityIdentifier("content.body")
                } header: {
                    Text(detail.title)
                } footer: {
                    Text("검토 완료해도 자동으로 게시되지 않아요. \(detail.channel)에는 직접 올려 주세요.")
                }
            } else if let message = loader.errorMessage {
                Label(message, systemImage: "exclamationmark.circle")
                Button("다시 시도") { Task { await load() } }
            } else {
                ProgressView("불러오는 중이에요")
            }
        }
        .task { await load() }
    }

    private func load() async {
        let id = item.id
        await loader.load { try await RoundupAPI.contentDraft(id: id) }
        if let body = loader.value?.body, text.isEmpty { text = body }
    }

    private func save() {
        guard let detail = loader.value else { return }
        let body = text
        Task {
            if await app.run(id: item.id, {
                try await RoundupAPI.reviewContent(id: detail.id, body: body, revision: detail.revision)
            }) { dismiss() }
        }
    }
}

struct BookingFormSheet: View {
    @State private var sessions = Loader<[SessionOption]>()
    @State private var sessionID: String?
    @State private var customerName = ""
    @State private var phone = ""
    @State private var partySize = 1
    @Environment(AppModel.self) private var app
    @Environment(\.dismiss) private var dismiss

    private var selected: SessionOption? { sessions.value?.first { $0.id == sessionID } }

    var body: some View {
        FormSheet(
            title: "예약 등록", saveLabel: "등록", canSave: selected != nil && isFilled(customerName),
            isSaving: app.isRunning("booking.create"), save: save
        ) {
            if let options = sessions.value {
                if options.isEmpty {
                    Label("예약을 받을 수 있는 수업이 없어요", systemImage: "calendar")
                } else {
                    Section("수업") {
                        Picker("수업", selection: $sessionID) {
                            Text("선택해 주세요").tag(String?.none)
                            ForEach(options) { option in
                                Text("\(option.title) · \(option.schedule)").tag(Optional(option.id))
                            }
                        }
                        .accessibilityIdentifier("booking.session")
                        if let selected {
                            LabeledContent("남은 자리", value: "\(selected.remainingSeats)자리")
                            LabeledContent("예약금", value: selected.deposit)
                        }
                    }
                    Section("예약자") {
                        TextField("이름", text: $customerName)
                            .textContentType(.name)
                            .accessibilityIdentifier("booking.name")
                        TextField("연락처 (선택)", text: $phone)
                            .keyboardType(.phonePad)
                        Stepper("인원 \(partySize)명", value: $partySize, in: 1...max(selected?.remainingSeats ?? 1, 1))
                    }
                }
            } else if let message = sessions.errorMessage {
                Label(message, systemImage: "exclamationmark.circle")
                Button("다시 시도") { Task { await load() } }
            } else {
                ProgressView("불러오는 중이에요")
            }
        }
        .task { await load() }
        .onChange(of: sessionID) { partySize = 1 }
    }

    private func load() async {
        await sessions.load { try await RoundupAPI.classSessions() }
    }

    private func save() {
        guard let sessionID else { return }
        let (name, phone, size) = (customerName, phone, partySize)
        Task {
            if await app.run(id: "booking.create", {
                try await RoundupAPI.createBooking(sessionID: sessionID, customerName: name, phone: phone, partySize: size)
            }) { dismiss() }
        }
    }
}

struct EventFormSheet: View {
    @State private var title = ""
    @State private var detail = ""
    @State private var kind = EventKind.todo
    @State private var startsAt: Date
    @Environment(AppModel.self) private var app
    @Environment(\.dismiss) private var dismiss

    init(day: Date) {
        let calendar = Calendar.workshop
        _startsAt = State(initialValue: calendar.date(bySettingHour: 10, minute: 0, second: 0, of: day) ?? day)
    }

    var body: some View {
        FormSheet(
            title: "일정 추가", saveLabel: "추가", canSave: isFilled(title),
            isSaving: app.isRunning("event.create"), save: save
        ) {
            Section {
                TextField("제목", text: $title)
                    .accessibilityIdentifier("event.title")
                Picker("종류", selection: $kind) {
                    ForEach(EventKind.allCases) { Text($0.label).tag($0) }
                }
                DatePicker("시작", selection: $startsAt)
                    .environment(\.timeZone, Calendar.workshop.timeZone)
                TextField("메모 (선택)", text: $detail, axis: .vertical)
            }
        }
    }

    private func save() {
        let (title, kind, detail, startsAt) = (title, kind, detail, startsAt)
        Task {
            if await app.run(id: "event.create", {
                try await RoundupAPI.createEvent(title: title, kind: kind, detail: detail, startsAt: startsAt)
            }) { dismiss() }
        }
    }
}
