import SwiftUI
import Vision
import VisionKit

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

/// A tracking number kept as digits only, so pasted or scanned dashes and spaces vanish.
struct TrackingNumber: Equatable {
    static let lengths = 10...14
    private(set) var digits = ""

    init(_ text: String = "") { digits = String(text.filter(\.isWholeNumber).prefix(Self.lengths.upperBound)) }

    var isEmpty: Bool { digits.isEmpty }
    var isValid: Bool { Self.lengths.contains(digits.count) }

    /// Groups of four, the way labels print them.
    var grouped: String {
        stride(from: 0, to: digits.count, by: 4).map { start in
            let lower = digits.index(digits.startIndex, offsetBy: start)
            return String(digits[lower..<digits.index(lower, offsetBy: min(4, digits.count - start))])
        }.joined(separator: " ")
    }
}

/// Registers tracking numbers for one parcel or a whole packing session: one carrier, one field per parcel,
/// each filled by typing, pasting the copied number, or scanning the label's barcode.
struct InvoiceSheet: View {
    static let carriers = ["CJ대한통운", "우체국택배", "한진택배", "롯데택배", "로젠택배"]
    private static let customCarrier = "직접 입력"

    let items: [WorkItem]
    @AppStorage("invoice.lastCarrier") private var lastCarrier = "CJ대한통운"
    @State private var choice = ""
    @State private var customName = ""
    @State private var numbers: [String: TrackingNumber] = [:]
    @State private var scanning: WorkItem?
    @FocusState private var focused: String?
    @Environment(AppModel.self) private var app
    @Environment(\.dismiss) private var dismiss

    private var carrier: String {
        choice == Self.customCarrier ? customName.trimmingCharacters(in: .whitespaces) : choice
    }

    private var runID: String { items.count == 1 ? items[0].id : "invoice.batch" }
    private var canScan: Bool { DataScannerViewController.isSupported && DataScannerViewController.isAvailable }

    private func number(_ item: WorkItem) -> TrackingNumber { numbers[item.id] ?? TrackingNumber() }

    private func isDuplicate(_ item: WorkItem) -> Bool {
        let own = number(item)
        return !own.isEmpty && items.contains { $0.id != item.id && number($0) == own }
    }

    private var canSave: Bool {
        isFilled(carrier) && items.allSatisfy { number($0).isValid && !isDuplicate($0) }
    }

