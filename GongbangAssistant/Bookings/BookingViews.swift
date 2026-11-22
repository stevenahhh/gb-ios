import SwiftUI

struct BookingListRow: View {
    let item: WorkItem
    let summary: BookingSummary
    @ScaledMetric(relativeTo: .subheadline) private var timeWidth = 46

    private var customerText: String { "\(summary.customer) · \(summary.people)명" }

    var body: some View {
        NavigationLink(value: AppRoute.booking(item.id)) {
            // A phone cannot fit all four fields on one line, so the booker moves under the class.
            ViewThatFits(in: .horizontal) {
                HStack(spacing: 10) {
                    time
                    title.fixedSize()
                    customer.fixedSize()
                    Spacer(minLength: 8)
                    status
                }
                HStack(spacing: 10) {
                    time
                    VStack(alignment: .leading, spacing: 2) {
                        title
                        customer
                    }
                    Spacer(minLength: 8)
                    status
                }
            }
        }
        .accessibilityElement(children: .combine)
        .accessibilityIdentifier("booking.row.\(item.id)")
    }

    private var time: some View {
        Text(summary.time)
            .font(.subheadline.monospacedDigit())
            .foregroundStyle(Color.secondaryText)
            .frame(minWidth: timeWidth, alignment: .leading)
    }

    private var title: some View {
        Text(verbatim: item.title)
            .font(.subheadline.weight(.semibold))
    }

    private var customer: some View {
        Text(customerText)
            .font(.subheadline)
            .foregroundStyle(Color.secondaryText)
    }

    @ViewBuilder
    private var status: some View {
        if let status = item.status {
            StatusBadge(status, isPlain: true)
        }
    }
}

struct ProcessStepRow: View {
    let label: String
    let isDone: Bool
    let doneText: String
    var actionTitle: String?
    var deadline: String?
    var due: CardDue?
    var isRunning = false
    var isPrimary = true
    var isActionEnabled = true
    var actionHint: String?
    let perform: () -> Void
    var undo: (() -> Void)?

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(spacing: 10) {
                VStack(alignment: .leading, spacing: 4) {
                    Text(label)
                        .foregroundStyle(Color.secondaryText)
                        .overdueMark(for: isDone ? nil : due)
                        .font(.subheadline)
                    if isDone {
                        Label {
                            Text(verbatim: doneText).foregroundStyle(.primary)
                        } icon: {
                            Image(systemName: "checkmark.circle.fill").foregroundStyle(Color.secondaryText)
                        }
                        .font(.subheadline.weight(.medium))
                    } else if let due {
                        DueLabel(due: due)
                    } else if let deadline {
                        Label {
                            Text(verbatim: deadline).foregroundStyle(.primary)
                        } icon: {
                            Image(systemName: "clock").foregroundStyle(Color.secondaryText)
                        }
                        .font(.subheadline.weight(.semibold))
                    }
                }
                Spacer(minLength: 8)
                if isDone, let undo {
                    UndoButton(label: label, isRunning: isRunning, action: undo)
                }
            }
            if !isDone, let actionTitle {
                let button = Button(action: perform) {
                    BusyLabel(title: actionTitle, isBusy: isRunning, isProminent: isPrimary)
                        .font(.subheadline.weight(.semibold))
                    .frame(maxWidth: .infinity, minHeight: 30)
                }
                .controlSize(.large)
                .disabled(isRunning || !isActionEnabled)
                .accessibilityIdentifier("step.do.\(label)")
                if isPrimary && isActionEnabled {
                    button.buttonStyle(.borderedProminent)
                } else {
                    button.buttonStyle(.bordered)
                }
                if let actionHint, !isActionEnabled {
                    Text(actionHint)
                        .font(.subheadline)
                        .foregroundStyle(Color.secondaryText)
                }
            }
        }
        .padding(.vertical, 4)
    }
}

struct UndoButton: View {
    let label: String
    var isRunning = false
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            Label("되돌리기", systemImage: "arrow.uturn.backward")
                .font(.subheadline.weight(.semibold))
        }
        .buttonStyle(.bordered)
        .disabled(isRunning)
        .accessibilityLabel("\(label) 되돌리기")
        .accessibilityIdentifier("step.undo.\(label)")
    }
}

struct DetailValueRow: View {
    let label: String
    let value: String

