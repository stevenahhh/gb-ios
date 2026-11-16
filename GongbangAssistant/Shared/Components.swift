import SwiftUI

enum ScreenState: String {
    case loaded
    case loading
    case empty
    case error

    static var launch: ScreenState {
        ScreenState(rawValue: UserDefaults.standard.string(forKey: "screenState") ?? "") ?? .loaded
    }
}

extension String {
    var keepingWords: String {
        var result = ""
        var previous: Character?
        for character in self {
            if let previous, !previous.isWhitespace, !character.isWhitespace {
                result.append("\u{2060}")
            }
            result.append(character)
            previous = character
        }
        return result
    }
}

extension Text {
    init(keepingWords string: String) {
        self = Text(verbatim: string.keepingWords).accessibilityLabel(string)
    }
}

struct PhraseText: View {
    let text: String
    var selectable = false
    @ScaledMetric(relativeTo: .subheadline) private var gap = 4

    private var pieces: [String] {
        guard text.contains(" · ") else {
            return text.split(separator: " ").map(String.init)
        }
        let phrases = text.components(separatedBy: " · ")
        return phrases.enumerated().map { index, phrase in
            index < phrases.count - 1 ? phrase + " ·" : phrase
        }
    }

    var body: some View {
        PhraseFlowLayout(spacing: gap, lineSpacing: 2) {
            ForEach(Array(pieces.enumerated()), id: \.offset) { _, piece in
                pieceText(piece)
            }
        }
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(text)
    }

    @ViewBuilder
    private func pieceText(_ piece: String) -> some View {
        let label = Text(verbatim: piece).fixedSize()
        if selectable {
            label.textSelection(.enabled)
        } else {
            label
        }
    }
}

struct PhraseFlowLayout: Layout {
    var spacing: CGFloat
    var lineSpacing: CGFloat

    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
        let maxWidth = proposal.width ?? .infinity
        var x: CGFloat = 0
        var y: CGFloat = 0
        var lineHeight: CGFloat = 0
        var widest: CGFloat = 0
        for subview in subviews {
            let size = subview.sizeThatFits(.unspecified)
            if x > 0, x + size.width > maxWidth {
                y += lineHeight + lineSpacing
                x = 0
                lineHeight = 0
            }
            widest = max(widest, x + size.width)
            x += size.width + spacing
            lineHeight = max(lineHeight, size.height)
        }
        return CGSize(width: min(widest, maxWidth), height: y + lineHeight)
    }

    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) {
        var x = bounds.minX
        var y = bounds.minY
        var lineHeight: CGFloat = 0
        for subview in subviews {
            let size = subview.sizeThatFits(.unspecified)
            if x > bounds.minX, x + size.width > bounds.maxX {
                y += lineHeight + lineSpacing
                x = bounds.minX
                lineHeight = 0
            }
            subview.place(at: CGPoint(x: x, y: y), proposal: ProposedViewSize(size))
            x += size.width + spacing
            lineHeight = max(lineHeight, size.height)
        }
    }
}

struct MetricStrip: View {
    let metrics: [Metric]
    @Environment(\.dynamicTypeSize) private var dynamicTypeSize

    var body: some View {
        if dynamicTypeSize.isAccessibilitySize {
            VStack(alignment: .leading, spacing: 8) {
                ForEach(metrics) { metric in
                    HStack(alignment: .firstTextBaseline) {
                        Text(metric.label)
                            .foregroundStyle(.secondary)
                        Spacer(minLength: 8)
                        Text(metric.value)
                            .font(.title3.bold())
                            .monospacedDigit()
                    }
                    .accessibilityElement(children: .combine)
                }
            }
        } else {
            HStack(spacing: 0) {
                ForEach(Array(metrics.enumerated()), id: \.element.id) { index, metric in
                    if index > 0 {
                        Divider().frame(height: 32)
                    }
                    VStack(spacing: 2) {
                        Text(metric.value)
                            .font(.title3.bold())
                            .monospacedDigit()
                        Text(metric.label)
                            .font(.subheadline)
                            .foregroundStyle(.secondary)
                    }
                    .frame(maxWidth: .infinity)
                    .accessibilityElement(children: .combine)
                }
            }
            .padding(.vertical, 4)
        }
    }
}

struct StatusBadge: View {
    let status: Status

    init(_ status: Status) {
        self.status = status
    }

    var body: some View {
        HStack(spacing: 4) {
            Image(systemName: status.tone.symbol)
                .imageScale(.small)
                .foregroundStyle(status.tone.color)
            Text(status.text)
                .foregroundStyle(.primary)
        }
        .font(.subheadline.weight(.semibold))
        .padding(.horizontal, 8)
        .padding(.vertical, 4)
        .background(.fill.tertiary, in: .capsule)
        .fixedSize()
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("상태 \(status.text)")
    }
}

