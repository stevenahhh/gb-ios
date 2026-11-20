import SwiftUI

struct AreaRoute: Hashable {
    let area: OperationArea
    var filter: String?
}

// Value navigation keeps a detail open when its row moves in a reloaded list.
enum AppRoute: Hashable {
    case booking(String)
    case classSession(String)
    case work(CardKind, String)
    case inquiry(String)
    case draft(DraftKind, String)
}

extension View {
    func appDestinations() -> some View {
        navigationDestination(for: AreaRoute.self) { route in
            OperationAreaView(area: route.area, initialFilter: route.filter)
        }
        .navigationDestination(for: AppRoute.self) { route in
            switch route {
            case .booking(let id): BookingDetailView(id: id)
            case .classSession(let id): ClassSessionView(id: id)
            case .work(let kind, let id): WorkDetailView(kind: kind, id: id)
            case .inquiry(let id): InquiryDetailView(id: id)
            case .draft(let kind, let id): AssistantDraftDetailView(kind: kind, id: id)
            }
        }
    }
}
