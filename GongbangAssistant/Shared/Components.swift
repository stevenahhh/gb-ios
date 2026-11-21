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
                            .foregroundStyle(Color.secondaryText)
                        Spacer(minLength: 8)
                        Text(metric.display)
                            .font(.title3.bold())
                            .monospacedDigit()
                            .contentTransition(.numericText())
                            .animation(.default, value: metric.display)
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
                            .contentTransition(.numericText())
                            .animation(.default, value: metric.display)
                        Text(metric.label)
                            .font(.subheadline)
                            .foregroundStyle(Color.secondaryText)
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
    private let isPlain: Bool

    init(_ status: Status, isPlain: Bool = false) {
        self.status = status
        self.isPlain = isPlain
    }

    var body: some View {
        HStack(spacing: 4) {
            if status.tone == .attention {
                Circle()
                    .fill(Color.pendingOrange)
                    .frame(width: 7, height: 7)
                    .accessibilityHidden(true)
            } else {
                Image(systemName: status.tone.symbol)
                    .imageScale(.small)
                    .foregroundStyle(status.tone.color)
            }
            Text(status.text)
                .foregroundStyle(.primary)
        }
        .font(isPlain ? .footnote.weight(.semibold) : .subheadline.weight(.semibold))
        .padding(.horizontal, isPlain ? 0 : 8)
        .padding(.vertical, isPlain ? 0 : 4)
        .background(isPlain ? AnyShapeStyle(.clear) : AnyShapeStyle(.fill.tertiary), in: .capsule)
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
    /// Inside the overdue group the red title already says so; rows show a gray "어제 16:00 · 포장 대기".
    var isInOverdueGroup = false
    @State private var requestedDone: Bool?
    @Environment(AppModel.self) private var app
    @Environment(\.dynamicTypeSize) private var dynamicTypeSize
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @ScaledMetric(relativeTo: .subheadline) private var timeWidth = 48
    @ScaledMetric(relativeTo: .body) private var iconSize = 36
    @ScaledMetric(relativeTo: .body) private var nodeSize = 24

    private let infoSpacing: CGFloat = 12
    private let railWidth: CGFloat = 2

    private var isDone: Bool { requestedDone ?? item.isDone ?? false }
    private var isRunning: Bool { app.isRunning(item.id) }
    /// Finished rows can always be reopened; an unfinished class waits for its start time.
    private var isLocked: Bool { !isDone && !item.canComplete }
    private var visibleTimeline: TimelinePosition? { dynamicTypeSize.isAccessibilitySize ? nil : timeline }

    var body: some View {
        // At accessibility sizes the check sits under the text, so titles get the full width and wrap at words.
        let row = dynamicTypeSize.isAccessibilitySize
            ? AnyLayout(VStackLayout(alignment: .leading, spacing: 8))
            : AnyLayout(HStackLayout(spacing: 8))
        return row {
            link
            if item.isDone != nil {
                doneButton
            }
        }
        .padding(.vertical, visibleTimeline == nil ? 0 : 10)
        .background(alignment: .leading) {
            if let visibleTimeline {
                rail(visibleTimeline)
            }
        }
        .listRowInsets(visibleTimeline == nil ? nil : EdgeInsets(top: 0, leading: 16, bottom: 0, trailing: 16))
        .swipeActions(edge: .leading, allowsFullSwipe: true) {
            if item.isDone != nil {
                Button(isDone ? "미완료" : "완료", systemImage: isDone ? "arrow.uturn.backward" : "checkmark") {
                    toggle()
                }
                .tint(.gray)
                .disabled(isRunning || isLocked)
            }
        }
        .onChange(of: item.revision) { requestedDone = nil }
    }

    @ViewBuilder
    private var link: some View {
        let content = HStack(spacing: 12) {
            info
            Spacer(minLength: 0)
            if item.isDone == nil, !isInOverdueGroup, let status = item.status {
                StatusBadge(status)
            }
        }
        .contentShape(.rect)
        if let route = item.route {
            NavigationLink(value: route) { content }
                .buttonStyle(.plain)
                .navigationLinkIndicatorVisibility(item.isDone == nil ? .automatic : .hidden)
                .accessibilityIdentifier("row.\(item.id)")
        } else {
            content
        }
    }

    private func rail(_ position: TimelinePosition) -> some View {
        VStack(spacing: 0) {
            Rectangle().fill(.separator).opacity(position.isFirst ? 0 : 1)
            Rectangle().fill(.separator).opacity(position.isLast ? 0 : 1)
        }
        .frame(width: railWidth)
        .padding(.leading, timeWidth + infoSpacing + (nodeSize - railWidth) / 2)
        .accessibilityHidden(true)
    }

    private var node: some View {
        Image(systemName: isDone ? "checkmark" : kind.symbol)
            .font(.caption2.weight(.bold))
            .foregroundStyle(.white)
            .frame(width: nodeSize, height: nodeSize)
            .background(isDone ? AnyShapeStyle(.gray) : AnyShapeStyle(kind.color), in: .circle)
            .accessibilityHidden(true)
    }

    // The mark changes at once; the server result or a failure settles it.
    private func toggle() {
        let item = item
        let target = !isDone
        // Moves like the calendar's check, so both marks flip alike.
        withAnimation(reduceMotion ? nil : .snappy(duration: 0.2)) { requestedDone = target }
        Task {
            var revision: Int?
            let saved = await app.run(id: item.id) { revision = try await RoundupAPI.setDone(item, done: target) }
            guard saved, let revision else {
                withAnimation(reduceMotion ? nil : .snappy(duration: 0.2)) { requestedDone = nil }
                return
            }
            app.showToast("‘\(item.title)’ \(target ? "완료했어요" : "완료를 취소했어요")") { [app] in
                await app.run(id: item.id) { _ = try await RoundupAPI.setDone(item, done: !target, revision: revision) }
            }
        }
    }

    private var doneButton: some View {
        Button(action: toggle) {
            Group {
                if isRunning && requestedDone == nil {
                    ProgressView()
                } else {
                    DoneMark(isDone: isDone)
                }
            }
            .frame(minWidth: 44, minHeight: 44)
            .contentShape(.rect)
        }
        .buttonStyle(.plain)
        .disabled(isRunning || isLocked)
        .opacity(isLocked ? 0.35 : 1)
        .accessibilityLabel("\(item.title) 완료 표시")
        .accessibilityValue(isDone ? "완료" : "미완료")
        .accessibilityHint(isLocked ? "수업이 시작되면 누를 수 있어요." : "")
        .accessibilityIdentifier("task.\(item.id)")
    }

    private var info: some View {
        let layout = dynamicTypeSize.isAccessibilitySize
            ? AnyLayout(VStackLayout(alignment: .leading, spacing: 4))
            : AnyLayout(HStackLayout(spacing: infoSpacing))
        return layout {
            // In the overdue group the gray meta line already carries the time, so the row shows its icon.
            if !isInOverdueGroup, let time = item.time {
                Text(time)
                    .font(.subheadline.monospacedDigit())
                    .foregroundStyle(Color.secondaryText)
                    .frame(width: visibleTimeline == nil ? nil : timeWidth, alignment: .leading)
                    .frame(minWidth: timeWidth, alignment: .leading)
            } else if visibleTimeline == nil {
                Image(systemName: kind.symbol)
                    .foregroundStyle(.primary)
                    .frame(width: iconSize, height: iconSize)
                    .background(CalendarTokens.fill, in: .rect(cornerRadius: 8, style: .continuous))
                    .accessibilityHidden(true)
            }
            if visibleTimeline != nil {
                node
            }
            VStack(alignment: .leading, spacing: 2) {
                Text(keepingWords: item.title)
                    .font(.body.weight(.medium))
                    .strikethrough(isDone)
                    .foregroundStyle(isDone ? Color.secondaryText : Color.primary)
                PhraseText(text: item.detail)
                    .font(.subheadline)
                    .foregroundStyle(Color.secondaryText)
                // Parcels always show their pickup; timed rows show theirs only once it has passed.
                if isInOverdueGroup, let date = item.due?.date {
                    Text([RelativeDayFormatter.moment(date, now: .now), item.status?.text].compactMap { $0 }
                        .joined(separator: " · "))
                        .font(.subheadline)
                        .foregroundStyle(Color.secondaryText)
                } else if let due = item.due, item.target == .shipment || due.isOverdue(at: .now) {
                    DueLabel(due: due)
                }
            }
        }
        .accessibilityElement(children: .combine)
    }
}