struct TaskRow: View {
    let item: TaskItem
    let kind: EventKind
    @State private var isDone: Bool
    @Environment(\.dynamicTypeSize) private var dynamicTypeSize
    @ScaledMetric(relativeTo: .subheadline) private var timeWidth = 48
    @ScaledMetric(relativeTo: .body) private var iconSize = 36

    init(item: TaskItem, kind: EventKind) {
        self.item = item
        self.kind = kind
        _isDone = State(initialValue: item.isDone ?? false)
    }

    var body: some View {
        Group {
            if dynamicTypeSize.isAccessibilitySize {
                VStack(alignment: .leading, spacing: 8) {
                    HStack(alignment: .top, spacing: 12) {
                        info
                        Spacer(minLength: 8)
                        if item.isDone != nil {
                            doneButton
                        }
                    }
                    if item.isDone == nil, let status = item.status {
                        StatusBadge(status)
                    }
                }
            } else {
                HStack(spacing: 12) {
                    info
                    Spacer(minLength: 8)
                    if item.isDone != nil {
                        doneButton
                    } else if let status = item.status {
                        StatusBadge(status)
                    }
                }
            }
        }
        .swipeActions(edge: .leading, allowsFullSwipe: true) {
            if item.isDone != nil {
                Button(isDone ? "미완료" : "완료", systemImage: isDone ? "arrow.uturn.backward" : "checkmark") {
                    isDone.toggle()
                }
                .tint(.green)
            }
        }
    }

    private var doneButton: some View {
        Button {
            isDone.toggle()
        } label: {
            Image(systemName: isDone ? "checkmark.circle.fill" : "circle")
                .font(.title2)
                .foregroundStyle(isDone ? AnyShapeStyle(.green) : AnyShapeStyle(.secondary))
                .frame(minWidth: 44, minHeight: 44)
                .contentShape(.rect)
        }
        .buttonStyle(.plain)
        .accessibilityLabel("\(item.title) 완료 표시")
        .accessibilityValue(isDone ? "완료" : "미완료")
        .sensoryFeedback(.success, trigger: isDone)
    }

    private var info: some View {
        let layout = dynamicTypeSize.isAccessibilitySize
            ? AnyLayout(VStackLayout(alignment: .leading, spacing: 4))
            : AnyLayout(HStackLayout(spacing: 12))
        return layout {
            if let time = item.time {
                Text(time)
                    .font(.subheadline.monospacedDigit())
                    .foregroundStyle(.secondary)
                    .frame(minWidth: timeWidth, alignment: .leading)
            } else {
                Image(systemName: kind.symbol)
                    .foregroundStyle(kind.color)
                    .frame(width: iconSize, height: iconSize)
                    .background(kind.color.opacity(0.12), in: .rect(cornerRadius: 8))
                    .accessibilityHidden(true)
            }
            VStack(alignment: .leading, spacing: 2) {
                Text(keepingWords: item.title)
                    .font(.body.weight(.medium))
                PhraseText(text: item.detail)
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
            }
        }
        .accessibilityElement(children: .combine)
    }
}

struct WorkCard: View {
    let item: WorkItem
    var isPrimary = false
    var showsAction = true
    var selectable = true
    @State private var isCompleted = false
    @Environment(\.dynamicTypeSize) private var dynamicTypeSize

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            let header = dynamicTypeSize.isAccessibilitySize
                ? AnyLayout(VStackLayout(alignment: .leading, spacing: 4))
                : AnyLayout(HStackLayout(alignment: .firstTextBaseline))
            header {
                Text(keepingWords: item.title)
                    .font(.headline)
                if !dynamicTypeSize.isAccessibilitySize {
                    Spacer(minLength: 8)
                }
                if let status = currentStatus {
                    StatusBadge(status)
                }
            }
            ForEach(item.lines, id: \.self) { line in
                lineText(line)
            }
            if let deadline = item.deadline {
                Label {
                    Text(keepingWords: deadline)
                        .foregroundStyle(.primary)
                } icon: {
                    Image(systemName: "clock.fill")
                        .foregroundStyle(.orange)
                }
                .font(.subheadline.weight(.semibold))
            }
            if showsAction, case .perform(let label) = item.action {
                actionButton(label)
                    .padding(.top, 8)
            }
        }
        .padding(.vertical, 4)
        .sensoryFeedback(.success, trigger: isCompleted)
    }

    private var currentStatus: Status? {
        isCompleted ? Status(text: "처리 완료", tone: .done) : item.status
    }

    private func lineText(_ line: String) -> some View {
        PhraseText(text: line, selectable: selectable)
            .font(.subheadline)
            .foregroundStyle(.secondary)
    }

    @ViewBuilder
    private func actionButton(_ label: String) -> some View {
        let button = Button {
            isCompleted = true
        } label: {
            Group {
                if isCompleted {
                    Label("처리했어요", systemImage: "checkmark")
                } else if isPrimary {
                    Text(label)
                        .foregroundStyle(Color(.systemBackground))
                } else {
                    Text(label)
                }
            }
            .font(.subheadline.weight(.semibold))
            .frame(maxWidth: .infinity, minHeight: 30)
        }
        .controlSize(.large)
        .disabled(isCompleted)

        if isPrimary && !isCompleted {
            button.buttonStyle(.borderedProminent)
        } else {
            button.buttonStyle(.bordered)
        }
    }
}

