import Observation
import SwiftUI
import UserNotifications

/// What K06 waits on the owner for; 확인해 주실 일 shows it.
@MainActor
@Observable
final class BK06Inbox {
    static let shared = BK06Inbox()
    private let loader = Loader<BK06Cards>()

    var cards: BK06Cards? { loader.value }
    var errorMessage: String? { loader.errorMessage }

    var rows: [BK06AttentionItem] {
        guard let cards else { return [] }
        return cards.late.map { .late($0) } + cards.refill.map { .refill($0) } + cards.underMin.map { .underMin($0) }
    }

    func load() async {
        await loader.load { try await RoundupAPI.k06Cards() }
        if let cards { await BK06Reminders.shared.refresh(cards.reminders) }
    }
}

enum BK06AttentionItem: Identifiable {
    case late(BK06LateCard)
    case refill(BK06RefillCard)
    case underMin(BK06UnderMinCard)

    /// Also the row's accessibility identifier.
    var id: String {
        switch self {
        case .late(let card): "k06.late.\(card.bookingId)"
        case .refill(let card): "k06.refill.\(card.sessionId)"
        case .underMin(let card): "k06.underMin.\(card.sessionId)"
        }
    }

    var title: String {
        switch self {
        case .late(let card): card.headline
        case .refill(let card): card.expired ? card.classTitle : "빈자리 \(card.openSeats)개 · 제안할 분 \(card.targetCount)명"
        case .underMin(let card): "예약 \(card.booked)명, 최소 \(card.minSeats)명 · 진행 여부 결정"
        }
    }

    var detail: String {
        switch self {
        case .late(let card): card.detail
        case .refill(let card):
            card.expired ? BK06Format.when(card.startsAt) : "\(card.classTitle) · \(BK06Format.when(card.startsAt))"
        case .underMin(let card): "\(card.className) · \(BK06Format.when(card.startsAt))"
        }
    }

    var isOverdue: Bool {
        if case .refill(let card) = self { card.expired } else { false }
    }
}

struct BK06AttentionRow: View {
    let item: BK06AttentionItem

    var body: some View {
        NavigationLink {
            switch item {
            case .late(let card): BK06LateView(bookingID: card.bookingId)
            case .refill(let card): BK06RefillView(sessionID: card.sessionId)
            case .underMin(let card): BK06UnderMinView(card: card)
            }
        } label: {
            AttentionRow(title: item.title, detail: item.detail, isOverdue: item.isOverdue) { EmptyView() }
        }
        .accessibilityIdentifier(item.id)
    }
}

/// The K06 entries that stay in 확인해 주실 일 whether or not anything waits.
struct BK06ToolRows: View {
    @State private var inbox = BK06Inbox.shared
    @State private var reminders = BK06Reminders.shared
    @AppStorage("bk06.notificationRowHidden") private var hidesPermission = false
    @Environment(\.openURL) private var openURL

    private var asksPermission: Bool {
        !hidesPermission && inbox.cards?.reminders.isEmpty == false
            && (reminders.status == .notDetermined || reminders.status == .denied)
    }

    var body: some View {
        if asksPermission { permissionRow }
        NavigationLink {
            BK06CancellationView()
        } label: {
            Label { Text("취소 메시지 붙여넣기") } icon: { MenuIcon(systemName: "doc.on.clipboard") }
        }
        .accessibilityIdentifier("k06.paste")
        if let cards = inbox.cards {
            NavigationLink { BK06SessionListView(sessions: cards.sessions) } label: {
                Label { Text("출석 체크와 대기 손님") } icon: { MenuIcon(systemName: "checklist") }
            }
            .accessibilityIdentifier("k06.sessions")
        }
        if let message = inbox.errorMessage {
            BK06ErrorRow(message: message)
            Button("다시 시도") { Task { await inbox.load() } }
        }
    }

    private var permissionRow: some View {
        AttentionRow(title: "15분 알림을 받으려면 알림을 켜 주세요", detail: nil) {
            AttentionButton(title: "알림 켜기", isProminent: false, isBusy: false) {
                if reminders.status == .denied, let url = URL(string: UIApplication.openSettingsURLString) {
                    openURL(url)
                } else {
                    Task {
                        await reminders.requestPermission()
                        await inbox.load()
                    }
                }
            }
            AttentionButton(title: "나중에", isProminent: false, isBusy: false) { hidesPermission = true }
        }
    }
}