extension AppModel {
    /// Takes a card's next step in place. The invoice step needs its number, so it asks the caller to open the sheet.
    func takeStep(_ item: WorkItem, enterInvoice: () -> Void) {
        guard let code = item.action?.code else { return }
        guard code != .registerInvoice else { return enterInvoice() }
        Task {
            var changed: WorkItem?
            let saved = await run(id: item.id) { changed = try await RoundupAPI.perform(code, on: item) }
            if saved, let changed { showStepToast(code, title: item.title, changed: [changed]) }
        }
    }

    /// Names the finished step on one line and offers 되돌리기 for every row the server lets go back.
    func showStepToast(_ code: ActionCode, title: String, changed: [WorkItem]) {
        let message = changed.count == 1 ? "‘\(title)’ \(code.doneText)" : "\(changed.count)건 \(code.doneText)"
        guard changed.allSatisfy({ $0.undo != nil }), let first = changed.first else {
            return showToast(message)
        }
        showToast(message) { [self] in
            await run(id: first.id) {
                if changed.count == 1, let undo = first.undo {
                    try await RoundupAPI.undo(undo, revision: first.revision)
                } else {
                    try await RoundupAPI.undo(changed)
                }
            }
        }
    }
}

struct CardActionButton: View {
    let item: WorkItem
    let action: CardAction
    var isPrimary = false
    @State private var isEnteringInvoice = false
    @Environment(AppModel.self) private var app

