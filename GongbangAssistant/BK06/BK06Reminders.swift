import Foundation
import Observation
import UserNotifications

/// Local 15-minute checks. Nothing is sent to a customer; a notice only opens the late card.
@Observable
final class BK06Reminders: NSObject, UNUserNotificationCenterDelegate {
    static let shared = BK06Reminders()
    private static let prefix = "bk06.late."

    var openedBookingID: String?
    private(set) var status: UNAuthorizationStatus = .authorized

    /// The delegate comes with the first access, not the first load, so a tap before the cards arrive is not lost.
    private override init() {
        super.init()
        UNUserNotificationCenter.current().delegate = self
    }

    func refresh(_ reminders: [BK06Reminder]) async {
        let center = UNUserNotificationCenter.current()
        status = await center.notificationSettings().authorizationStatus
        guard status == .authorized else { return }
        let old = await center.pendingNotificationRequests().map(\.identifier).filter { $0.hasPrefix(Self.prefix) }
        center.removePendingNotificationRequests(withIdentifiers: old)
        for reminder in reminders {
            guard let date = BK06Format.date(reminder.fireAt), date > .now else { continue }
            let content = UNMutableNotificationContent()
            content.title = "\(reminder.customerName) 님이 아직 안 오셨어요"
            content.body = "출석 체크가 아직 없어요. 눌러서 확인해 주세요."
            content.sound = .default
            let trigger = UNTimeIntervalNotificationTrigger(timeInterval: date.timeIntervalSinceNow, repeats: false)
            try? await center.add(UNNotificationRequest(
                identifier: Self.prefix + reminder.bookingId, content: content, trigger: trigger))
        }
    }

    func requestPermission() async {
        _ = try? await UNUserNotificationCenter.current().requestAuthorization(options: [.alert, .sound])
        status = await UNUserNotificationCenter.current().notificationSettings().authorizationStatus
    }

    nonisolated func userNotificationCenter(_ center: UNUserNotificationCenter, willPresent notification: UNNotification)
        async -> UNNotificationPresentationOptions { [.banner, .sound] }

    nonisolated func userNotificationCenter(_ center: UNUserNotificationCenter, didReceive response: UNNotificationResponse)
        async {
        let identifier = response.notification.request.identifier
        await MainActor.run {
            guard identifier.hasPrefix(Self.prefix) else { return }
            openedBookingID = String(identifier.dropFirst(Self.prefix.count))
        }
    }
}
