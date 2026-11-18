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

    private var canSave: Bool {
        !name.trimmingCharacters(in: .whitespaces).isEmpty && !ownerTitle.trimmingCharacters(in: .whitespaces).isEmpty
    }

    var body: some View {
        List {
            Section("기본 정보") {
                TextField("공방 이름", text: $name)
                    .accessibilityIdentifier("workshop.name")
                TextField("호칭", text: $ownerTitle)
                TextField("전화번호", text: $phone)
                    .keyboardType(.phonePad)
                TextField("소개", text: $description, axis: .vertical)
            }

            Section {
                TextField("도로명 주소", text: $address)
                    .textContentType(.fullStreetAddress)
                    .submitLabel(.search)
                    .onSubmit { Task { await search() } }
                    .accessibilityIdentifier("workshop.address")
                Button {
                    Task { await search() }
                } label: {
                    if isSearching {
                        ProgressView("위치를 찾는 중이에요")
                    } else {
                        Label("지도에서 위치 확인", systemImage: "map")
                    }
                }
                .disabled(isSearching || address.trimmingCharacters(in: .whitespaces).isEmpty)
            } header: {
                Text("공방 주소")
            } footer: {
                Text("네이버 지도로 주소를 확인해요. 저장하면 확인된 위치도 함께 보관해요.")
            }

            if let errorMessage {
                Label(errorMessage, systemImage: "exclamationmark.circle.fill")
                    .foregroundStyle(.orange)
            }

            if let place {
                Section("확인된 위치") {
                    Text(place.address)
                        .textSelection(.enabled)
                    Group {
                        if let mapImage {
                            Image(uiImage: mapImage).resizable().scaledToFit()
                                .accessibilityLabel("공방 위치 지도")
                        } else {
                            ProgressView()
                                .frame(maxWidth: .infinity, minHeight: 160)
                        }
                    }
                    .clipShape(.rect(cornerRadius: 12))
                }
            }
        }
        .listStyle(.insetGrouped)
        .navigationTitle("공방 정보")
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .confirmationAction) {
                if app.isRunning(runID) {
                    ProgressView()
                } else {
                    Button("저장", action: save)
                        .disabled(!canSave)
                        .accessibilityIdentifier("workshop.save")
                }
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
