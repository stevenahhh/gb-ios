import Foundation

/// Rules for what the owner says aloud and what is read back, kept apart from the microphone and the voice.
public enum SpokenTurn {
    /// The server takes a question of up to 1,000 characters.
    private static let questionLimit = 1000
    private static let sentenceLimit = 5
    private static let spokenLimit = 300

    public static func isTooLong(_ question: String) -> Bool { question.unicodeScalars.count > questionLimit }

    /// False when two transcripts of the same words each hold a number the other lacks. Only numbers of three or
    /// more digits count, and a number one side wrote in words cannot be compared, so it does not disagree.
    public static func numbersAgree(_ first: String, _ second: String) -> Bool {
        if first.filter(\.isWholeNumber) == second.filter(\.isWholeNumber) { return true }
        let left = longNumbers(first), right = longNumbers(second)
        return left.isSubset(of: right) || right.isSubset(of: left)
    }

    private static func longNumbers(_ text: String) -> Set<String> {
        Set(text.matches(of: #/[0-9]+(?:[,.\-][0-9]+)*/#)
            .map { $0.output.filter(\.isWholeNumber) }
            .filter { $0.count >= 3 })
    }

    /// True only for a turn that says nothing but "take that back". 취소 is left out: it also means a customer's.
    public static func isUndoRequest(_ text: String) -> Bool {
        let bare = text.filter { $0.isLetter || $0.isNumber }
        return bare.wholeMatch(of: #/(?:방금|아까)?(?:한|그)?(?:거|것|일)?(?:을|를)?되돌려(?:줘|줘요|주세요)?/#) != nil
    }

    /// What is read aloud for an answer. A report of work is never shortened; `waiting` proposals are announced.
    public static func spoken(_ answer: String, reportsWork: Bool, waiting: Int) -> String {
        let body = reportsWork ? answer : shortened(answer)
        guard waiting > 0 else { return body }
        let count = waiting == 1 ? "" : "제안 \(waiting)건이 "
        let notice = "\(count)승인을 기다려요. 화면에서 승인하기를 눌러 주세요."
        return body.isEmpty ? notice : "\(body)\n\(notice)"
    }

    private static func shortened(_ text: String) -> String {
        var end = text.startIndex
        var count = 0
        text.enumerateSubstrings(in: text.startIndex..., options: .bySentences) { _, _, enclosing, stop in
            let length = text.distance(from: text.startIndex, to: enclosing.upperBound)
            if count == sentenceLimit || (count > 0 && length > spokenLimit) {
                stop = true
            } else {
                count += 1
                end = enclosing.upperBound
            }
        }
        guard end < text.endIndex else { return text }
        return text[..<end].trimmingCharacters(in: .whitespacesAndNewlines) + "\n나머지는 대화 내용에서 볼 수 있어요."
    }

    /// A masked name such as 박*은 keeps its stars in inline Markdown, where two of them would read as emphasis.
    public static func escapingMaskedNames(_ text: String) -> String {
        text.replacing(#/(^|[^가-힣*])([가-힣])(\*+)/#) { match in
            match.output.1 + match.output.2 + String(repeating: "\\*", count: match.output.3.count)
        }
    }
}

/// The newest elements of a stream, enough to cover `seconds`; older ones are dropped.
public struct RecentWindow<Element> {
    private let seconds: Double
    private var kept: [(element: Element, duration: Double)] = []

    public init(seconds: Double) { self.seconds = seconds }

    public var elements: [Element] { kept.map(\.element) }

    public mutating func append(_ element: Element, duration: Double) {
        kept.append((element, duration))
        var total = kept.reduce(0) { $0 + $1.duration }
        while let first = kept.first, total - first.duration >= seconds {
            total -= first.duration
            kept.removeFirst()
        }
    }

    public mutating func removeAll() { kept.removeAll() }
}
