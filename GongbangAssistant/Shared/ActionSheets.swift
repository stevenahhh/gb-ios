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
                        Button(action: save) {
                            BusyLabel(title: saveLabel, isBusy: isSaving)
                        }
                        .disabled(isSaving || !canSave)
                        .accessibilityIdentifier("form.save")
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
    static let carriers = ["CJ대한통운", "우체국택배", "한진택배", "롯데택배", "로젠택배"]
    private static let customCarrier = "직접 입력"

    let item: WorkItem
    @AppStorage("invoice.lastCarrier") private var lastCarrier = "CJ대한통운"
    @State private var choice = ""
    @State private var customName = ""
    @State private var digits = ""
    @Environment(AppModel.self) private var app
    @Environment(\.dismiss) private var dismiss

    private var carrier: String {
        choice == Self.customCarrier ? customName.trimmingCharacters(in: .whitespaces) : choice
    }

    private var isNumberValid: Bool { (10...14).contains(digits.count) }

    /// Shows the number in groups of four while storing digits only, so pasted dashes and spaces vanish.
    private var grouped: Binding<String> {
        Binding(
            get: { stride(from: 0, to: digits.count, by: 4).map { start -> String in
                let lower = digits.index(digits.startIndex, offsetBy: start)
                let upper = digits.index(lower, offsetBy: min(4, digits.count - start))
                return String(digits[lower..<upper])
            }.joined(separator: " ") },
            set: { digits = String($0.filter(\.isNumber).prefix(14)) }
        )
    }

    var body: some View {
        FormSheet(
            title: "송장 등록", saveLabel: "등록", canSave: isFilled(carrier) && isNumberValid,
            isSaving: app.isRunning(item.id), save: save
        ) {
            Section {
                Picker("택배사", selection: $choice) {
                    ForEach(Self.carriers + [Self.customCarrier], id: \.self) { Text($0).tag($0) }
                }
                .accessibilityIdentifier("invoice.carrier")
                if choice == Self.customCarrier {
                    TextField("택배사 이름", text: $customName)
                        .accessibilityIdentifier("invoice.carrier.custom")
                }
                LabeledContent("운송장 번호") {
                    TextField("숫자 10~14자리", text: grouped)
                        .keyboardType(.numberPad)
                        .multilineTextAlignment(.trailing)
                        .monospacedDigit()
                        .accessibilityIdentifier("invoice.number")
                }
            } header: {
                Text(item.title)
            } footer: {
                if !digits.isEmpty && !isNumberValid {
                    Text("운송장 번호는 숫자 10~14자리예요.")
                }
            }
        }
        .presentationDetents([.medium])
        .onAppear {
            if choice.isEmpty { choice = Self.carriers.contains(lastCarrier) ? lastCarrier : Self.customCarrier }
            if choice == Self.customCarrier, customName.isEmpty, !Self.carriers.contains(lastCarrier) { customName = lastCarrier }
        }
    }

    private func save() {
        let (item, carrier, number) = (item, carrier, digits)
        Task {
            if await app.run(id: item.id, {
                try await RoundupAPI.registerInvoice(item: item, carrier: carrier, trackingNumber: number)
            }) {
                lastCarrier = carrier
                dismiss()
            }
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
                // The spinner sits where the picker will be, so the form does not jump when the classes arrive.
                Section("수업") {
                    LabeledContent("수업") { ProgressView() }
                }
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
