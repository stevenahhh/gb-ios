import SwiftUI

/// The assistant's name lives here so the team can rename it in one place.
enum AssistantIdentity {
    static let name = "비서"
}

/// One face for the assistant everywhere: a clay circle with a white line vase.
/// It replaces the generic sparkles, and clay (`assistantAccent`) is used for nothing else.
struct AssistantFace: View {
    enum Size: CGFloat {
        case card = 22
        case composer = 24
        case sheet = 28
    }

    var size: Size = .card

    var body: some View {
        VaseShape()
            .stroke(.white, style: StrokeStyle(lineWidth: max(1.4, size.rawValue / 14), lineCap: .round, lineJoin: .round))
            .padding(size.rawValue * 0.22)
            .frame(width: size.rawValue, height: size.rawValue)
            .background(Color.assistantAccent, in: .circle)
            .accessibilityElement()
            .accessibilityLabel(AssistantIdentity.name)
    }
}

/// A small pottery vase: a lip, a narrow neck, and a round body.
/// SwiftUI may draw shapes off the main actor, so this stateless shape opts out of the target's default isolation.
nonisolated private struct VaseShape: Shape {
    func path(in rect: CGRect) -> Path {
        let w = rect.width, h = rect.height
        func point(_ x: CGFloat, _ y: CGFloat) -> CGPoint { CGPoint(x: rect.minX + x * w, y: rect.minY + y * h) }
        var path = Path()
        path.move(to: point(0.30, 0.04))
        path.addLine(to: point(0.70, 0.04))
        path.move(to: point(0.38, 0.04))
        path.addCurve(to: point(0.14, 0.62), control1: point(0.40, 0.28), control2: point(0.12, 0.34))
        path.addCurve(to: point(0.50, 0.98), control1: point(0.16, 0.86), control2: point(0.32, 0.98))
        path.addCurve(to: point(0.86, 0.62), control1: point(0.68, 0.98), control2: point(0.84, 0.86))
        path.addCurve(to: point(0.62, 0.04), control1: point(0.88, 0.34), control2: point(0.60, 0.28))
        return path
    }
}
