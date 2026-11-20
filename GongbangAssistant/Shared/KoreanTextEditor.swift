import SwiftUI
import UIKit

/// A text editor that wraps Korean at word boundaries ("있어요" never splits into "있어/요").
/// SwiftUI's `TextEditor` exposes no line-break strategy, so this wraps `UITextView` directly.
struct KoreanTextEditor: UIViewRepresentable {
    @Binding var text: String

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
        if view.text != text { apply(text, to: view) }
    }

    func makeCoordinator() -> Coordinator { Coordinator(text: $text) }

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

        init(text: Binding<String>) {
            self.text = text
        }

        func textViewDidChange(_ view: UITextView) {
            text.wrappedValue = view.text
        }
    }
}
