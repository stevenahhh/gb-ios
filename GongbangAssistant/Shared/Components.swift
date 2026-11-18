import SwiftUI

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
                        Text(metric.display)
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
                        Text(metric.display)
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

struct TimelinePosition: Hashable {
    let isFirst: Bool
    let isLast: Bool

    init(index: Int, count: Int) {
        isFirst = index == 0
        isLast = index == count - 1
    }
}

struct TaskRow: View {
    let item: TaskItem
    let kind: EventKind
    var timeline: TimelinePosition?
    var route: AgendaRoute?
    @State private var requestedDone: Bool?
    @Environment(AppModel.self) private var app
    @Environment(\.dynamicTypeSize) private var dynamicTypeSize
    @ScaledMetric(relativeTo: .subheadline) private var timeWidth = 48
    @ScaledMetric(relativeTo: .body) private var iconSize = 36
    @ScaledMetric(relativeTo: .body) private var nodeSize = 24

    private let timelineSpacing: CGFloat = 10
    private let railWidth: CGFloat = 2

    private var isDone: Bool { requestedDone ?? item.isDone ?? false }
    private var isRunning: Bool { app.isRunning(item.id) }
    private var visibleTimeline: TimelinePosition? { dynamicTypeSize.isAccessibilitySize ? nil : timeline }

    var body: some View {
        destinationContent
            .swipeActions(edge: .leading, allowsFullSwipe: true) {
                if item.isDone != nil {
                    Button(isDone ? "미완료" : "완료", systemImage: isDone ? "arrow.uturn.backward" : "checkmark") {
                        toggle()
                    }
                    .tint(.green)
                    .disabled(isRunning)
                }
            }
            .listRowInsets(visibleTimeline == nil ? nil : EdgeInsets(top: 0, leading: 16, bottom: 0, trailing: 16))
            .listRowSeparator(visibleTimeline == nil ? .automatic : .hidden)
            .onChange(of: item.revision) { requestedDone = nil }
    }

    @ViewBuilder
    private var destinationContent: some View {
        if let route {
            NavigationLink(value: route) { content }
        } else {
            content
        }
    }

    @ViewBuilder
    private var content: some View {
        if let visibleTimeline {
            timelineContent(visibleTimeline)
        } else if dynamicTypeSize.isAccessibilitySize {
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
                accessory
            }
        }
    }

    @ViewBuilder
    private var accessory: some View {
        if item.isDone != nil {
            doneButton
        } else if let status = item.status {
            StatusBadge(status)
        }
    }

    private func timelineContent(_ position: TimelinePosition) -> some View {
        HStack(spacing: timelineSpacing) {
            HStack(spacing: timelineSpacing) {
                Text(item.time ?? "")
                    .font(.subheadline.monospacedDigit())
                    .foregroundStyle(.secondary)
                    .frame(width: timeWidth, alignment: .leading)
                timelineNode
                titles
            }
            .accessibilityElement(children: .combine)
            Spacer(minLength: 4)
            accessory
        }
        .padding(.vertical, 8)
        .background(alignment: .leading) {
            VStack(spacing: 0) {
                Rectangle().fill(.separator).opacity(position.isFirst ? 0 : 1)
                Rectangle().fill(.separator).opacity(position.isLast ? 0 : 1)
            }
            .frame(width: railWidth)
            .padding(.leading, timeWidth + timelineSpacing + (nodeSize - railWidth) / 2)
            .accessibilityHidden(true)
        }
    }

    private var timelineNode: some View {
        Image(systemName: isDone ? "checkmark" : kind.symbol)
            .font(.caption2.weight(.bold))
            .foregroundStyle(.white)
            .frame(width: nodeSize, height: nodeSize)
            .background(isDone ? AnyShapeStyle(.gray) : AnyShapeStyle(kind.color), in: .circle)
            .accessibilityLabel(kind.label)
    }

    private func toggle() {
        let item = item
        let target = !isDone
        requestedDone = target
        Task {
            let saved = await app.run(id: item.id) { try await RoundupAPI.setDone(item, done: target) }
            if !saved { requestedDone = nil }
        }
    }

    private var doneButton: some View {
        Button(action: toggle) {
            Image(systemName: isDone ? "checkmark.circle.fill" : "circle")
                .font(.title2)
                .foregroundStyle(isDone ? AnyShapeStyle(.green) : AnyShapeStyle(.secondary))
                .frame(minWidth: 44, minHeight: 44)
                .contentShape(.rect)
        }
        .buttonStyle(.plain)
        .disabled(isRunning)
        .accessibilityLabel("\(item.title) 완료 표시")
        .accessibilityValue(isDone ? "완료" : "미완료")
        .accessibilityIdentifier("task.\(item.id)")
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
            titles
        }
        .accessibilityElement(children: .combine)
    }

    private var titles: some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(keepingWords: item.title)
                .font(.body.weight(.medium))
                .strikethrough(isDone)
                .foregroundStyle(isDone ? .secondary : .primary)
            PhraseText(text: item.detail)
                .font(.subheadline)
                .foregroundStyle(.secondary)
        }
    }
}