    var body: some View {
        LabeledContent(label) {
            Text(verbatim: value)
                .multilineTextAlignment(.trailing)
                .textSelection(.enabled)
        }
    }
}

struct BookingDetailView: View {
    let id: String
    @State private var loader = Loader<BookingDetail>()
    @Environment(AppModel.self) private var app

    var body: some View {
        LoadableContent(loader: loader, retry: load) { detail in
            List { sections(detail) }
                .cardList()
                .contentMargins(.bottom, 96, for: .scrollContent)
                .refreshable { await load() }
        }
        .navigationTitle("예약 상세")
        .navigationBarTitleDisplayMode(.inline)
        .task(id: app.dataVersion) { await load() }
    }

    private func load() async {
        let id = id
        await loader.load { try await RoundupAPI.booking(id: id) }
    }

    @ViewBuilder
    private func sections(_ detail: BookingDetail) -> some View {
        CardSection("예약 정보") {
            HStack(alignment: .firstTextBaseline) {
                Text(verbatim: detail.title).font(.headline)
                Spacer(minLength: 8)
                StatusBadge(detail.status)
            }
            DetailValueRow(label: "일시", value: detail.schedule)
            DetailValueRow(label: "예약자", value: detail.customer)
            DetailValueRow(label: "인원", value: "\(detail.people)명")
            DetailValueRow(label: "수업 시간", value: "\(detail.minutes)분")
            DetailValueRow(label: "예약금", value: detail.depositDisplay)
            DetailValueRow(label: "예약 경로", value: detail.source)
            if let seatNote = detail.seatNote {
                DetailValueRow(label: "자리", value: seatNote)
            }
        }
        CardSection("처리") {
            ProcessStepRow(
                label: "예약금", isDone: detail.depositConfirmed, doneText: "입금 확인 완료",
                actionTitle: detail.action?.label, deadline: detail.depositDeadline, due: detail.depositDue,
                isRunning: app.isRunning(detail.id),
                perform: { run(detail.id) { try await RoundupAPI.confirmDeposit(bookingID: detail.id, revision: detail.revision) } },
                undo: detail.undo.map { undo in
                    { run(detail.id) { try await RoundupAPI.undo(undo, revision: detail.revision) } }
                }
            )
            SessionStepRow(session: detail.session, isPrimary: detail.action == nil,
                           depositPending: !detail.depositConfirmed)
        }
    }

    private func run(_ id: String, _ operation: @escaping () async throws -> Void) {
        Task { await app.run(id: id, operation) }
    }
}

struct SessionStepRow: View {
    let session: BookingDetail.Session
    var isPrimary = true
    /// When the deposit is still unpaid, finishing the class asks first.
    var depositPending = false
    @State private var isConfirming = false
    @Environment(AppModel.self) private var app

    var body: some View {
        ProcessStepRow(
            label: "수업", isDone: session.isDone, doneText: "수업을 마쳤어요",
            actionTitle: "수업 마침으로 바꾸기", isRunning: app.isRunning(session.id), isPrimary: isPrimary,
            isActionEnabled: session.hasStarted, actionHint: "시작 시각이 돼야 버튼이 켜져요.",
            perform: { if depositPending { isConfirming = true } else { setDone(true) } },
            undo: { setDone(false) }
        )
        .confirmationDialog("아직 예약금 입금을 확인하지 않으셨어요", isPresented: $isConfirming, titleVisibility: .visible) {
            Button("그래도 수업 마치기") { setDone(true) }
            Button("입금부터 확인하기", role: .cancel) {}
        } message: {
            Text("바로 위 입금 확인 버튼으로 예약금이 들어왔는지 먼저 살펴보세요.")
        }
    }

    private func setDone(_ done: Bool) {
        let session = session
        Task {
            await app.run(id: session.id) {
                try await RoundupAPI.setSessionDone(id: session.id, done: done, revision: session.revision)
            }
        }
    }
}

/// A class row opens its booking directly, or lists the bookings when several share the class.
struct ClassSessionView: View {
    private struct Content {
        let session: ClassSessionDetail
        let bookings: [WorkItem]
    }

    let id: String
    @State private var loader = Loader<Content>()
    @Environment(AppModel.self) private var app