    var body: some View {
        let isRunning = app.isRunning(item.id)
        let button = Button {
            app.takeStep(item) { isEnteringInvoice = true }
        } label: {
            BusyLabel(title: action.label, isBusy: isRunning, isProminent: isPrimary)
                .font(.subheadline.weight(.semibold))
                .frame(maxWidth: .infinity, minHeight: 30)
        }
        .controlSize(.large)
        .disabled(isRunning)
        .accessibilityIdentifier("action.\(item.id)")
        .sheet(isPresented: $isEnteringInvoice) {
            InvoiceSheet(items: [item])
        }

        if isPrimary {
            button.buttonStyle(.borderedProminent)
        } else {
            button.buttonStyle(.bordered)
        }
    }
}

/// Where a parcel stands on its fixed steps, as a native bar and "2/5단계"; finished parcels show none.
struct StepProgressLine: View {
    let progress: CardProgress
    @ScaledMetric(relativeTo: .subheadline) private var barWidth = 88

    var body: some View {
        if progress.current < progress.steps.count {
            HStack(spacing: 8) {
                ProgressView(value: Double(progress.current), total: Double(progress.steps.count))
                    .tint(.primary)
                    .frame(width: barWidth)
                Text("\(progress.current)/\(progress.steps.count)단계")
                    .font(.subheadline.monospacedDigit())
                    .foregroundStyle(Color.secondaryText)
            }
            .accessibilityElement(children: .ignore)
            .accessibilityLabel("진행 단계")
            .accessibilityValue("\(progress.steps.count)단계 중 \(progress.current)단계 완료, 다음 \(progress.steps[progress.current])")
        }
    }
}

/// A button title that is replaced by a spinner while its action runs. The button keeps its size and its name.
struct BusyLabel: View {
    let title: String
    let isBusy: Bool
    /// On a prominent button the title takes the background color.
    var isProminent = false

    var body: some View {
        ZStack {
            text
                .opacity(isBusy ? 0 : 1)
            if isBusy {
                ProgressView()
                    .transition(.opacity)
            }
        }
        .animation(.default, value: isBusy)
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(title)
        .accessibilityValue(isBusy ? "처리 중" : "")
    }

    @ViewBuilder
    private var text: some View {
        if isProminent {
            Text(title)
                .foregroundStyle(Color(.systemBackground))
        } else {
            Text(title)
        }
    }
}