struct WorkCard: View {
    private enum InputSheet: String, Identifiable {
        case invoice
        case content
        var id: Self { self }
    }

    let item: WorkItem
    var isPrimary = false
    @State private var inputSheet: InputSheet?
    @Environment(AppModel.self) private var app
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
                if let status = item.status {
                    StatusBadge(status)
                }
            }
            ForEach(item.lines, id: \.self) { line in
                PhraseText(text: line, selectable: true)
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
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
            if let action = item.action {
                actionButton(action)
                    .padding(.top, 8)
            }
        }
        .padding(.vertical, 4)
        .sheet(item: $inputSheet) { sheet in
            switch sheet {
            case .invoice: InvoiceSheet(item: item)
            case .content: ContentReviewSheet(item: item)
            }
        }
    }

    private func start(_ action: CardAction) {
        switch action.code {
        case .registerInvoice: inputSheet = .invoice
        case .reviewContent: inputSheet = .content
        case .confirmDeposit, .confirmOrder, .pack, .markDelivered, .completeTask, .acknowledgeRecommendation:
            let item = item
            Task { await app.run(id: item.id) { try await RoundupAPI.perform(action.code, on: item) } }
        }
    }

    @ViewBuilder
    private func actionButton(_ action: CardAction) -> some View {
        let isRunning = app.isRunning(item.id)
        let button = Button {
            start(action)
        } label: {
            Group {
                if isRunning {
                    ProgressView()
                } else if isPrimary {
                    Text(action.label)
                        .foregroundStyle(Color(.systemBackground))
                } else {
                    Text(action.label)
                }
            }
            .font(.subheadline.weight(.semibold))
            .frame(maxWidth: .infinity, minHeight: 30)
        }
        .controlSize(.large)
        .disabled(isRunning)
        .accessibilityIdentifier("action.\(item.id)")

        if isPrimary {
            button.buttonStyle(.borderedProminent)
        } else {
            button.buttonStyle(.bordered)
        }
    }
}

extension [WorkItem] {
    var primaryActionID: WorkItem.ID? { first { $0.action != nil }?.id }
}

struct SectionHeader: View {
    let title: String
    var area: OperationArea?
    var filter: String?
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
                NavigationLink("전체 보기", value: AreaRoute(area: area, filter: filter))
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

struct LoadErrorView: View {
    let message: String
    let retry: () -> Void

    var body: some View {
        ContentUnavailableView {
            Label("불러오지 못했어요", systemImage: "wifi.exclamationmark")
        } description: {
            Text(keepingWords: message)
        } actions: {
            Button(action: retry) {
                Text("다시 시도")
                    .foregroundStyle(Color(.systemBackground))
            }
            .buttonStyle(.borderedProminent)
            .controlSize(.large)
            .accessibilityIdentifier("screen.retry")
        }
    }
}
