import SwiftUI
import UIKit

/// Saturated colors carry one meaning each; everything else stays black, white, and gray.
extension Color {
    /// Waiting for the owner before a deadline: the dot on 검토 대기, 포장·송장 대기, 예약금 대기.
    static let pendingOrange = dynamic(light: 0xE8820C, dark: 0xFF9F2E)
    /// Secondary text at 4.5:1 or better on white and on the dark card; lighter grays are for icons and rules only.
    static let secondaryText = dynamic(light: 0x636366, dark: 0xAEAEB2)
    /// The unfilled part of a progress ring.
    static let ringTrack = dynamic(light: 0xE5E5EA, dark: 0x3A3A3C)
    /// Assistant only: its face, draft marks, and the composer icon.
    static let assistantAccent = dynamic(light: 0xA84A2A, dark: 0xE08A66)

    // Nonisolated: SwiftUI resolves colors off the main thread, and a main-actor closure traps there.
    private static func dynamic(light: UInt32, dark: UInt32) -> Color {
        Color(uiColor: UIColor { @Sendable traits in
            let hex = traits.userInterfaceStyle == .dark ? dark : light
            return UIColor(red: CGFloat((hex >> 16) & 0xFF) / 255, green: CGFloat((hex >> 8) & 0xFF) / 255,
                           blue: CGFloat(hex & 0xFF) / 255, alpha: 1)
        })
    }
}