    var body: some View {
        LoadableContent(loader: loader, retry: load) { content in
            if content.session.bookingIds.count == 1, let bookingID = content.session.bookingIds.first {
                BookingDetailView(id: bookingID)
            } else {
                list(content)
                    .navigationTitle(content.session.title)
                    .navigationBarTitleDisplayMode(.inline)
            }
        }
        .task(id: app.dataVersion) { await load() }
    }

    private func load() async {
        let id = id
        await loader.load {
            async let session = RoundupAPI.classSession(id: id)
            async let page = RoundupAPI.bookings(sessionID: id)
            return try await Content(session: session, bookings: page.items)
        }
    }

    private func list(_ content: Content) -> some View {
        List {
            CardSection("수업 정보") {
                DetailValueRow(label: "일시", value: content.session.schedule)
            }
            CardSection("예약 \(content.bookings.count)개") {
                if content.bookings.isEmpty {
                    Text("이 수업을 예약한 손님은 아직 없어요.")
                        .foregroundStyle(Color.secondaryText)
                }
                ForEach(content.bookings) { item in
                    if let summary = item.booking {
                        BookingListRow(item: item, summary: summary)
                    }
                }
            }
            CardSection("처리") {
                SessionStepRow(session: BookingDetail.Session(
                    id: content.session.id, isDone: content.session.isDone, revision: content.session.revision,
                    startsAt: content.session.startsAt))
            }
        }
        .cardList(separators: .hidden)
        .refreshable { await load() }
    }
}

struct WorkDetailView: View {
    let kind: CardKind
    let id: String
    @State private var loader = Loader<WorkItem>()
    @Environment(AppModel.self) private var app

    var body: some View {
        LoadableContent(loader: loader, retry: load) { item in
            List {
                if let progress = item.progress {
                    OrderSummarySections(item: item, progress: progress)
                } else {
                    CardSection("정보") {
                        WorkCardContent(item: item, selectable: true)
                    }
                }
                if kind == .task, item.action != nil, let due = item.due?.date {
                    TaskScheduleSection(item: item, due: due)
                }
                // A fulfilment detail keeps its step controls under the steps; any other detail gives them a card.
                if item.progress == nil, item.action != nil || item.stepBack != nil {
                    CardSection("처리") {
                        CardActions(item: item, isPrimary: true)
                    }
                }
            }
            .cardList(separators: .hidden)
            // Keeps the last button clear of the assistant bar.
            .contentMargins(.bottom, 96, for: .scrollContent)
            .refreshable { await load() }
            .navigationTitle(item.progress == nil ? item.title : kind == .shipment ? "배송 상세" : "주문 상세")
        }
        .navigationBarTitleDisplayMode(.inline)
        .task(id: app.dataVersion) { await load() }
    }

    private func load() async {
        let (kind, id) = (kind, id)
        await loader.load { try await RoundupAPI.card(kind: kind, id: id) }
    }
}

/// Order and shipment details open with one centered card: what was ordered, where it stands on the fulfilment
/// steps, and the controls that move it. The label-value rows follow.
struct OrderSummarySections: View {
    let item: WorkItem
    let progress: CardProgress

    var body: some View {
        CardSection {
            VStack(spacing: 20) {
                VStack(spacing: 4) {
                    Text(verbatim: item.title)
                        .multilineTextAlignment(.center)
                        .overdueMark(for: item.due)
                        .font(.title3.bold())
                    if let line = item.lines.first {
                        PhraseText(text: line, selectable: true, alignment: .center)
                            .font(.subheadline)
                            .foregroundStyle(Color.secondaryText)
                    }
                    if let due = item.due {
                        DueLabel(due: due)
                    } else if let deadline = item.deadline {
                        Label {
                            Text(verbatim: deadline).foregroundStyle(.primary)
                        } icon: {
                            Image(systemName: "clock").foregroundStyle(Color.secondaryText)
                        }
                        .font(.subheadline.weight(.semibold))
                    }
                }
                VStack(spacing: 10) {
                    if let status = item.status {
                        StatusBadge(status)
                    }
                    ProgressSteps(progress: progress)
                }
                if item.action != nil || item.stepBack != nil {
                    CardActions(item: item, isPrimary: true)
                }
            }
            .frame(maxWidth: .infinity)
            .padding(.vertical, 12)
        }
        if let fields = item.fields, !fields.isEmpty {
            CardSection(item.kind == .shipment ? "배송 정보" : "주문 정보") {
                ForEach(fields, id: \.label) { DetailValueRow(label: $0.label, value: $0.value) }
            }
        }
    }
}

