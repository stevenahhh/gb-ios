import SwiftUI

/// A whole-number field with its unit behind it. An empty field is nil, never zero.
struct OutreachNumberField: View {
    let title: String
    @Binding var value: Int?
    let unit: String
    let identifier: String
    /// Shown under the field while the value cannot be saved.
    var problem: String?

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            LabeledContent {
                HStack(spacing: 4) {
                    TextField("입력", value: $value, format: .number)
                        .keyboardType(.numberPad)
                        .multilineTextAlignment(.trailing)
                        .monospacedDigit()
                        .accessibilityLabel(title)
                        .accessibilityIdentifier(identifier)
                    Text(unit)
                        .foregroundStyle(Color.secondaryText)
                }
            } label: {
                Text(title)
            }
            if let problem {
                Label(problem, systemImage: "exclamationmark.circle")
                    .font(.subheadline)
                    .accessibilityIdentifier("\(identifier).problem")
            }
        }
    }
}

/// A name and its value at the app's readable secondary gray; LabeledContent's own gray is too light.
struct OutreachValueRow: View {
    let title: String
    let value: String

    var body: some View {
        LabeledContent(title) {
            Text(verbatim: value)
                .monospacedDigit()
                .multilineTextAlignment(.trailing)
                .foregroundStyle(Color.secondaryText)
        }
    }
}

struct ClassCostListView: View {
    @State private var loader = Loader<OutreachCostSettings>()
    @Environment(AppModel.self) private var app

    var body: some View {
        LoadableContent(loader: loader, retry: load) { data in
            if data.classes.isEmpty {
                ContentUnavailableView("아직 만든 수업이 없어요", systemImage: "square.stack",
                                       description: Text("수업부터 하나 캘린더에 만들어 주세요"))
            } else {
                list(data)
            }
        }
        .navigationTitle("수업마다 드는 돈")
        .navigationBarTitleDisplayMode(.inline)
        .task(id: app.dataVersion) { await load() }
    }

    private func load() async {
        await loader.load { try await RoundupAPI.outreachCosts() }
    }

    private func list(_ data: OutreachCostSettings) -> some View {
        List {
            CardSection("수업", footer: "재료비와 시간을 채운 수업만 출장 수업을 맡아도 될지 따져 봐요.") {
                ForEach(data.classes) { item in
                    NavigationLink {
                        ClassCostEditView(item: item)
                    } label: {
                        row(item)
                    }
                    .accessibilityIdentifier("classCost.\(item.classId)")
                }
            }
            CardSection("출장 수업 기본 설정") {
                NavigationLink {
                    OutreachDefaultsView(saved: data.defaults)
                } label: {
                    Label {
                        VStack(alignment: .leading, spacing: 4) {
                            Text("강사비, 출장비")
                            if let defaults = data.defaults {
                                Text("한 시간 강사비 \(OutreachFormat.won(defaults.instructorHourlyKrw))")
                                    .font(.subheadline)
                                    .foregroundStyle(Color.secondaryText)
                            } else {
                                StatusBadge(Status(text: "채워 주세요", tone: .attention))
                            }
                        }
                    } icon: {
                        MenuIcon(systemName: "car")
                    }
                }
                .accessibilityIdentifier("classCost.defaults")
            }
        }
        .cardList()
        .refreshable { await load() }
    }

    private func row(_ item: OutreachClassCost) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(verbatim: item.title)
            if item.isMissing {
                StatusBadge(Status(text: "원가 없음", tone: .attention))
            } else {
                PhraseText(text: "재료비 1인 \(OutreachFormat.won(item.materialPerPersonKrw)) · 원데이 클래스 가격 \(OutreachFormat.won(item.onedayPriceKrw))")
                    .font(.subheadline)
                    .foregroundStyle(Color.secondaryText)
            }
        }
    }
}

struct ClassCostEditView: View {
    let item: OutreachClassCost
    @State private var material: Int?
    @State private var price: Int?
    @State private var prep: Int?
    @State private var cleanup: Int?
    @State private var headcount: Int?
    @State private var errorMessage: String?
    @State private var isSaving = false
    @Environment(AppModel.self) private var app
    @Environment(\.dismiss) private var dismiss

    init(item: OutreachClassCost) {
        self.item = item
        _material = State(initialValue: item.materialPerPersonKrw)
        _price = State(initialValue: item.onedayPriceKrw)
        _prep = State(initialValue: item.prepMinutes)
        _cleanup = State(initialValue: item.cleanupMinutes)
        _headcount = State(initialValue: item.maxHeadcount)
    }

    private var isComplete: Bool {
        material != nil && price != nil && headcount != nil
            && [moneyProblem(material, minimum: 0), moneyProblem(price, minimum: 1), minuteProblem(prep),
                minuteProblem(cleanup), headcountProblem].allSatisfy { $0 == nil }
    }

    // The server refuses the same ranges; checking here puts the reason under the field that caused it.
    private func moneyProblem(_ value: Int?, minimum: Int) -> String? {
        value.flatMap { (minimum...1_000_000_000).contains($0) ? nil : "\(minimum)원에서 10억 원 사이로 적어 주세요." }
    }

    private func minuteProblem(_ value: Int?) -> String? {
        value.flatMap { (0...1440).contains($0) ? nil : "1,440분, 그러니까 하루보다 긴 시간은 적을 수 없어요." }
    }

    private var headcountProblem: String? {
        headcount.flatMap { (1...1000).contains($0) ? nil : "1명에서 1,000명 사이로 적어 주세요." }
    }

