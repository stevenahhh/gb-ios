import SwiftUI

/// Timing and look shared by every place assistant-written text appears.
/// Nonisolated: SwiftUI may draw the reveal off the main thread.
nonisolated enum WritingStyle {
    /// Seconds one glyph takes to come into focus and shed its tint once the reveal front reaches it.
    static let settle = 0.55
    /// Shares of `settle`. A glyph is opaque by `opaqueBy`, and sharp and in place by `sharpBy`. Its tint keeps
    /// the lead color until `turnFrom` and has turned to the trail color by `turnBy`; from `fadeFrom` it drains away.
    static let opaqueBy = 0.5
    static let sharpBy = 0.7
    static let turnFrom = 0.25
    static let turnBy = 0.6
    static let fadeFrom = 0.5
    /// Gaussian blur, in points, on a glyph the front has only just reached.
    static let blur: CGFloat = 8
    /// Levels the blur resolves through. Glyphs on one level share one blurred layer.
    static let blurSteps = 6
    /// Points a glyph starts below its resting place.
    static let rise: CGFloat = 3
    /// Characters the front passes each second, unless `sweep` has to hurry a long answer or hold back a short one.
    static let pace = 50.0
    /// Seconds one pass of the waiting shimmer takes.
    static let shimmerPeriod = 2.4

    /// Seconds the reveal front needs to cross a text of this length. A few words still take 0.4 seconds, so they
    /// do not pop in, and no answer takes more than 2.2, because the cards under it wait for the reveal to end.
    static func sweep(characters: Int) -> Double {
        min(2.2, max(0.4, Double(characters) / pace))
    }

    /// How far a glyph is through its arrival: 0 or less is still hidden, 1 or more is at rest. `progress` runs
    /// from 0 to 1 over `sweep + settle` seconds, and `share` is how far along the text the glyph sits.
    static func phase(progress: Double, share: Double, sweep: Double) -> Double {
        (progress * (sweep + settle) - share * sweep) / settle
    }

    /// How far a glyph `phase` of the way in still is from sharp and in place: 1 as the front reaches it, 0 from
    /// `sharpBy` on.
    static func unfocus(at phase: Double) -> Double {
        1 - UnitCurve.easeOut.value(at: phase / sharpBy)
    }

    /// The blur level of a glyph `phase` of the way in: `blurSteps` as the front reaches it, 0 once it is sharp.
    /// A level's radius grows with its square, so the levels crowd toward sharp, where a jump shows most.
    static func blurStep(at phase: Double) -> Int {
        Int((Double(blurSteps) * unfocus(at: phase).squareRoot()).rounded())
    }

    /// Draws the glyphs that are on their way in, given in reading order with how far along each one is.
    /// `content` draws a glyph at rest; this adds its fade, its small rise, its tint, and the blur that resolves.
    /// Glyphs on one blur level share one blurred layer, so a frame costs at most `blurSteps` blurs however
    /// long the text is. A blur filter on a glyph's own drawing would be cheaper, but it is cut off at the
    /// glyph's bounds, and a blurred layer per glyph halves the frame rate.
    static func draw<Glyph>(_ arriving: [(glyph: Glyph, phase: Double)], lead: Color.Resolved, trail: Color.Resolved,
                            in context: GraphicsContext, content: (Glyph, inout GraphicsContext) -> Void) {
        var rest = arriving[...]
        while let first = rest.first {
            let step = blurStep(at: first.phase)
            let level = rest.prefix { blurStep(at: $0.phase) == step }
            rest = rest.dropFirst(level.count)
            func paint(in target: GraphicsContext) {
                for (glyph, phase) in level {
                    var one = target
                    one.opacity *= UnitCurve.easeOut.value(at: phase / opaqueBy)
                    one.translateBy(x: 0, y: rise * unfocus(at: phase))
                    one.addFilter(.colorMatrix(tint(at: phase, lead: lead, trail: trail), isPremultiplied: true))
                    content(glyph, &one)
                }
            }
            guard step > 0 else {
                paint(in: context)
                continue
            }
            let share = CGFloat(step) / CGFloat(blurSteps)
            var blurred = context
            blurred.addFilter(.blur(radius: blur * share * share))
            blurred.drawLayer { paint(in: $0) }
        }
    }

    /// The tint on a glyph `phase` of the way in, as a matrix on premultiplied color: the glyph's own color gives
    /// way to the tint by the tint's strength, and its alpha stays. The tint turns from `lead` to `trail`, then
    /// drains into the glyph's own color.
    static func tint(at phase: Double, lead: Color.Resolved, trail: Color.Resolved) -> ColorMatrix {
        let turn = Float(UnitCurve.easeInOut.value(at: (phase - turnFrom) / (turnBy - turnFrom)))
        let strength = Float(1 - UnitCurve.easeInOut.value(at: (phase - fadeFrom) / (1 - fadeFrom)))
        var matrix = ColorMatrix()
        (matrix.r1, matrix.r4) = (1 - strength, strength * (lead.red + (trail.red - lead.red) * turn))
        (matrix.g2, matrix.g4) = (1 - strength, strength * (lead.green + (trail.green - lead.green) * turn))
        (matrix.b3, matrix.b4) = (1 - strength, strength * (lead.blue + (trail.blue - lead.blue) * turn))
        return matrix
    }

    /// The waiting shimmer: a soft band of the trail and lead colors, as wide as the line, that drifts across
    /// it. Each pass eases in and out, so the line rests in `resting` between passes.
    @MainActor static func shimmer(at date: Date, resting: Color) -> LinearGradient {
        let pass = date.timeIntervalSinceReferenceDate.truncatingRemainder(dividingBy: shimmerPeriod) / shimmerPeriod
        // The band starts one line width before the line and ends one line width past it.
        let start = UnitCurve.easeInOut.value(at: pass) * 2 - 1
        return LinearGradient(
            stops: [
                .init(color: resting, location: 0), .init(color: .writingTrail, location: 0.38),
                .init(color: .writingLead, location: 0.62), .init(color: resting, location: 1),
            ],
            startPoint: UnitPoint(x: start, y: 0.5), endPoint: UnitPoint(x: start + 1, y: 0.5))
    }
}