/// The fulfilment steps as a track. A finished step fills its node and draws a check into it, and the line to the
/// next node fills behind it. A step taken back plays the same marks in reverse: the check retracts and the node
/// empties. Under Reduce Motion the marks only cross-fade.
struct ProgressSteps: View {
    let progress: CardProgress
    @ScaledMetric(relativeTo: .body) private var marker = 22
    @Environment(\.dynamicTypeSize) private var dynamicTypeSize

    /// Clear space between a node and the line that reaches it.
    private let gap: CGFloat = 4

    var body: some View {
        // Five labels cannot share a row at accessibility sizes, so the track turns and reads top to bottom.
        let isStacked = dynamicTypeSize.isAccessibilitySize
        let track = isStacked
            ? AnyLayout(VStackLayout(alignment: .leading, spacing: 0))
            : AnyLayout(HStackLayout(alignment: .top, spacing: 0))
        let cell = isStacked ? AnyLayout(HStackLayout(spacing: 12)) : AnyLayout(VStackLayout(spacing: 6))
        track {
            ForEach(Array(progress.steps.enumerated()), id: \.offset) { index, step in
                cell {
                    StepNode(isDone: index < progress.current, isCurrent: index == progress.current, size: marker)
                    Text(step)
                        .font(.subheadline.weight(index == progress.current ? .semibold : .regular))
                        .foregroundStyle(index <= progress.current ? Color.primary : Color.secondaryText)
                        .lineLimit(1)
                        .minimumScaleFactor(0.75)
                        // In a row the labels stop growing at xLarge, so long and short names keep one size.
                        .dynamicTypeSize(DynamicTypeSize.xSmall...(isStacked ? .accessibility5 : .xLarge))
                }
                .frame(maxWidth: .infinity, alignment: isStacked ? .leading : .top)
                .frame(height: isStacked ? marker + 20 : nil)
            }
        }
        .background { lines(isStacked: isStacked) }
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("어디까지 왔나")
        .accessibilityValue(accessibilityValue)
    }

    private var accessibilityValue: String {
        guard progress.current < progress.steps.count else { return "모든 단계 완료" }
        let done = progress.current > 0 ? "\(progress.steps[progress.current - 1]) 완료, " : ""
        return "\(done)다음 단계 \(progress.steps[progress.current])"
    }

    /// One line per pair of neighbouring nodes, centered on the border between their cells.
    private func lines(isStacked: Bool) -> some View {
        GeometryReader { proxy in
            let count = progress.steps.count
            let cell = (isStacked ? proxy.size.height : proxy.size.width) / CGFloat(max(count, 1))
            let length = max(0, cell - marker - gap * 2)
            ForEach(0..<max(count - 1, 0), id: \.self) { index in
                let border = cell * CGFloat(index + 1)
                StepLine(isFilled: index < progress.current, axis: isStacked ? .vertical : .horizontal)
                    .frame(width: isStacked ? 2 : length, height: isStacked ? length : 2)
                    .position(x: isStacked ? marker / 2 : border, y: isStacked ? border : marker / 2)
            }
        }
        .accessibilityHidden(true)
    }
}

/// When each mark of a step moves. Going forward the node fills, its check draws, the line runs on, and the next
/// node wakes; going back the same marks leave in the opposite order.
private enum StepMotion {
    static let crossFade = Animation.easeInOut(duration: 0.25)

    static func fill(_ isDone: Bool) -> Animation {
        isDone ? .spring(duration: 0.4, bounce: 0.4) : .easeIn(duration: 0.2).delay(0.3)
    }

    static func check(_ isDone: Bool) -> Animation {
        isDone ? .easeOut(duration: 0.28).delay(0.16) : .easeIn(duration: 0.18).delay(0.12)
    }

    static func line(_ isFilled: Bool) -> Animation {
        isFilled ? .easeInOut(duration: 0.32).delay(0.24) : .easeInOut(duration: 0.24).delay(0.04)
    }

    static func ring(_ isReached: Bool) -> Animation {
        isReached ? .easeOut(duration: 0.25).delay(0.5) : .easeOut(duration: 0.15)
    }
}

