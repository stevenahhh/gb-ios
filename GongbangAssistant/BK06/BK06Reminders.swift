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

    func refresh(_ reminders: [BK06Reminder]) async {
        let center = UNUserNotificationCenter.current()
        center.delegate = self
        status = await center.notificationSettings().authorizationStatus
        guard status == .authorized else { return }
        let old = await center.pendingNotificationRequests().map(\.identifier).filter { $0.hasPrefix(Self.prefix) }
        center.removePendingNotificationRequests(withIdentifiers: old)
        for reminder in reminders {
            guard let date = BK06Format.date(reminder.fireAt), date > .now else { continue }
            let content = UNMutableNotificationContent()
            content.title = "\(reminder.customerName) 님 아직 도착 전"
            content.body = "오셨는지 아직 체크 안 하셨어요. 눌러서 봐 주세요."
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