/// Draws text as a soft front that crosses it in reading order: each glyph fades in out of a blur, a little
/// below its place and tinted, then rests in its own color. Layout never changes, so a row has its final
/// height from the first frame.
/// Nonisolated: SwiftUI may call `draw` off the main thread.
nonisolated struct WritingRenderer: TextRenderer {
    /// 0 hides everything; 1 is the resting text.
    var progress: Double
    /// Seconds the front takes to cross this text: `WritingStyle.sweep`.
    let sweep: Double
    let lead: Color
    let trail: Color
    /// Reduce Motion: no travelling front, blur, or movement; the whole text fades in where it stands.
    let isUniform: Bool

    var animatableData: Double {
        get { progress }
        set { progress = newValue }
    }

    /// Room above and below the text's own bounds for the blur around its first and last lines. None at the
    /// sides: horizontal display padding makes SwiftUI break lines as if the text were that much wider, so
    /// they overflow the frame, and the blur beside a line shows without it.
    var displayPadding: EdgeInsets {
        let reach = WritingStyle.blur * 2
        return EdgeInsets(top: reach, leading: 0, bottom: reach, trailing: 0)
    }

    func draw(layout: Text.Layout, in context: inout GraphicsContext) {
        guard !isUniform, progress < 1 else {
            var resting = context
            if isUniform {
                resting.opacity *= UnitCurve.easeOut.value(at: progress)
            }
            for line in layout {
                resting.draw(line)
            }
            return
        }
        let lead = lead.resolve(in: context.environment)
        let trail = trail.resolve(in: context.environment)
        // Lines are treated as one long strip, so the front runs off the end of a line onto the next.
        let length = max(layout.reduce(0) { $0 + $1.typographicBounds.width }, 1)
        var passed = CGFloat.zero
        var arriving: [(glyph: Text.Layout.RunSlice, phase: Double)] = []
        for line in layout {
            let bounds = line.typographicBounds.rect
            let offset = passed - bounds.minX
            passed += bounds.width
            func phase(at x: CGFloat) -> Double {
                WritingStyle.phase(progress: progress, share: (offset + x) / length, sweep: sweep)
            }
            if phase(at: bounds.maxX) >= 1 {
                context.draw(line)
            } else if phase(at: bounds.minX) > 0 {
                for run in line {
                    for slice in run {
                        let arrival = phase(at: slice.typographicBounds.rect.midX)
                        if arrival >= 1 {
                            context.draw(slice)
                        } else if arrival > 0 {
                            arriving.append((slice, arrival))
                        }
                    }
                }
            }
        }
        WritingStyle.draw(arriving, lead: lead, trail: trail, in: context) { slice, glyph in
            glyph.draw(slice, options: .disablesSubpixelQuantization)
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
        Text(text)
            .textRenderer(WritingRenderer(progress: progress, sweep: sweep, lead: .writingLead, trail: .writingTrail,
                                          isUniform: reduceMotion))
            .task {
                guard isFresh else { return }
                withAnimation(.linear(duration: sweep + WritingStyle.settle)) {
                    progress = 1
                } completion: {
                    isFresh = false
                }
            }
            .accessibilityIdentifier(isFresh ? "assistant.writing" : "assistant.generated")
    }
}

/// Shown until assistant text arrives: one line with a soft color band drifting across it.
struct GeneratingIndicator: View {
    let label: String
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        HStack(spacing: 8) {
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
    List {
        ForEach([0.15, 0.35, 0.55, 0.75, 1.0], id: \.self) { progress in
            Text(text)
                .textRenderer(WritingRenderer(progress: progress, sweep: WritingStyle.sweep(characters: text.characters.count),
                                              lead: .writingLead, trail: .writingTrail, isUniform: false))
        }
    }
}

#Preview("쓰기 · 재생") {
    @Previewable @State var isFresh = true
    @Previewable @State var run = 0
    VStack(alignment: .leading, spacing: 16) {
        GeneratingIndicator(label: "비서가 공방 상황을 살피는 중이에요")
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