    var body: some View {
        List {
            CardSection("한 명당 드는 돈") {
                OutreachNumberField(title: "1인 재료비", value: $material, unit: "원", identifier: "classCost.material",
                                    problem: moneyProblem(material, minimum: 0))
                OutreachNumberField(title: "원데이 클래스 1인 가격", value: $price, unit: "원", identifier: "classCost.price",
                                    problem: moneyProblem(price, minimum: 1))
            }
            CardSection("수업 시간, 정원", footer: "만들어 두신 수업대로 수업 시간은 \(item.classMinutes)분으로 잡아요.") {
                OutreachNumberField(title: "수업 전 준비", value: $prep, unit: "분", identifier: "classCost.prep",
                                    problem: minuteProblem(prep))
                OutreachNumberField(title: "수업 뒤 정리", value: $cleanup, unit: "분", identifier: "classCost.cleanup",
                                    problem: minuteProblem(cleanup))
                OutreachNumberField(title: "최대 인원", value: $headcount, unit: "명", identifier: "classCost.headcount",
                                    problem: headcountProblem)
            }
            OutreachSaveSection(errorMessage: errorMessage, isBusy: isSaving, isEnabled: isComplete, save: save)
        }
        .cardList()
        .navigationTitle(item.title)
        .navigationBarTitleDisplayMode(.inline)
    }

    private func save() {
        guard let material, let price, let headcount else { return }
        let cost = OutreachClassCostUpdate(
            materialPerPersonKrw: material, onedayPriceKrw: price, prepMinutes: prep ?? 0,
            cleanupMinutes: cleanup ?? 0, maxHeadcount: headcount)
        Task {
            isSaving = true
            defer { isSaving = false }
            do {
                _ = try await RoundupAPI.saveClassCost(classID: item.classId, cost)
                app.dataDidChange()
                dismiss()
            } catch {
                errorMessage = error.localizedDescription
            }
        }
    }
}

/// The one prominent button of a cost form, with the failure shown above it and the entered values kept.
struct OutreachSaveSection: View {
    let errorMessage: String?
    let isBusy: Bool
    let isEnabled: Bool
    let save: () -> Void

    var body: some View {
        CardSection {
            if let errorMessage {
                Label {
                    Text(verbatim: errorMessage)
                } icon: {
                    Image(systemName: "exclamationmark.circle")
                }
                .accessibilityIdentifier("outreach.saveError")
                Button("다시 시도", action: save)
                    .buttonStyle(.bordered)
                    .controlSize(.large)
            }
            Button(action: save) {
                BusyLabel(title: "저장", isBusy: isBusy, isProminent: true)
                    .frame(maxWidth: .infinity)
            }
            .buttonStyle(.borderedProminent)
            .controlSize(.large)
            .disabled(!isEnabled || isBusy)
            .accessibilityIdentifier("outreach.save")
        }
    }
}

struct OutreachDefaultsView: View {
    @State private var hourly: Int?
    @State private var assistant: Int?
    @State private var mode: OutreachTravelMode
    @State private var perKm: Int?
    @State private var flat: Int?
    @State private var minimum: Int?
    @State private var errorMessage: String?
    @State private var isSaving = false
    @Environment(AppModel.self) private var app
    @Environment(\.dismiss) private var dismiss

    init(saved: OutreachDefaults?) {
        _hourly = State(initialValue: saved?.instructorHourlyKrw)
        _assistant = State(initialValue: saved?.assistantDailyKrw)
        _mode = State(initialValue: saved?.travelMode ?? .flat)
        _perKm = State(initialValue: saved?.travelPerKmKrw)
        _flat = State(initialValue: saved?.travelFlatKrw)
        _minimum = State(initialValue: saved?.minimumFeeKrw)
    }

    private var isComplete: Bool {
        hourly != nil && (mode == .flat ? flat != nil : perKm != nil)
    }

    var body: some View {
        List {
            CardSection("강사비") {
                OutreachNumberField(title: "한 시간 강사비", value: $hourly, unit: "원", identifier: "defaults.hourly")
                OutreachNumberField(title: "보조 강사 하루치", value: $assistant, unit: "원", identifier: "defaults.assistant")
            }
            CardSection("출장비") {
                Picker("출장비 계산 방법", selection: $mode) {
                    ForEach(OutreachTravelMode.allCases) { Text($0.label).tag($0) }
                }
                if mode == .flat {
                    OutreachNumberField(title: "한 번에 정해진 출장비", value: $flat, unit: "원", identifier: "defaults.flat")
                } else {
                    OutreachNumberField(title: "1km 갈 때마다 차비", value: $perKm, unit: "원", identifier: "defaults.perKm")
                }
            }
            CardSection("최소 금액", footer: "예산 이야기가 없는 문의라면 이보다 싸게는 안 불러요.") {
                OutreachNumberField(title: "출장 수업 최저 금액", value: $minimum, unit: "원", identifier: "defaults.minimum")
            }
            OutreachSaveSection(errorMessage: errorMessage, isBusy: isSaving, isEnabled: isComplete, save: save)
        }
        .cardList()
        .navigationTitle("출장 수업 기본 설정")
        .navigationBarTitleDisplayMode(.inline)
    }

    private func save() {
        let defaults = OutreachDefaults(
            instructorHourlyKrw: hourly ?? 0, assistantDailyKrw: assistant ?? 0, travelMode: mode,
            travelPerKmKrw: perKm ?? 0, travelFlatKrw: flat ?? 0, minimumFeeKrw: minimum ?? 0)
        Task {
            isSaving = true
            defer { isSaving = false }
            do {
                _ = try await RoundupAPI.saveOutreachDefaults(defaults)
                app.dataDidChange()
                dismiss()
            } catch {
                errorMessage = error.localizedDescription
            }
        }
    }
}
