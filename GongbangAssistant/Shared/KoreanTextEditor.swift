import SwiftUI
import UIKit

/// A text editor that wraps Korean at word boundaries ("있어요" never splits into "있어/요").
/// SwiftUI's `TextEditor` exposes no line-break strategy, so this wraps `UITextView` directly.
struct KoreanTextEditor: UIViewRepresentable {
    @Binding var text: String
    /// Set to true in the same update that assigns assistant-written text. The editor reveals that text once
    /// and clears the flag. Typing or tapping into the editor ends the reveal at once.
    var isFresh: Binding<Bool> = .constant(false)

    func makeUIView(context: Context) -> UITextView {
        let view = WrappingTextView()
        view.textContainer.lineBreakMode = .byWordWrapping
        view.font = .preferredFont(forTextStyle: .body)
        view.adjustsFontForContentSizeCategory = true
        view.backgroundColor = .clear
        view.textContainerInset = .zero
        view.textContainer.lineFragmentPadding = 0
        view.delegate = context.coordinator
        view.wrapDidChange = { [coordinator = context.coordinator] in coordinator.wrapDidChange() }
        view.isEditable = context.environment.isEnabled
        apply(text, to: view)
        return view
    }

    // `.disabled` reaches UIKit only through the environment, so typing stops while a screen locks the text.
    func updateUIView(_ view: UITextView, context: Context) {
        view.isEditable = context.environment.isEnabled
        if view.text != text {
            context.coordinator.cancelReveal()
            apply(text, to: view)
        }
        if isFresh.wrappedValue {
            context.coordinator.reveal(in: view, isUniform: context.environment.accessibilityReduceMotion)
        }
    }

    static func dismantleUIView(_ view: UITextView, coordinator: Coordinator) {
        coordinator.cancelReveal()
    }

    func makeCoordinator() -> Coordinator { Coordinator(text: $text, isFresh: isFresh) }

    private func apply(_ value: String, to view: UITextView) {
        let style = NSMutableParagraphStyle()
        style.lineBreakStrategy = .hangulWordPriority
        let selection = view.selectedRange
        view.attributedText = NSAttributedString(string: value, attributes: [
            .font: UIFont.preferredFont(forTextStyle: .body), .foregroundColor: UIColor.label, .paragraphStyle: style,
        ])
        view.typingAttributes = [
            .font: UIFont.preferredFont(forTextStyle: .body), .foregroundColor: UIColor.label, .paragraphStyle: style,
        ]
        view.selectedRange = NSRange(location: min(selection.location, (value as NSString).length), length: 0)
    }

    final class Coordinator: NSObject, UITextViewDelegate {
        private let text: Binding<String>
        private let isFresh: Binding<Bool>
        private weak var view: UITextView?
        /// True from the request to reveal until the text is at rest again.
        private var isRevealing = false
        private var isUniform = false
        /// Draws the reveal over the hidden text. Nil while a reveal waits for the view's first layout.
        private var overlay: UIViewController?

        init(text: Binding<String>, isFresh: Binding<Bool>) {
            self.text = text
            self.isFresh = isFresh
        }

        func textViewDidBeginEditing(_ view: UITextView) {
            finishReveal()
        }

        func textViewDidChange(_ view: UITextView) {
            finishReveal()
            text.wrappedValue = view.text
        }

        /// The overlay shows only the lines that were in view when it started, so scrolling ends the reveal.
        func scrollViewDidScroll(_ view: UIScrollView) {
            if overlay != nil {
                finishReveal()
            }
        }

        /// Hides the text and plays the writing reveal over it. Only colors change in the text view itself, so
        /// the layout, the caret, and the string the binding holds stay as they are.
        func reveal(in view: UITextView, isUniform: Bool) {
            guard !isRevealing, view.textStorage.length > 0 else { return }
            isRevealing = true
            self.view = view
            self.isUniform = isUniform
            showOverlay()
        }

        /// The view's width, and so its line wrapping, changed. A reveal that waited for the first layout
        /// starts; one already playing no longer matches the lines, so it ends with the text at rest.
        func wrapDidChange() {
            guard isRevealing else { return }
            if overlay == nil {
                showOverlay()
            } else {
                finishReveal()
            }
        }

        /// Stops a reveal without touching the text: the caller is replacing it or tearing the view down.
        func cancelReveal() {
            overlay?.view.removeFromSuperview()
            overlay = nil
            view?.clipsToBounds = true
            isRevealing = false
        }