/// One step's mark: a thin ring while it waits, a heavy ring when it is next, and a filled disc with a check once
/// it is done.
private struct StepNode: View {
    let isDone: Bool
    let isCurrent: Bool
    let size: CGFloat
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        let isReached = isDone || isCurrent
        ZStack {
            Circle()
                .strokeBorder(isReached ? Color.primary : Color.secondary.opacity(0.5), lineWidth: isReached ? 2.5 : 1.5)
                .animation(reduceMotion ? StepMotion.crossFade : StepMotion.ring(isReached), value: isReached)
            // With motion the disc grows from the center and the check is drawn along its stroke; without it both fade.
            Circle()
                .scale(isDone || reduceMotion ? 1 : 0)
                .fill(.primary)
                .opacity(isDone || !reduceMotion ? 1 : 0)
                .animation(reduceMotion ? StepMotion.crossFade : StepMotion.fill(isDone), value: isDone)
            StepCheck()
                .trim(from: 0, to: isDone || reduceMotion ? 1 : 0)
                .stroke(Color(.systemBackground), style: StrokeStyle(lineWidth: size / 9, lineCap: .round, lineJoin: .round))
                .opacity(isDone || !reduceMotion ? 1 : 0)
                .animation(reduceMotion ? StepMotion.crossFade : StepMotion.check(isDone), value: isDone)
        }
        .frame(width: size, height: size)
    }
}

/// The check as one stroke that starts at its short leg, so a trim draws it in and takes it back.
nonisolated private struct StepCheck: Shape {
    func path(in rect: CGRect) -> Path {
        var path = Path()
        path.move(to: CGPoint(x: rect.minX + rect.width * 0.29, y: rect.minY + rect.height * 0.53))
        path.addLine(to: CGPoint(x: rect.minX + rect.width * 0.44, y: rect.minY + rect.height * 0.67))
        path.addLine(to: CGPoint(x: rect.minX + rect.width * 0.71, y: rect.minY + rect.height * 0.36))
        return path
    }
}

/// The line between two nodes. It fills from the earlier node and empties back toward it.
private struct StepLine: View {
    let isFilled: Bool
    let axis: Axis
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        let isDrawn = isFilled || reduceMotion
        ZStack {
            Rectangle()
                .fill(Color.secondary.opacity(0.35))
            Rectangle()
                .scale(x: axis == .horizontal && !isDrawn ? 0 : 1, y: axis == .vertical && !isDrawn ? 0 : 1,
                       anchor: axis == .horizontal ? .leading : .top)
                .fill(.primary)
                .opacity(isFilled || !reduceMotion ? 1 : 0)
        }
        .clipShape(.capsule)
        .animation(reduceMotion ? StepMotion.crossFade : StepMotion.line(isFilled), value: isFilled)
    }
}

/// Lets the owner fix a task's date and time after moving it; 종일 stores the 23:59:59 marker.
struct TaskScheduleSection: View {
    let item: WorkItem
    let due: Date
    @State private var date: Date
    @State private var isAllDay: Bool
    @Environment(AppModel.self) private var app

    init(item: WorkItem, due: Date) {
        self.item = item
        self.due = due
        _date = State(initialValue: due)
        let parts = Calendar.workshop.dateComponents([.hour, .minute, .second], from: due)
        _isAllDay = State(initialValue: parts.hour == 23 && parts.minute == 59 && parts.second == 59)
    }

    private var target: Date {
        guard isAllDay else { return date }
        return Calendar.workshop.date(bySettingHour: 23, minute: 59, second: 59, of: date) ?? date
    }

    var body: some View {
        CardSection("날짜와 시각") {
            DatePicker("날짜", selection: $date, displayedComponents: .date)
            Toggle("종일", isOn: $isAllDay)
            if !isAllDay {
                DatePicker("시각", selection: $date, displayedComponents: .hourAndMinute)
            }
            Button {
                let (item, target) = (item, target)
                Task {
                    await app.run(id: item.id) {
                        _ = try await RoundupAPI.move(.task(id: item.id, revision: item.revision), to: target)
                    }
                }
            } label: {
                BusyLabel(title: "저장", isBusy: app.isRunning(item.id))
            }
            .disabled(target == due || app.isRunning(item.id))
            .accessibilityIdentifier("task.schedule.save")
        }
        .environment(\.timeZone, Calendar.workshop.timeZone)
    }
}
