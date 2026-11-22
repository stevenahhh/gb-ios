import SwiftUI

struct WorkshopStep: View {
    let next: () -> Void
    let skip: () -> Void

    @State private var loader = Loader<SettingsData>()
    @State private var name = ""
    @State private var ownerTitle = "사장님"
    @State private var phone = ""
    @State private var address = ""
    /// The server copy the fields were filled from. Its revision goes back with the save.
    @State private var base: WorkshopProfile?
    @State private var hasFilled = false
    @State private var types = BusinessType.saved
    @State private var errorMessage: String?
    @State private var isSaving = false
    @State private var isEditingAll = false
    @Environment(AppModel.self) private var app

    private var hasChanges: Bool {
        name != (base?.name ?? "") || ownerTitle != (base?.ownerTitle ?? "사장님")
            || phone != (base?.phone ?? "") || address != (base?.address ?? "")
    }

    private var canSave: Bool {
        !name.trimmingCharacters(in: .whitespaces).isEmpty
            && !ownerTitle.trimmingCharacters(in: .whitespaces).isEmpty
    }

    private var addressChanged: Bool { address != (base?.address ?? "") }

    /// What the full screen opens with: the typed fields over the saved copy, so nothing typed here is lost there.
    private var typedProfile: WorkshopProfile {
        WorkshopProfile(
            name: name, ownerTitle: ownerTitle, phone: phone, address: address,
            description: base?.description ?? "",
            // Coordinates belong to the saved address; a new address has none until it is checked on the map.
            latitude: addressChanged ? nil : base?.latitude,
            longitude: addressChanged ? nil : base?.longitude,
            revision: base?.revision ?? 0)
    }

    var body: some View {
        LoadableContent(loader: loader, retry: load) { _ in
            form
        }
        .task(id: app.dataVersion) { await load() }
        // A cached response shows first, so the fields fill from it without waiting for the network.
        .onChange(of: loader.value?.workshop, initial: true) { _, profile in
            if loader.value != nil { fill(profile) }
        }
        .sheet(isPresented: $isEditingAll) {
            NavigationStack {
                WorkshopInfoView(workshop: typedProfile)
                    .toolbar {
                        ToolbarItem(placement: .cancellationAction) { Button("닫기") { isEditingAll = false } }
                    }
            }
        }
    }

    private var form: some View {
        List {
            OnboardingStepTitleRow(title: "공방 정보를 확인해 주세요")
            CardSection("기본 정보") {
                LabeledContent("공방 이름") {
                    TextField("공방 이름", text: $name)
                        .multilineTextAlignment(.trailing)
                        .accessibilityIdentifier("onboarding.workshop.name")
                }
                LabeledContent("대표자") {
                    TextField("호칭", text: $ownerTitle)
                        .multilineTextAlignment(.trailing)
                        .accessibilityIdentifier("onboarding.workshop.ownerTitle")
                }
                LabeledContent("전화번호") {
                    TextField("전화번호", text: $phone)
                        .keyboardType(.phonePad)
                        .textContentType(.telephoneNumber)
                        .multilineTextAlignment(.trailing)
                        .accessibilityIdentifier("onboarding.workshop.phone")
                }
                LabeledContent("주소") {
                    TextField("도로명 주소", text: $address)
                        .textContentType(.fullStreetAddress)
                        .multilineTextAlignment(.trailing)
                        .accessibilityIdentifier("onboarding.workshop.address")
                }
            }

            if let errorMessage {
                CardSection {
                    Label {
                        Text(verbatim: errorMessage)
                            .foregroundStyle(.primary)
                    } icon: {
                        Image(systemName: "exclamationmark.circle.fill")
                            .foregroundStyle(.orange)
                    }
                    .accessibilityIdentifier("onboarding.workshop.error")
                }
            }

            CardSection {
                ForEach(BusinessType.allCases) { type in
                    typeRow(type)
                }
            } header: {
                Text("하는 일")
            } footer: {
                Text("여러 개를 고를 수 있어요. 이 선택은 이 기기에만 저장해요.")
            }

            CardSection {
                Button {
                    isEditingAll = true
                } label: {
                    HStack {
                        Label { Text("소개와 지도 위치 입력") } icon: { MenuIcon(systemName: "map") }
                        Spacer(minLength: 8)
                        Image(systemName: "chevron.forward")
                            .font(.footnote.weight(.semibold))
                            .foregroundStyle(.tertiary)
                            .accessibilityHidden(true)
                    }
                    .contentShape(.rect)
                }
                .buttonStyle(.plain)
                .accessibilityIdentifier("onboarding.workshop.more")
            }
        }
        .cardList()
        .onboardingStepPrimaryButton(title: "저장하고 다음", isBusy: isSaving, isEnabled: canSave,
                                     identifier: "onboarding.workshop.save", action: save)
    }

    private func typeRow(_ type: BusinessType) -> some View {
        let isChosen = types.contains(type)
        return Button {
            if isChosen { types.remove(type) } else { types.insert(type) }
            BusinessType.saved = types
        } label: {
            HStack {
                Text(type.title)
                Spacer(minLength: 8)
                if isChosen {
                    Image(systemName: "checkmark")
                        .font(.body.weight(.semibold))
                        .accessibilityHidden(true)
                }
            }
            .contentShape(.rect)
        }
        .buttonStyle(.plain)
        .accessibilityAddTraits(isChosen ? .isSelected : [])
        .accessibilityIdentifier("onboarding.workshop.type.\(type.rawValue)")
    }

    private func load() async {
        await loader.load { try await RoundupAPI.settings() }
        if let data = loader.value { fill(data.workshop) }
    }

    /// A reload with the same revision brings nothing new, so typed text stays. A newer revision replaces it.
    private func fill(_ profile: WorkshopProfile?) {
        guard !hasFilled || profile?.revision != base?.revision else { return }
        base = profile
        name = profile?.name ?? ""
        ownerTitle = profile?.ownerTitle ?? "사장님"
        phone = profile?.phone ?? ""
        address = profile?.address ?? ""
        hasFilled = true
    }

    private func save() {
        guard hasChanges || base == nil else {
            next()
            return
        }
        let saved = typedProfile
        let draft = WorkshopDraft(
            name: saved.name, ownerTitle: saved.ownerTitle, phone: saved.phone, address: saved.address,
            description: saved.description, latitude: saved.latitude, longitude: saved.longitude,
            expectedRevision: saved.revision)
        Task {
            isSaving = true
            defer { isSaving = false }
            do {
                base = try await RoundupAPI.saveWorkshop(draft)
                errorMessage = nil
                app.dataDidChange()
                next()
            } catch let error as RoundupAPIError where error.isConflict {
                // 409: the reload brings a newer revision, which replaces the fields with what is saved now.
                await load()
                errorMessage = "다른 곳에서 공방 정보가 먼저 바뀌었어요. 최신 내용을 불러왔으니 확인하고 다시 저장해 주세요."
            } catch {
                errorMessage = error.localizedDescription
            }
        }
    }
}
