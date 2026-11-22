#if BUILD_B
import SwiftUI
import UserNotifications

/// The 오늘 tab's entry: paste a message, then whatever waits for the owner.
struct BK06TodaySection: View {
    @State private var loader = Loader<BK06Cards>()
    @State private var reminders = BK06Reminders.shared
    @AppStorage("bk06.notificationRowHidden") private var hidesPermission = false
    @Environment(AppModel.self) private var app
    @Environment(\.openURL) private var openURL

    private var opened: Binding<BK06OpenedBooking?> {
        Binding(get: { reminders.openedBookingID.map(BK06OpenedBooking.init) },
                set: { if $0 == nil { reminders.openedBookingID = nil } })
    }

    var body: some View {
        CardSection {
            NavigationLink {
                BK06CancellationView()
            } label: {
                Label { Text("취소 메시지 붙여넣기") } icon: { MenuIcon(systemName: "doc.on.clipboard") }
            }
            .accessibilityIdentifier("k06.paste")
            .task(id: app.dataVersion) { await load() }
            .sheet(item: opened) { item in
                NavigationStack { BK06LateView(bookingID: item.id) }
            }

            if let cards = loader.value {
                rows(cards)
            } else if let message = loader.errorMessage {
                BK06ErrorRow(message: message)
                Button("다시 시도") { Task { await load() } }
            }
        } header: {
            Text("취소·노쇼")
        }
    }

    private func load() async {
        await loader.load { try await RoundupAPI.k06Cards() }
        if let cards = loader.value { await reminders.refresh(cards.reminders) }
    }

    @ViewBuilder
    private func rows(_ cards: BK06Cards) -> some View {
        if !hidesPermission, !cards.reminders.isEmpty,
           reminders.status == .notDetermined || reminders.status == .denied {
            permissionRow
        }
        ForEach(cards.late) { card in
            NavigationLink { BK06LateView(bookingID: card.bookingId) } label: {
                row("\(card.customerName) 님이 아직 안 오셨어요", "\(card.classTitle) · 시작 \(BK06Format.elapsed(card.minutesLate)) 지남",
                    badge: "확인 필요")
            }
            .accessibilityIdentifier("k06.late.\(card.bookingId)")
        }
        ForEach(cards.refill) { card in
            NavigationLink { BK06RefillView(sessionID: card.sessionId) } label: {
                if card.expired {
                    VStack(alignment: .leading, spacing: 4) {
                        Text(verbatim: card.classTitle).font(.headline)
                        Label("지남", systemImage: "clock").font(.subheadline).foregroundStyle(Color.overdueRed)
                    }
                } else {
                    row("빈자리 \(card.openSeats)개", "\(card.classTitle) · \(BK06Format.when(card.startsAt))",
                        badge: "제안할 분 \(card.targetCount)명")
                }
            }
            .accessibilityIdentifier("k06.refill.\(card.sessionId)")
        }
        ForEach(cards.underMin) { card in
            NavigationLink { BK06UnderMinView(card: card) } label: {
                row("예약 \(card.booked)명, 최소 \(card.minSeats)명", "\(card.className) · \(BK06Format.when(card.startsAt))",
                    badge: "진행 여부 결정")
            }
            .accessibilityIdentifier("k06.underMin.\(card.sessionId)")
        }
        NavigationLink { BK06SessionListView(sessions: cards.sessions) } label: {
            Label { Text("출석 체크와 대기 손님") } icon: { MenuIcon(systemName: "checklist") }
        }
        .accessibilityIdentifier("k06.sessions")
    }

    private var permissionRow: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("15분 알림을 받으려면 알림을 켜 주세요")
            HStack {
                Button("알림 켜기") {
                    if reminders.status == .denied, let url = URL(string: UIApplication.openSettingsURLString) {
                        openURL(url)
                    } else {
                        Task {
                            await reminders.requestPermission()
                            await load()
                        }
                    }
                }
                Button("나중에") { hidesPermission = true }
            }
            .buttonStyle(.bordered)
        }
    }

    private func row(_ title: String, _ detail: String, badge: String) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(verbatim: title).font(.headline)
            PhraseText(text: detail).font(.subheadline).foregroundStyle(Color.secondaryText)
            BK06PendingLabel(text: badge)
        }
        .padding(.vertical, 4)
    }
}

struct BK06OpenedBooking: Identifiable {
    let id: String
}
#endif
