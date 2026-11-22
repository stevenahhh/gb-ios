import SwiftUI

/// The assistant's name lives here so the team can rename it in one place.
enum AssistantIdentity {
    static let name = "비서"
}

/// One face for the assistant everywhere: the 공도리 mark, the same character as the app icon.
struct AssistantFace: View {
    enum Size: CGFloat {
        case card = 22
        case composer = 24
        case sheet = 28
    }

    var size: Size = .card

    var body: some View {
        Image(.brandMark)
            .resizable()
            .interpolation(.high)
            .scaledToFit()
            .frame(width: size.rawValue, height: size.rawValue)
            .accessibilityElement()
            .accessibilityLabel(AssistantIdentity.name)
    }
}