        /// Ends the reveal with the text at rest, whether it played out or the owner started typing.
        private func finishReveal() {
            guard isRevealing else { return }
            cancelReveal()
            if let storage = view?.textStorage {
                storage.addAttribute(.foregroundColor, value: UIColor.label, range: NSRange(location: 0, length: storage.length))
            }
            isFresh.wrappedValue = false
        }

        /// Starts once the view is on screen with a width; until then `wrapDidChange` calls back here.
        private func showOverlay() {
            guard let view, view.window != nil, view.bounds.width > 0 else { return }
            guard let snapshot = WritingSnapshot(of: view) else { return finishReveal() }
            let storage = view.textStorage
            storage.addAttribute(.foregroundColor, value: UIColor.clear, range: NSRange(location: 0, length: storage.length))
            // The blur reaches past the glyphs, so the overlay is wider than the text view and the text view stops
            // clipping while it plays. The overlay clips instead: above and below it adds room only where no text
            // is scrolled out of view, because that text is in the picture too.
            let reach = WritingStyle.blur * 2
            let frame = view.bounds.inset(by: UIEdgeInsets(
                top: view.bounds.minY <= snapshot.bounds.minY ? -reach : 0, left: -reach,
                bottom: view.bounds.maxY >= snapshot.bounds.maxY ? -reach : 0, right: -reach))
            let host = UIHostingController(rootView: WritingOverlay(
                snapshot: snapshot, origin: frame.origin, sweep: isUniform ? 0 : WritingStyle.sweep(characters: storage.length),
                isUniform: isUniform, finish: { [weak self] in self?.finishReveal() }))
            host.safeAreaRegions = []
            host.view.backgroundColor = .clear
            host.view.isUserInteractionEnabled = false
            host.view.accessibilityElementsHidden = true
            host.view.frame = frame
            host.view.clipsToBounds = true
            view.clipsToBounds = false
            view.addSubview(host.view)
            overlay = host
        }
    }
}

/// A text view that says when its width, and so its line wrapping, changes while it is on screen.
private final class WrappingTextView: UITextView {
    var wrapDidChange: (() -> Void)?
    private var wrappedWidth = CGFloat.zero

    override func layoutSubviews() {
        super.layoutSubviews()
        guard window != nil, bounds.width != wrappedWidth else { return }
        wrappedWidth = bounds.width
        wrapDidChange?()
    }

    override func didMoveToWindow() {
        super.didMoveToWindow()
        setNeedsLayout()
    }
}

/// The editor's text as it is laid out: drawn once at rest, then cut into lines and characters.
/// `GraphicsContext` cannot blur a `UITextView`'s own glyphs, so the reveal draws these pieces instead.
private struct WritingSnapshot {
    /// One line or one character of the picture, and where it sits in the text view.
    struct Piece {
        let image: Image
        let rect: CGRect
    }

    struct Line {
        let whole: Piece
        /// The line's characters from the left.
        let characters: [Piece]
        /// How much of the text comes before this line when all lines are laid end to end.
        let lead: CGFloat
    }

    /// The area the lines cover in the text view. The editor has no text container inset, so it starts at zero.
    let bounds: CGRect
    let lines: [Line]
    /// The length of all lines laid end to end.
    let length: CGFloat

    init?(of view: UITextView) {
        guard let manager = view.textLayoutManager else { return nil }
        manager.ensureLayout(for: manager.documentRange)
        var fragments: [NSTextLayoutFragment] = []
        manager.enumerateTextLayoutFragments(from: manager.documentRange.location, options: .ensuresLayout) {
            fragments.append($0)
            return true
        }
        let bounds = CGRect(x: 0, y: 0, width: view.bounds.width, height: manager.usageBoundsForTextContainer.maxY)
        var picture = UIImage()
        // The label color in the text resolves against the current traits, which are not the view's by default here.
        view.traitCollection.performAsCurrent {
            let format = UIGraphicsImageRendererFormat(for: view.traitCollection)
            picture = UIGraphicsImageRenderer(bounds: bounds, format: format).image { renderer in
                for fragment in fragments {
                    fragment.draw(at: fragment.layoutFragmentFrame.origin, in: renderer.cgContext)
                }
            }
        }
        guard let pixels = picture.cgImage else { return nil }
        let scale = picture.scale
        /// Cuts whole pixels out of the picture, so neighboring pieces meet without a seam.
        func piece(_ area: CGRect) -> Piece? {
            pixels.cropping(to: area).map {
                Piece(image: Image(decorative: $0, scale: scale), rect: area.applying(CGAffineTransform(scaleX: 1 / scale, y: 1 / scale)))
            }
        }
        var lines: [Line] = []
        var lead = CGFloat.zero
        for fragment in fragments {
            let frame = fragment.layoutFragmentFrame
            for line in fragment.textLineFragments where line.characterRange.length > 0 {
                let rect = line.typographicBounds.offsetBy(dx: frame.minX, dy: frame.minY)
                let string = line.attributedString.string as NSString
                // Where each character starts, in pixels, ending with the line's trailing edge.
                var edges: [CGFloat] = []
                var index = line.characterRange.location
                while index < NSMaxRange(line.characterRange) {
                    edges.append(((rect.minX + line.locationForCharacter(at: index).x) * scale).rounded())
                    index = NSMaxRange(string.rangeOfComposedCharacterSequence(at: index))
                }
                edges.append((rect.maxX * scale).rounded())
                let top = (rect.minY * scale).rounded(), height = (rect.maxY * scale).rounded() - top
                guard let whole = piece(CGRect(x: edges[0], y: top, width: edges[edges.count - 1] - edges[0], height: height)) else { continue }
                let characters = zip(edges, edges.dropFirst()).compactMap { leading, trailing in
                    piece(CGRect(x: leading, y: top, width: trailing - leading, height: height))
                }
                lines.append(Line(whole: whole, characters: characters, lead: lead))
                lead += whole.rect.width
            }
        }
        self.bounds = bounds
        self.lines = lines
        self.length = max(lead, 1)
    }
}