    var body: some View {
        FormSheet(
            title: items.count == 1 ? "송장 등록" : "송장 \(items.count)건 등록", saveLabel: "등록", canSave: canSave,
            isSaving: app.isRunning(runID), save: save
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
            } footer: {
                Text("마지막에 쓴 택배사를 기억해요.")
            }
            Group {
                ForEach(items) { item in
                    Section {
                        numberRow(item)
                    } header: {
                        Text(item.title)
                    } footer: {
                        footer(item)
                    }
                }
            }
            // The number pad has no return key, so the bar above it moves to the next empty parcel.
            .toolbar {
                ToolbarItemGroup(placement: .keyboard) {
                    Spacer()
                    Button(nextEmpty == nil ? "완료" : "다음") { focused = nextEmpty }
                        .accessibilityIdentifier("invoice.next")
                }
            }
        }
        .presentationDetents(items.count == 1 ? [.medium, .large] : [.large])
        .fullScreenCover(item: $scanning) { item in
            BarcodeScanSheet(title: item.title) { numbers[item.id] = $0 }
        }
        .onAppear {
            if choice.isEmpty { choice = Self.carriers.contains(lastCarrier) ? lastCarrier : Self.customCarrier }
            if choice == Self.customCarrier, customName.isEmpty, !Self.carriers.contains(lastCarrier) { customName = lastCarrier }
            // The keyboard is up at once, so the first parcel needs no tap before typing.
            focused = items.first?.id
        }
    }

    /// The next parcel still waiting for a valid number, after the focused one.
    private var nextEmpty: String? {
        let start = items.firstIndex { $0.id == focused }.map { $0 + 1 } ?? 0
        return (items[start...] + items[..<start]).first { !number($0).isValid && $0.id != focused }?.id
    }

    private func numberRow(_ item: WorkItem) -> some View {
        HStack(spacing: 8) {
            TextField("운송장 번호 10~14자리", text: Binding(
                get: { number(item).grouped },
                set: { numbers[item.id] = TrackingNumber($0) }
            ))
            .keyboardType(.numberPad)
            .textContentType(.shipmentTrackingNumber)
            .monospacedDigit()
            .focused($focused, equals: item.id)
            .accessibilityLabel("\(item.title) 운송장 번호")
            .accessibilityIdentifier("invoice.number.\(item.actionTarget.id)")
            if number(item).isEmpty {
                // The system paste control reads the clipboard only when tapped, so no permission prompt appears.
                PasteButton(payloadType: String.self) { strings in
                    if let text = strings.first { numbers[item.id] = TrackingNumber(text) }
                }
                .labelStyle(.iconOnly)
                .buttonBorderShape(.circle)
                .accessibilityIdentifier("invoice.paste.\(item.actionTarget.id)")
            }
            if canScan {
                Button {
                    scanning = item
                } label: {
                    Image(systemName: "barcode.viewfinder")
                        .font(.title3)
                        .frame(minWidth: 44, minHeight: 44)
                        .contentShape(.rect)
                }
                .buttonStyle(.borderless)
                .accessibilityLabel("\(item.title) 바코드 찍기")
                .accessibilityIdentifier("invoice.scan.\(item.actionTarget.id)")
            }
        }
    }

    @ViewBuilder
    private func footer(_ item: WorkItem) -> some View {
        let entered = number(item)
        if isDuplicate(item) {
            Text("다른 소포와 같은 번호예요.")
        } else if !entered.isEmpty && !entered.isValid {
            Text("운송장 번호는 숫자 10~14자리예요.")
        } else if let line = item.lines.first {
            Text(line)
        }
    }

    private func save() {
        let (items, carrier) = (items, carrier)
        let entries = items.map { (item: $0, trackingNumber: number($0).digits) }
        Task {
            var changed: [WorkItem] = []
            let saved = await app.run(id: runID) {
                if let only = entries.first, entries.count == 1 {
                    changed = [try await RoundupAPI.registerInvoice(
                        item: only.item, carrier: carrier, trackingNumber: only.trackingNumber)]
                } else {
                    changed = try await RoundupAPI.registerInvoices(entries, carrier: carrier)
                }
            }
            guard saved else { return }
            lastCarrier = carrier
            dismiss()
            app.showStepToast(.registerInvoice, title: items[0].title, changed: changed)
        }
    }
}

/// Reads one waybill barcode with the live camera and hands back its digits, then closes itself.
private struct BarcodeScanSheet: View {
    let title: String
    let found: (TrackingNumber) -> Void
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            BarcodeScanner { number in
                found(number)
                dismiss()
            }
            .ignoresSafeArea()
            .safeAreaInset(edge: .bottom) {
                Text("송장의 바코드를 화면 가운데에 맞춰 주세요.")
                    .font(.subheadline)
                    .padding(12)
                    .frame(maxWidth: .infinity)
                    .background(.regularMaterial, in: .card)
                    .padding(16)
            }
            .navigationTitle(title)
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("닫기") { dismiss() }
                }
            }
        }
    }
}

/// VisionKit's live scanner limited to the linear codes Korean waybills print.
private struct BarcodeScanner: UIViewControllerRepresentable {
    let found: (TrackingNumber) -> Void

    func makeUIViewController(context: Context) -> DataScannerViewController {
        let scanner = DataScannerViewController(
            recognizedDataTypes: [.barcode(symbologies: [.code128, .code39, .code93, .itf14, .ean13, .i2of5])],
            qualityLevel: .accurate, recognizesMultipleItems: false, isHighFrameRateTrackingEnabled: false,
            isHighlightingEnabled: true)
        scanner.delegate = context.coordinator
        try? scanner.startScanning()
        return scanner
    }

    func updateUIViewController(_ scanner: DataScannerViewController, context: Context) {
        context.coordinator.found = found
    }

    func makeCoordinator() -> Coordinator { Coordinator(found: found) }

    final class Coordinator: NSObject, DataScannerViewControllerDelegate {
        var found: (TrackingNumber) -> Void
        private var isDone = false

        init(found: @escaping (TrackingNumber) -> Void) { self.found = found }

        func dataScanner(_ scanner: DataScannerViewController, didAdd added: [RecognizedItem], allItems: [RecognizedItem]) {
            for case .barcode(let code) in added {
                let number = TrackingNumber(code.payloadStringValue ?? "")
                guard number.isValid, !isDone else { continue }
                isDone = true
                scanner.stopScanning()
                found(number)
                return
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
