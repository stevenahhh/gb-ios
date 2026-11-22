import SwiftUI
import UIKit

struct WorkshopInfoView: View {
    let workshop: WorkshopProfile?
    @State private var name: String
    @State private var ownerTitle: String
    @State private var phone: String
    @State private var address: String
    @State private var description: String
    @State private var place: GeocodeResult?
    @State private var errorMessage: String?
    @State private var isSearching = false
    @State private var mapImage: UIImage?
    @Environment(AppModel.self) private var app
    @Environment(\.dismiss) private var dismiss

    private let runID = "workshop.save"

    init(workshop: WorkshopProfile?) {
        self.workshop = workshop
        _name = State(initialValue: workshop?.name ?? "")
        _ownerTitle = State(initialValue: workshop?.ownerTitle ?? "사장님")
        _phone = State(initialValue: workshop?.phone ?? "")
        _address = State(initialValue: workshop?.address ?? "")
        _description = State(initialValue: workshop?.description ?? "")
    }

    /// Save turns on only when something changed, as on every settings screen.
    private var hasChanges: Bool {
        name != (workshop?.name ?? "") || ownerTitle != (workshop?.ownerTitle ?? "사장님")
            || phone != (workshop?.phone ?? "") || address != (workshop?.address ?? "")
            || description != (workshop?.description ?? "") || place != nil
    }

    private var canSave: Bool {
        hasChanges &&
        !name.trimmingCharacters(in: .whitespaces).isEmpty && !ownerTitle.trimmingCharacters(in: .whitespaces).isEmpty
    }

    var body: some View {
        List {
            CardSection("기본 정보") {
                LabeledContent("공방 이름") {
                    TextField("공방 이름", text: $name)
                        .multilineTextAlignment(.trailing)
                        .accessibilityIdentifier("workshop.name")
                }
                LabeledContent("대표자") {
                    TextField("호칭", text: $ownerTitle)
                        .multilineTextAlignment(.trailing)
                }
                LabeledContent("전화번호") {
                    TextField("전화번호", text: $phone)
                        .keyboardType(.phonePad)
                        .multilineTextAlignment(.trailing)
                }
                VStack(alignment: .leading, spacing: 6) {
                    Text("소개")
                    TextField("공방 소개", text: $description, axis: .vertical)
                        .foregroundStyle(Color.secondaryText)
                }
            }

            CardSection {
                TextField("도로명 주소", text: $address)
                    .textContentType(.fullStreetAddress)
                    .submitLabel(.search)
                    .onSubmit { Task { await search() } }
                    .accessibilityIdentifier("workshop.address")
                Button {
                    Task { await search() }
                } label: {
                    if isSearching {
                        ProgressView("지도에서 찾고 있어요")
                    } else {
                        Label("지도로 위치 보기", systemImage: "map")
                    }
                }
                .disabled(isSearching || address.trimmingCharacters(in: .whitespaces).isEmpty)
            } header: {
                Text("공방 주소")
            } footer: {
                Text("이 주소를 네이버 지도에서 찾아볼게요. 저장을 누르시면 찾아낸 위치도 같이 보관돼요.")
            }

            if let errorMessage {
                CardSection {
                    // Orange stays on the symbol; orange words measure about 2:1 on the light card.
                    Label {
                        Text(errorMessage)
                            .foregroundStyle(.primary)
                    } icon: {
                        Image(systemName: "exclamationmark.circle.fill")
                            .foregroundStyle(.orange)
                    }
                    .accessibilityIdentifier("workshop.error")
                }
            }

            if let place {
                CardSection("찾은 위치") {
                    Text(place.address)
                        .textSelection(.enabled)
                    Group {
                        if let mapImage {
                            Image(uiImage: mapImage).resizable().scaledToFit()
                                .accessibilityLabel("지도로 본 공방 위치")
                        } else {
                            ProgressView()
                                .frame(maxWidth: .infinity, minHeight: 160)
                                .background(CalendarTokens.fill)
                        }
                    }
                    .clipShape(.inner)
                    .animation(.default, value: mapImage == nil)
                }
            }
        }
        .cardList()
        .navigationTitle("공방 정보")
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .confirmationAction) {
                Button(action: save) {
                    BusyLabel(title: "저장", isBusy: app.isRunning(runID))
                }
                .disabled(app.isRunning(runID) || !canSave)
                .accessibilityIdentifier("workshop.save")
            }
        }
    }

    private func save() {
        let addressChanged = address != workshop?.address
        let draft = WorkshopDraft(
            name: name, ownerTitle: ownerTitle, phone: phone, address: place?.address ?? address,
            description: description,
            latitude: place?.lat ?? (addressChanged ? nil : workshop?.latitude),
            longitude: place?.lng ?? (addressChanged ? nil : workshop?.longitude),
            expectedRevision: workshop?.revision ?? 0
        )
        Task {
            if await app.run(id: runID, { _ = try await RoundupAPI.saveWorkshop(draft) }) { dismiss() }
        }
    }

    private func search() async {
        isSearching = true
        defer { isSearching = false }
        do {
            let found = try await RoundupAPI.geocode(address)
            place = found
            mapImage = nil
            errorMessage = nil
            mapImage = UIImage(data: try await RoundupAPI.staticMap(for: found))
        } catch {
            place = nil
            errorMessage = error.localizedDescription
        }
    }
}
