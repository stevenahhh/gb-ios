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
            .foregroundStyle(.secondary)
            .frame(minWidth: timeWidth, alignment: .leading)
    }

    private var title: some View {
        Text(keepingWords: item.title)
            .font(.subheadline.weight(.semibold))
    }

    private var customer: some View {
        Text(customerText)
            .font(.subheadline)
            .foregroundStyle(.secondary)
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
    let perform: () -> Void
    var undo: (() -> Void)?

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(spacing: 10) {
                VStack(alignment: .leading, spacing: 4) {
                    Text(label)
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                    if isDone {
                        Label {
                            Text(keepingWords: doneText).foregroundStyle(.primary)
                        } icon: {
                            Image(systemName: "checkmark.circle.fill").foregroundStyle(.green)
                        }
                        .font(.subheadline.weight(.medium))
                    } else if let due {
                        DueLabel(due: due)
                    } else if let deadline {
                        Label {
                            Text(keepingWords: deadline).foregroundStyle(.primary)
                        } icon: {
                            Image(systemName: "clock.fill").foregroundStyle(.orange)
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
                    Group {
                        if isRunning {
                            ProgressView()
                        } else if isPrimary {
                            Text(actionTitle)
                                .foregroundStyle(Color(.systemBackground))
                        } else {
                            Text(actionTitle)
                        }
                    }
                    .font(.subheadline.weight(.semibold))
                    .frame(maxWidth: .infinity, minHeight: 30)
                }
                .controlSize(.large)
                .disabled(isRunning)
                .accessibilityIdentifier("step.do.\(label)")
                if isPrimary {
                    button.buttonStyle(.borderedProminent)
                } else {
                    button.buttonStyle(.bordered)
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
            Text(keepingWords: value)
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
                Text(keepingWords: detail.title).font(.headline)
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
                label: "예약금", isDone: detail.depositConfirmed, doneText: "입금을 확인했어요",
                actionTitle: detail.action?.label, deadline: detail.depositDeadline, due: detail.depositDue,
                isRunning: app.isRunning(detail.id),
                perform: { run(detail.id) { try await RoundupAPI.confirmDeposit(bookingID: detail.id, revision: detail.revision) } },
                undo: detail.undo.map { undo in
                    { run(detail.id) { try await RoundupAPI.undo(undo, revision: detail.revision) } }
                }
            )
            SessionStepRow(session: detail.session, isPrimary: detail.action == nil)
        }
    }

    private func run(_ id: String, _ operation: @escaping () async throws -> Void) {
        Task { await app.run(id: id, operation) }
    }
}

struct SessionStepRow: View {
    let session: BookingDetail.Session
    var isPrimary = true
    @Environment(AppModel.self) private var app

    var body: some View {
        ProcessStepRow(
            label: "수업", isDone: session.isDone, doneText: "수업을 완료했어요",
            actionTitle: "수업 완료로 표시", isRunning: app.isRunning(session.id), isPrimary: isPrimary,
            perform: { setDone(true) }, undo: { setDone(false) }
        )
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
            CardSection("예약 \(content.bookings.count)건") {
                if content.bookings.isEmpty {
                    Text("이 수업에는 아직 예약이 없어요.")
                        .foregroundStyle(.secondary)
                }
                ForEach(content.bookings) { item in
                    if let summary = item.booking {
                        BookingListRow(item: item, summary: summary)
                    }
                }
            }
            CardSection("처리") {
                SessionStepRow(session: BookingDetail.Session(
                    id: content.session.id, isDone: content.session.isDone, revision: content.session.revision))
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
                if item.action != nil || item.undo != nil {
                    CardSection("처리") {
                        if let undo = item.undo {
                            HStack {
                                Text("이전 단계로 돌아갈 수 있어요.")
                                    .font(.subheadline)
                                    .foregroundStyle(.secondary)
                                Spacer(minLength: 8)
                                UndoButton(label: "상태", isRunning: app.isRunning(item.id)) {
                                    Task { await app.run(id: item.id) { try await RoundupAPI.undo(undo, revision: item.revision) } }
                                }
                            }
                        }
                        if let action = item.action {
                            CardActionButton(item: item, action: action, isPrimary: true)
                        }
                    }
                }
            }
            .cardList()
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

/// Order and shipment details share one label-value template and the fulfilment steps.
struct OrderSummarySections: View {
    let item: WorkItem
    let progress: CardProgress

    /// The first card line, without the sales channel already shown above the title.
    private var headline: String? {
        guard let line = item.lines.first else { return nil }
        guard let source = item.source else { return line }
        return line.hasSuffix(" · \(source)") ? String(line.dropLast(source.count + 3)) : line
    }

    var body: some View {
        CardSection {
            VStack(alignment: .leading, spacing: 4) {
                HStack(alignment: .firstTextBaseline) {
                    if let source = item.source {
                        Text(source)
                            .font(.subheadline)
                            .foregroundStyle(.secondary)
                    }
                    Spacer(minLength: 8)
                    if let status = item.status {
                        StatusBadge(status)
                    }
                }
                Text(keepingWords: item.title)
                    .font(.title3.bold())
                if let line = headline {
                    PhraseText(text: line)
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                }
                if let due = item.due {
                    DueLabel(due: due)
                } else if let deadline = item.deadline {
                    Label {
                        Text(keepingWords: deadline).foregroundStyle(.primary)
                    } icon: {
                        Image(systemName: "clock.fill").foregroundStyle(.orange)
                    }
                    .font(.subheadline.weight(.semibold))
                }
            }
            .padding(.vertical, 4)
        }
        CardSection {
            ProgressSteps(progress: progress)
        }
        if let fields = item.fields, !fields.isEmpty {
            CardSection(item.kind == .shipment ? "배송 정보" : "주문 정보") {
                ForEach(fields, id: \.label) { DetailValueRow(label: $0.label, value: $0.value) }
            }
        }
    }
}

struct ProgressSteps: View {
    let progress: CardProgress
    @ScaledMetric(relativeTo: .body) private var marker = 22

    var body: some View {
        HStack(alignment: .top, spacing: 0) {
            ForEach(Array(progress.steps.enumerated()), id: \.offset) { index, step in
                VStack(spacing: 6) {
                    ZStack {
                        connectors(index)
                        dot(index)
                    }
                    Text(step)
                        .font(.subheadline.weight(index == progress.current ? .semibold : .regular))
                        .foregroundStyle(index <= progress.current ? .primary : .secondary)
                        .lineLimit(1)
                        .minimumScaleFactor(0.75)
                }
                .frame(maxWidth: .infinity)
            }
        }
        .padding(.vertical, 8)
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("진행 단계")
        .accessibilityValue(accessibilityValue)
    }

    private var accessibilityValue: String {
        guard progress.current < progress.steps.count else { return "모든 단계 완료" }
        let done = progress.current > 0 ? "\(progress.steps[progress.current - 1]) 완료, " : ""
        return "\(done)다음 단계 \(progress.steps[progress.current])"
    }

    private func connectors(_ index: Int) -> some View {
        HStack(spacing: marker + 8) {
            Rectangle()
                .fill(index == 0 ? Color.clear : segment(done: index <= progress.current))
            Rectangle()
                .fill(index == progress.steps.count - 1 ? Color.clear : segment(done: index < progress.current))
        }
        .frame(height: 2)
    }

    private func segment(done: Bool) -> Color {
        done ? .primary : Color.secondary.opacity(0.35)
    }

    @ViewBuilder
    private func dot(_ index: Int) -> some View {
        if index < progress.current {
            Image(systemName: "checkmark")
                .font(.caption.weight(.bold))
                .foregroundStyle(Color(.systemBackground))
                .frame(width: marker, height: marker)
                .background(.primary, in: .circle)
        } else {
            Circle()
                .strokeBorder(index == progress.current ? Color.primary : Color.secondary.opacity(0.5),
                              lineWidth: index == progress.current ? 2.5 : 1.5)
                .frame(width: marker, height: marker)
        }
    }
}
