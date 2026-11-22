#if BUILD_B
import SwiftUI

/// A whole-number field with its unit behind it. An empty field is nil, never zero.
struct OutreachNumberField: View {
    let title: String
    @Binding var value: Int?
    let unit: String
    let identifier: String

    var body: some View {
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
    }
}

struct ClassCostListView: View {
    @State private var loader = Loader<OutreachCostSettings>()
    @Environment(AppModel.self) private var app

    var body: some View {
        LoadableContent(loader: loader, retry: load) { data in
            if data.classes.isEmpty {
                ContentUnavailableView("등록된 수업이 없습니다", systemImage: "square.stack",
                                       description: Text("캘린더에서 수업을 먼저 만들어 주세요"))
            } else {
                list(data)
            }
        }
        .navigationTitle("수업별 원가")
        .navigationBarTitleDisplayMode(.inline)
        .task(id: app.dataVersion) { await load() }
    }

    private func load() async {
        await loader.load { try await RoundupAPI.outreachCosts() }
    }

    private func list(_ data: OutreachCostSettings) -> some View {
        List {
            CardSection("수업", footer: "원가를 넣은 수업만 출강 가부를 판단해요.") {
                ForEach(data.classes) { item in
                    NavigationLink {
                        ClassCostEditView(item: item)
                    } label: {
                        row(item)
                    }
                    .accessibilityIdentifier("classCost.\(item.classId)")
                }
            }
            CardSection("출강 기본값") {
                NavigationLink {
                    OutreachDefaultsView(saved: data.defaults)
                } label: {
                    Label {
                        Text("강사비와 출장비")
                        if let defaults = data.defaults {
                            Text("시간당 강사비 \(OutreachFormat.won(defaults.instructorHourlyKrw))")
                                .foregroundStyle(Color.secondaryText)
                        } else {
                            StatusBadge(Status(text: "입력 필요", tone: .attention))
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
                PhraseText(text: "1인 재료비 \(OutreachFormat.won(item.materialPerPersonKrw)) · 원데이 \(OutreachFormat.won(item.onedayPriceKrw))")
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
        material.map { $0 >= 0 } == true && price.map { $0 > 0 } == true && headcount.map { $0 > 0 } == true
    }

    var body: some View {
        List {
            CardSection("한 사람 기준") {
                OutreachNumberField(title: "1인 재료비", value: $material, unit: "원", identifier: "classCost.material")
                OutreachNumberField(title: "원데이 1인 가격", value: $price, unit: "원", identifier: "classCost.price")
            }
            CardSection("시간과 정원", footer: "수업 시간은 등록한 수업의 \(item.classMinutes)분을 써요.") {
                OutreachNumberField(title: "준비 시간", value: $prep, unit: "분", identifier: "classCost.prep")
                OutreachNumberField(title: "뒷정리 시간", value: $cleanup, unit: "분", identifier: "classCost.cleanup")
                OutreachNumberField(title: "최대 인원", value: $headcount, unit: "명", identifier: "classCost.headcount")
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
                OutreachNumberField(title: "시간당 강사비", value: $hourly, unit: "원", identifier: "defaults.hourly")
                OutreachNumberField(title: "보조 강사 일당", value: $assistant, unit: "원", identifier: "defaults.assistant")
            }
            CardSection("출장비") {
                Picker("출장비 방식", selection: $mode) {
                    ForEach(OutreachTravelMode.allCases) { Text($0.label).tag($0) }
                }
                if mode == .flat {
                    OutreachNumberField(title: "고정 출장비", value: $flat, unit: "원", identifier: "defaults.flat")
                } else {
                    OutreachNumberField(title: "1km당 차량비", value: $perKm, unit: "원", identifier: "defaults.perKm")
                }
            }
            CardSection("최소 금액", footer: "예산을 모르는 문의에 이 금액보다 낮은 견적을 내지 않아요.") {
                OutreachNumberField(title: "출강 최소 금액", value: $minimum, unit: "원", identifier: "defaults.minimum")
            }
            OutreachSaveSection(errorMessage: errorMessage, isBusy: isSaving, isEnabled: isComplete, save: save)
        }
        .cardList()
        .navigationTitle("출강 기본값")
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
#endif