struct WorkCardContent: View {
    let item: WorkItem
    var selectable = false
    @Environment(\.hidesCardStatus) private var hidesStatus
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
                if let status = item.status, !hidesStatus {
                    StatusBadge(status)
                }
            }
            ForEach(item.lines, id: \.self) { line in
                PhraseText(text: line, selectable: selectable)
                    .font(.subheadline)
                    .foregroundStyle(Color.secondaryText)
            }
            if let due = item.due {
                DueLabel(due: due)
            } else if let deadline = item.deadline {
                Label {
                    Text(keepingWords: deadline)
                        .foregroundStyle(.primary)
                } icon: {
                    Image(systemName: "clock")
                        .foregroundStyle(Color.secondaryText)
                }
                .font(.subheadline.weight(.semibold))
            }
            if let progress = item.progress {
                StepProgressLine(progress: progress)
            }
        }
        .padding(.vertical, 4)
    }
}

struct WorkCard: View {
    let item: WorkItem
    var isPrimary = false
    @State private var isEnteringInvoice = false
    @Environment(AppModel.self) private var app

    var body: some View {
        card
            // A full swipe from the leading edge takes the same next step as the button.
            .swipeActions(edge: .leading, allowsFullSwipe: true) {
                if let action = item.action, item.draft == nil, ActionCode.fulfilment.contains(action.code) {
                    Button(action.label, systemImage: "checkmark") {
                        app.takeStep(item) { isEnteringInvoice = true }
                    }
                    .tint(.gray)
                    .disabled(app.isRunning(item.id))
                    .accessibilityIdentifier("swipe.\(item.id)")
                }
            }
            .sheet(isPresented: $isEnteringInvoice) {
                InvoiceSheet(items: [item])
            }
    }

    @ViewBuilder
    private var card: some View {
        if let draft = item.draft {
            AssistantDraftRow(title: item.title, reference: draft)
        } else if let route = item.route {
            if let action = item.action {
                VStack(alignment: .leading, spacing: 8) {
                    NavigationLink(value: route) {
                        HStack(spacing: 8) {
                            WorkCardContent(item: item)
                            Image(systemName: "chevron.forward")
                                .font(.footnote.weight(.semibold))
                                .foregroundStyle(.tertiary)
                                .accessibilityHidden(true)
                        }
                        .contentShape(.rect)
                    }
                    .buttonStyle(.plain)
                    .navigationLinkIndicatorVisibility(.hidden)
                    .accessibilityIdentifier("card.\(item.id)")
                    CardActionButton(item: item, action: action, isPrimary: isPrimary)
                }
            } else {
                NavigationLink(value: route) {
                    WorkCardContent(item: item)
                }
                .accessibilityIdentifier("card.\(item.id)")
            }
        } else {
            WorkCardContent(item: item, selectable: true)
        }
    }
}

extension [WorkItem] {
    var primaryActionID: WorkItem.ID? { first { $0.action != nil && $0.draft == nil }?.id }
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

/// The completion circle: an empty ring, or the calendar's gray done node. Completion never uses green.
struct DoneMark: View {
    let isDone: Bool

    var body: some View {
        if isDone {
            Image(systemName: "checkmark")
                .font(.footnote.weight(.bold))
                .foregroundStyle(CalendarTokens.secondary)
                .frame(width: 24, height: 24)
                .background(CalendarTokens.separator, in: .circle)
        } else {
            Image(systemName: "circle")
                .font(.title2)
                .foregroundStyle(Color.secondaryText)
        }
    }
}

extension [WorkItem] {
    /// Channels are all unconnected for now; then one sentence replaces a badge on every card.
    var allChannelsUnconnected: Bool {
        count > 1 && allSatisfy { $0.status?.text == "아직 연결 안 됨" }
    }
}

struct UnconnectedChannelsNote: View {
    var body: some View {
        Text("채널은 아직 연결 전이에요. 주문과 문의는 앱에 직접 등록한 내용만 보여요.")
            .font(.subheadline)
            .foregroundStyle(Color.secondaryText)
            .textCase(nil)
    }
}
