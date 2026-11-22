import SwiftUI

extension View {
    /// Opens the late check for a tapped notification. Attach it where the view outlives every tab and list row.
    func bk06NotificationSheet() -> some View { modifier(BK06NotificationSheet()) }
}

private struct BK06NotificationSheet: ViewModifier {
    @State private var reminders = BK06Reminders.shared

    private var opened: Binding<BK06OpenedBooking?> {
        Binding(get: { reminders.openedBookingID.map(BK06OpenedBooking.init) },
                set: { if $0 == nil { reminders.openedBookingID = nil } })
    }

    func body(content: Content) -> some View {
        content.sheet(item: opened) { item in
            NavigationStack { BK06LateView(bookingID: item.id) }
        }
    }
}

private struct BK06OpenedBooking: Identifiable {
    let id: String
}
