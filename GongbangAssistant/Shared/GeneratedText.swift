import SwiftUI

/// Timing and colors shared by every place assistant-written text appears.
enum WritingStyle {
    /// Seconds one glyph takes to go from the lead color to its resting color.
    static let settle = 0.5
    /// Shares of `settle`. A glyph fades in in the lead color and holds it, turns to the trail color and holds
    /// that, then settles.
    static let leadIn = 0.12
    static let leadUntil = 0.28
    static let trailFrom = 0.45
    static let trailUntil = 0.62

    /// Seconds the reveal front needs to cross a text of this length.
    static func sweep(characters: Int) -> Double {
        min(1.6, max(0.6, 0.4 + Double(characters) * 0.008))
    }

    /// The band behind the reveal front, from resting text (location 0) to the still invisible front (location 1).
    static func band(resting: Color) -> Gradient {
        Gradient(stops: [
            .init(color: resting, location: 0),
            .init(color: .writingTrail, location: 1 - trailUntil),
            .init(color: .writingTrail, location: 1 - trailFrom),
            .init(color: .writingLead, location: 1 - leadUntil),
            .init(color: .writingLead, location: 1 - leadIn),
            .init(color: .writingLead.opacity(0), location: 1),
        ])
    }

    /// The waiting shimmer: a band of the trail and lead colors that crosses one line of text every 1.6 seconds.
    static func shimmer(at date: Date, resting: Color) -> LinearGradient {
        let phase = date.timeIntervalSinceReferenceDate.truncatingRemainder(dividingBy: 1.6) / 1.6
        return LinearGradient(
            stops: [
                .init(color: resting, location: 0), .init(color: .writingTrail, location: 0.35),
                .init(color: .writingLead, location: 0.65), .init(color: resting, location: 1),
            ],
            startPoint: UnitPoint(x: phase * 1.8 - 0.8, y: 0.5), endPoint: UnitPoint(x: phase * 1.8, y: 0.5))
    }
}

/// Draws text as a front that crosses it in reading order: glyphs appear in the lead color, turn to the trail
/// color, then rest. Layout never changes, so a row has its final height from the first frame.
/// Nonisolated: SwiftUI may call `draw` off the main thread.
nonisolated struct WritingRenderer: TextRenderer {
    /// 0 hides everything; 1 is the resting text.
    var progress: Double
    /// Share of the whole run that one glyph's color change takes: settle / (sweep + settle).
    let tail: Double
    /// `WritingStyle.band`: resting color first, invisible front last.
    let band: Gradient
    /// Reduce Motion: no travelling front; the whole text changes color in place.
    let isUniform: Bool

    var animatableData: Double {
        get { progress }
        set { progress = newValue }
    }

    func draw(layout: Text.Layout, in context: inout GraphicsContext) {
        let widths = layout.map(\.typographicBounds.width)
        let length = max(widths.reduce(0, +), 1)
        // Lines are treated as one long strip, so the front runs off the end of a line onto the next.
        let bandLength = isUniform ? length * 1000 : length * tail / (1 - tail)
        let front = isUniform ? progress * bandLength : length * progress / (1 - tail)
        var offset: CGFloat = 0
        for (line, width) in zip(layout, widths) {
            let reach = front - (isUniform ? 0 : offset)
            offset += width
            if progress >= 1 || reach - bandLength >= width {
                context.draw(line)
            } else if reach > 0 {
                let rect = line.typographicBounds.rect
                var masked = context
                masked.clipToLayer { $0.draw(line) }
                masked.fill(Path(rect.insetBy(dx: -8, dy: -8)), with: .linearGradient(
                    band, startPoint: CGPoint(x: rect.minX + reach - bandLength, y: rect.midY),
                    endPoint: CGPoint(x: rect.minX + reach, y: rect.midY)))
            }
        }
    }
}

/// Text the assistant just wrote. While `isFresh` is true it plays the writing reveal once and then clears the
/// flag, so a row that scrolls away and comes back never replays it. It adds no gesture, so it is safe inside
/// a row that is a link or holds buttons.
struct GeneratedText: View {
    let text: AttributedString
    @Binding var isFresh: Bool
    @State private var progress: Double
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    init(_ text: AttributedString, isFresh: Binding<Bool>) {
        self.text = text
        _isFresh = isFresh
        _progress = State(initialValue: isFresh.wrappedValue ? 0 : 1)
    }

    var body: some View {
        let sweep = reduceMotion ? 0 : WritingStyle.sweep(characters: text.characters.count)
        let total = sweep + WritingStyle.settle
        Text(text)
            .textRenderer(WritingRenderer(progress: progress, tail: WritingStyle.settle / total,
                                          band: WritingStyle.band(resting: .primary), isUniform: reduceMotion))
            .task {
                guard isFresh else { return }
                withAnimation(.linear(duration: total)) {
                    progress = 1
                } completion: {
                    isFresh = false
                }
            }
            .accessibilityIdentifier(isFresh ? "assistant.writing" : "assistant.generated")
    }
}

/// Shown until assistant text arrives: the face and one line with a color band moving across it.
struct GeneratingIndicator: View {
    let label: String
    var showsFace = true
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        HStack(spacing: 8) {
            if showsFace {
                AssistantFace(size: .card)
                    .accessibilityHidden(true)
            }
            if reduceMotion {
                Text(label)
                    .foregroundStyle(Color.secondaryText)
                ProgressView()
                    .controlSize(.small)
            } else {
                TimelineView(.animation) { context in
                    Text(label)
                        .foregroundStyle(WritingStyle.shimmer(at: context.date, resting: .secondaryText))
                }
            }
        }
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(label)
        .accessibilityIdentifier("assistant.generating")
    }
}

#Preview("쓰기 · 단계") {
    let text = AttributedString("안녕하세요, 오롯 공방이에요. 토요일 2시 물레 클래스는 두 자리 남아 있어요. 예약금 2만 원을 보내 주시면 자리를 잡아 둘게요.")
    let total = WritingStyle.sweep(characters: text.characters.count) + WritingStyle.settle
    List {
        ForEach([0.15, 0.35, 0.55, 0.75, 1.0], id: \.self) { progress in
            Text(text)
                .textRenderer(WritingRenderer(progress: progress, tail: WritingStyle.settle / total,
                                              band: WritingStyle.band(resting: .primary), isUniform: false))
        }
    }
}

#Preview("쓰기 · 재생") {
    @Previewable @State var isFresh = true
    @Previewable @State var run = 0
    VStack(alignment: .leading, spacing: 16) {
        GeneratingIndicator(label: "비서가 현황을 보고 있어요")
            .font(.subheadline)
        GeneratedText(AttributedString("안녕하세요, 오롯 공방이에요. 토요일 2시 물레 클래스는 두 자리 남아 있어요. 예약금 2만 원을 보내 주시면 자리를 잡아 둘게요."), isFresh: $isFresh)
            .id(run)
        Button("다시 보기") {
            isFresh = true
            run += 1
        }
    }
    .padding()
}