struct WorkCardRow: View {
    let item: WorkItem
    var isPrimary = false

    var body: some View {
        if case .open = item.action {
            NavigationLink(value: item) {
                WorkCard(item: item, selectable: false)
            }
        } else {
            WorkCard(item: item, isPrimary: isPrimary)
        }
    }
}

struct WorkDetailView: View {
    let item: WorkItem

    var body: some View {
        List {
            Section {
                WorkCard(item: item, showsAction: false)
            }
            Section {
                Label("세부 화면은 준비 중이에요.", systemImage: "hammer")
                    .foregroundStyle(.secondary)
            }
        }
        .listStyle(.insetGrouped)
        .navigationTitle(item.title)
        .navigationBarTitleDisplayMode(.inline)
    }
}

struct AgendaRow: View {
    let item: AgendaItem
    @ScaledMetric(relativeTo: .subheadline) private var timeWidth = 48
    @Environment(\.dynamicTypeSize) private var dynamicTypeSize

    var body: some View {
        Group {
            if dynamicTypeSize.isAccessibilitySize {
                VStack(alignment: .leading, spacing: 6) {
                    time
                    titles
                    KindTag(kind: item.kind)
                }
            } else {
                HStack(spacing: 12) {
                    time
                        .frame(minWidth: timeWidth, alignment: .leading)
                    titles
                    Spacer(minLength: 8)
                    KindTag(kind: item.kind)
                }
            }
        }
        .accessibilityElement(children: .combine)
    }

    private var time: some View {
        Text(keepingWords: item.time)
            .font(.subheadline.monospacedDigit())
            .foregroundStyle(.secondary)
    }

    private var titles: some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(keepingWords: item.title)
                .font(.body.weight(.semibold))
            PhraseText(text: item.detail)
                .font(.subheadline)
                .foregroundStyle(.secondary)
        }
    }
}

struct KindTag: View {
    let kind: EventKind

    var body: some View {
        HStack(spacing: 4) {
            Image(systemName: kind.symbol)
                .foregroundStyle(kind.color)
                .accessibilityHidden(true)
            Text(kind.rawValue)
                .foregroundStyle(.primary)
        }
        .font(.subheadline.weight(.semibold))
        .padding(.horizontal, 8)
        .padding(.vertical, 4)
        .background(kind.color.opacity(0.14), in: .rect(cornerRadius: 6))
        .fixedSize()
    }
}

struct SectionHeader: View {
    let title: String
    var area: OperationArea?
    @Environment(\.dynamicTypeSize) private var dynamicTypeSize

    var body: some View {
        let layout = dynamicTypeSize.isAccessibilitySize
            ? AnyLayout(VStackLayout(alignment: .leading, spacing: 0))
            : AnyLayout(HStackLayout(alignment: .firstTextBaseline))
        layout {
            Text(keepingWords: title)
                .accessibilityAddTraits(.isHeader)
            if !dynamicTypeSize.isAccessibilitySize {
                Spacer()
            }
            if let area {
                NavigationLink("전체 보기", value: AreaRoute(area: area))
                    .font(.subheadline)
                    .textCase(nil)
                    .frame(minHeight: 44)
                    .accessibilityLabel("\(title) 전체 보기")
            }
        }
    }
}

struct AdaptivePickerStyle: ViewModifier {
    @Environment(\.dynamicTypeSize) private var dynamicTypeSize

    func body(content: Content) -> some View {
        if dynamicTypeSize.isAccessibilitySize {
            content.pickerStyle(.menu)
        } else {
            content.pickerStyle(.segmented)
        }
    }
}

extension View {
    func adaptivePickerStyle() -> some View {
        modifier(AdaptivePickerStyle())
    }
}

struct PlaceholderScreen: View {
    let title: String
    let systemImage: String

    var body: some View {
        ContentUnavailableView(title, systemImage: systemImage, description: Text("아직 준비 중인 화면이에요.\n곧 열어 드릴게요."))
            .navigationTitle(title)
            .navigationBarTitleDisplayMode(.inline)
    }
}

struct LoadErrorView: View {
    let retry: () -> Void

    var body: some View {
        ContentUnavailableView {
            Label("불러오지 못했어요", systemImage: "wifi.exclamationmark")
        } description: {
            Text("인터넷 연결을 확인하고\n다시 시도해 주세요.")
        } actions: {
            Button(action: retry) {
                Text("다시 시도")
                    .foregroundStyle(Color(.systemBackground))
            }
            .buttonStyle(.borderedProminent)
            .controlSize(.large)
        }
    }
}
