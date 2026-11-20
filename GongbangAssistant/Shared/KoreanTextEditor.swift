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
        let view = UITextView()
        view.textContainer.lineBreakMode = .byWordWrapping
        view.font = .preferredFont(forTextStyle: .body)
        view.adjustsFontForContentSizeCategory = true
        view.backgroundColor = .clear
        view.textContainerInset = .zero
        view.textContainer.lineFragmentPadding = 0
        view.delegate = context.coordinator
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
        private var link: CADisplayLink?
        private var started = CFTimeInterval.zero
        private var sweep = 0.0
        /// Characters before this index have reached their resting color.
        private var settled = 0
        private var lead = SIMD4<Double>()
        private var trail = SIMD4<Double>()
        private var rest = SIMD4<Double>()

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

        /// Hides the text, then lets a front cross it one character at a time. Only colors change, so the
        /// layout, the caret, and the string the binding holds stay as they are.
        func reveal(in view: UITextView, isUniform: Bool) {
            let storage = view.textStorage
            guard link == nil, storage.length > 0 else { return }
            self.view = view
            sweep = isUniform ? 0 : WritingStyle.sweep(characters: storage.length)
            settled = 0
            started = CACurrentMediaTime()
            lead = Self.components(UIColor(Color.writingLead), in: view)
            trail = Self.components(UIColor(Color.writingTrail), in: view)
            rest = Self.components(.label, in: view)
            storage.addAttribute(.foregroundColor, value: UIColor.clear, range: NSRange(location: 0, length: storage.length))
            let link = CADisplayLink(target: self, selector: #selector(step))
            link.add(to: .main, forMode: .common)
            self.link = link
        }

        /// Stops the frame callback only. The display link holds this coordinator until it is invalidated.
        func cancelReveal() {
            link?.invalidate()
            link = nil
        }

        /// Ends the reveal with the text at rest, whether the front finished or the owner started typing.
        private func finishReveal() {
            guard link != nil else { return }
            cancelReveal()
            if let storage = view?.textStorage {
                storage.addAttribute(.foregroundColor, value: UIColor.label, range: NSRange(location: 0, length: storage.length))
            }
            isFresh.wrappedValue = false
        }

        @objc private func step(_ link: CADisplayLink) {
            guard let storage = view?.textStorage else { return cancelReveal() }
            let string = storage.string as NSString
            let elapsed = link.targetTimestamp - started
            let perCharacter = sweep / Double(max(string.length, 1))
            storage.beginEditing()
            var index = settled
            while index < string.length {
                let age = elapsed - Double(index) * perCharacter
                if age <= 0 { break }
                let range = string.rangeOfComposedCharacterSequence(at: index)
                storage.addAttribute(.foregroundColor, value: color(at: age / WritingStyle.settle), range: range)
                if age >= WritingStyle.settle, index == settled { settled = NSMaxRange(range) }
                index = NSMaxRange(range)
            }
            storage.endEditing()
            if settled >= string.length { finishReveal() }
        }

        /// The same steps as `WritingStyle.band`, read by how long ago the front passed the character.
        private func color(at share: Double) -> UIColor {
            let value: SIMD4<Double>
            switch share {
            case ..<WritingStyle.leadIn:
                value = SIMD4(lead.x, lead.y, lead.z, share / WritingStyle.leadIn)
            case ..<WritingStyle.leadUntil:
                value = lead
            case ..<WritingStyle.trailFrom:
                value = lead + (trail - lead) * ((share - WritingStyle.leadUntil) / (WritingStyle.trailFrom - WritingStyle.leadUntil))
            case ..<WritingStyle.trailUntil:
                value = trail
            case ..<1:
                value = trail + (rest - trail) * ((share - WritingStyle.trailUntil) / (1 - WritingStyle.trailUntil))
            default:
                return .label
            }
            return UIColor(red: value.x, green: value.y, blue: value.z, alpha: value.w)
        }

        private static func components(_ color: UIColor, in view: UITextView) -> SIMD4<Double> {
            var (red, green, blue, alpha) = (CGFloat.zero, CGFloat.zero, CGFloat.zero, CGFloat.zero)
            color.resolvedColor(with: view.traitCollection).getRed(&red, green: &green, blue: &blue, alpha: &alpha)
            return SIMD4(red, green, blue, alpha)
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
