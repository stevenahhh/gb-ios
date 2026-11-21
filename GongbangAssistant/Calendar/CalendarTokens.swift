import SwiftUI
import UIKit

/// The calendar's only colors: one label color for emphasis plus neutral steps.
/// System `secondaryLabel` is too faint on white, so secondary text uses its own pair.
enum CalendarTokens {
    static let background = pair(0xFFFFFF, 0x000000)
    static let label = pair(0x1C1C1E, 0xFFFFFF)
    static let secondary = pair(0x636366, 0xAEAEB2)
    /// Dots and arrows only; never text. 3:1 or better on the page and on the pinned box in both modes, so the
    /// schedule dots under a date can be read.
    static let tertiary = pair(0x8A8A8E, 0x6C6C70)
    static let separator = pair(0xE5E5EA, 0x38383A)
    static let fill = pair(0xF2F2F7, 0x1C1C1E)
    static let pinned = pair(0xF5F5F7, 0x1C1C1E)

    // UIKit resolves dynamic colors off the main thread during animations, so this must not be main-actor bound.
    private nonisolated static func pair(_ light: UInt32, _ dark: UInt32) -> Color {
        Color(uiColor: UIColor { @Sendable traits in
            UIColor(calendarHex: traits.userInterfaceStyle == .dark ? dark : light)
        })
    }
}

private extension UIColor {
    nonisolated convenience init(calendarHex hex: UInt32) {
        self.init(
            red: CGFloat((hex >> 16) & 0xFF) / 255,
            green: CGFloat((hex >> 8) & 0xFF) / 255,
            blue: CGFloat(hex & 0xFF) / 255,
            alpha: 1
        )
    }
}
