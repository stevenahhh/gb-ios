import SwiftUI
import UIKit

struct WorkshopInfoView: View {
    @State private var address = "순천시 중앙로 255"
    @State private var place: GeocodeResult?
    @State private var errorMessage: String?
    @State private var isSearching = false
    @State private var mapImage: UIImage?

    var body: some View {
        List {
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
                Text("네이버 지도로 주소를 확인해요. 손님 안내 문구에 이 주소를 써요.")
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

#Preview {
    NavigationStack { WorkshopInfoView() }
}
