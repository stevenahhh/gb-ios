import RoundupCore
import SwiftUI

/// What one row may claim. 수집 중 comes only from GET /collectors/status; a stored value is 저장됨 and nothing more.
enum ConnectionRowState: Equatable {
    case collecting
    case saved
    case empty
    case planned

    /// A badge only where a state stands behind it; an empty slot shows none.
    var badge: Status? {
        switch self {
        case .collecting: Status(text: "가져오는 중", tone: .progress)
        case .saved: Status(text: "저장됨", tone: .done)
        case .planned: Status(text: "준비 중", tone: .neutral)
        case .empty: nil
        }
    }

    static func resolve(service: ConnectionService, item: ServiceConnection?,
                        source: CollectorStatus.Source?) -> ConnectionRowState {
        guard service.availability == .savable, let item else { return .planned }
        if source?.state == .collecting { return .collecting }
        return item.isSaved ? .saved : .empty
    }
}

/// One service: its name and state, what it brings, the stored value or what is needed, and what is true today.
struct ConnectionRow: View {
    let service: ConnectionService
    let state: ConnectionRowState
    /// The stored value as the server normalised it.
    var value: String?
    /// The collector's own words for a source that is not collecting.
    var note: String?
    @Environment(\.dynamicTypeSize) private var dynamicTypeSize

    private var hasValue: Bool { (state == .saved || state == .collecting) && value != nil }

    var body: some View {
        Label {
            VStack(alignment: .leading, spacing: 4) {
                heading
                Text(verbatim: service.brings)
                    .font(.subheadline)
                    .foregroundStyle(Color.secondaryText)
                Text(verbatim: hasValue ? (value ?? "") : "필요한 것: \(service.needs)")
                    .font(.subheadline.weight(hasValue ? .semibold : .regular))
                    .foregroundStyle(hasValue ? Color.primary : Color.secondaryText)
                if state != .collecting {
                    Text(verbatim: note ?? service.today)
                        .font(.subheadline)
                        .foregroundStyle(Color.secondaryText)
                }
            }
        } icon: {
            MenuIcon(systemName: service.symbol)
        }
        .frame(minHeight: 44)
        .contentShape(Rectangle())
        .accessibilityElement(children: .combine)
        .accessibilityIdentifier("connections.row.\(service.id)")
    }

    /// The badge sits at the trailing edge, and under the name at accessibility sizes.
    private var heading: some View {
        let isLarge = dynamicTypeSize.isAccessibilitySize
        let layout = isLarge
            ? AnyLayout(VStackLayout(alignment: .leading, spacing: 6))
            : AnyLayout(HStackLayout(alignment: .firstTextBaseline, spacing: 8))
        return layout {
            Text(verbatim: service.name)
                .font(.headline)
            if !isLarge { Spacer(minLength: 8) }
            if let badge = state.badge {
                StatusBadge(badge)
            }
        }
    }
}