/// Plays the writing reveal over an editor whose own text is hidden, then reports that it finished.
private struct WritingOverlay: View {
    let snapshot: WritingSnapshot
    /// Where this view's corner sits in the text view, which is where the snapshot's pieces are measured from.
    let origin: CGPoint
    let sweep: Double
    let isUniform: Bool
    let finish: () -> Void
    @State private var progress = 0.0

    var body: some View {
        WritingCanvas(snapshot: snapshot, origin: origin, progress: progress, sweep: sweep, isUniform: isUniform)
            .task {
                withAnimation(.linear(duration: sweep + WritingStyle.settle)) {
                    progress = 1
                } completion: {
                    finish()
                }
            }
    }
}

/// One frame of the editor's reveal: the same front, fade, blur, rise, and tint as `WritingRenderer`, drawn
/// from the snapshot one character at a time.
private struct WritingCanvas: View, Animatable {
    let snapshot: WritingSnapshot
    let origin: CGPoint
    var progress: Double
    let sweep: Double
    /// Reduce Motion: the whole text fades in where it stands.
    let isUniform: Bool

    var animatableData: Double {
        get { progress }
        set { progress = newValue }
    }

    var body: some View {
        Canvas { context, _ in
            context.translateBy(x: -origin.x, y: -origin.y)
            guard !isUniform else {
                context.opacity = UnitCurve.easeOut.value(at: progress)
                for line in snapshot.lines {
                    context.draw(line.whole.image, in: line.whole.rect)
                }
                return
            }
            var arriving: [(glyph: WritingSnapshot.Piece, phase: Double)] = []
            for line in snapshot.lines {
                let rect = line.whole.rect
                // Characters at rest are drawn together, as the line's picture clipped to where they end.
                var rested = rect.minX
                for character in line.characters {
                    let share = (line.lead + character.rect.midX - rect.minX) / snapshot.length
                    let phase = WritingStyle.phase(progress: progress, share: share, sweep: sweep)
                    guard phase > 0 else { break }
                    if phase < 1 {
                        arriving.append((character, phase))
                    } else {
                        rested = character.rect.maxX
                    }
                }
                if rested > rect.minX {
                    var resting = context
                    resting.clip(to: Path(CGRect(x: rect.minX, y: rect.minY, width: rested - rect.minX, height: rect.height)))
                    resting.draw(line.whole.image, in: rect)
                }
            }
            WritingStyle.draw(arriving, lead: Color.writingLead.resolve(in: context.environment),
                              trail: Color.writingTrail.resolve(in: context.environment), in: context) { piece, glyph in
                glyph.draw(piece.image, in: piece.rect)
            }
        }
    }
}

#Preview("편집창 · 쓰기") {
    @Previewable @State var text = "안녕하세요, 오롯 공방이에요. 토요일 2시 물레 클래스는 두 자리 남아 있어요. 예약금 2만 원을 보내 주시면 자리를 잡아 둘게요."
    @Previewable @State var isFresh = true
    VStack(alignment: .leading, spacing: 16) {
        KoreanTextEditor(text: $text, isFresh: $isFresh)
            .frame(height: 160)
        Button("다시 쓰기") {
            text += " 고마워요."
            isFresh = true
        }
    }
    .padding()
}
