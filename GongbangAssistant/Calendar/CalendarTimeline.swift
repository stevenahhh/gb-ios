import SwiftUI

enum CalendarEventKind: Hashable {
    case reservation, delivery, task

    var label: String {
        switch self {
        case .reservation: "예약"
        case .delivery: "배송"
        case .task: "할 일"
        }
    }

    /// Same start time sorts reservation, then delivery, then task.
    fileprivate var order: Int {
        switch self {
        case .reservation: 0
        case .delivery: 1
        case .task: 2
        }
    }
}

enum CalendarEventState: Hashable {
    /// `missed` is an unfinished task whose time has passed; it is the only state drawn in red.
    case done, next, upcoming, missed
}

/// A row the owner made or owns, so the owner can check it off.
enum OwnerItem: Hashable {
    case task(id: String, revision: Int)
    case event(id: String, revision: Int)

    func with(revision: Int) -> OwnerItem {
        switch self {
        case .task(let id, _): .task(id: id, revision: revision)
        case .event(let id, _): .event(id: id, revision: revision)
        }
    }
}

enum TimelineDestination: Hashable {
    case app(AppRoute)
    case area(AreaRoute)
}

/// One timeline row, derived for display only; orders and all-day rows never become entries.
struct TimelineEntry: Identifiable, Hashable {
    let id: String
    let kind: CalendarEventKind
    let start: Int
    let minutes: Int?
    let title: String
    let subject: String
    let isDone: Bool
    /// Whether the server states completion; parcels waiting for pickup say `false` explicitly.
    let reportsDone: Bool
    let destination: TimelineDestination?
    let ownerItem: OwnerItem?
    /// A task or owner entry with no time of day; it leads the timeline and never ends by the clock.
    let isAllDay: Bool

    var end: Int { start + (minutes ?? 0) }

    init?(_ item: AgendaItem) {
        let isAllDay = item.time == "종일"
        guard let start = isAllDay ? 0 : Self.minutes(of: item.time) else { return nil }
        self.isAllDay = isAllDay
        let parts = item.id.split(separator: ":", maxSplits: 1).map(String.init)
        let prefix = parts.first ?? ""
        switch prefix {
        case "session": kind = .reservation
        case "shipment": kind = .delivery
        case "task": kind = .task
        default:
            switch item.kind {
            case .booking: kind = .reservation
            case .delivery: kind = .delivery
            case .order, .todo: kind = .task
            }
        }
        id = item.id
        self.start = start
        minutes = item.minutes.flatMap { $0 > 0 ? $0 : nil }
        title = item.title
        subject = item.subject ?? item.detail
        isDone = item.isDone ?? false
        reportsDone = item.isDone != nil
        destination = item.route.map(TimelineDestination.app)
        switch (prefix, item.revision) {
        case ("task", let revision?) where parts.count == 2: ownerItem = .task(id: parts[1], revision: revision)
        case ("event", let revision?) where parts.count == 2: ownerItem = .event(id: parts[1], revision: revision)
        default: ownerItem = nil
        }
    }

    fileprivate init(pickups: [AgendaItem], start: Int) {
        id = "pickup.\(start)"
        kind = .delivery
        self.start = start
        minutes = nil
        title = "택배 수거 \(pickups.count)건"
        let names = pickups.prefix(2).map(\.title).joined(separator: " · ")
        subject = pickups.count > 2 ? "\(names) 외 \(pickups.count - 2)건" : names
        isDone = pickups.allSatisfy { $0.isDone == true }
        reportsDone = pickups.allSatisfy { $0.isDone != nil }
        destination = .area(AreaRoute(area: .deliveries, filter: "scheduled"))
        ownerItem = nil
        isAllDay = false
    }

    static func minutes(of time: String) -> Int? {
        let parts = time.split(separator: ":").compactMap { Int($0) }
        guard parts.count == 2 else { return nil }
        return parts[0] * 60 + parts[1]
    }
}

/// A day's rows sorted for the timeline, with orders and all-day rows set aside for the pinned box.
struct DaySchedule {
    let allDay: [AgendaItem]
    let orders: [AgendaItem]
    let entries: [TimelineEntry]

    init(items: [AgendaItem]) {
        // Arrivals and other all-day facts go to the pinned box; all-day tasks stay in the timeline.
        let ownerAllDay = { (item: AgendaItem) in item.id.hasPrefix("task:") || item.id.hasPrefix("event:") }
        allDay = items.filter { $0.time == "종일" && !ownerAllDay($0) }
        let timed = items.filter { $0.time != "종일" || ownerAllDay($0) }
        orders = timed.filter { $0.id.hasPrefix("order:") }
        let rest = timed.filter { !$0.id.hasPrefix("order:") }
        var entries: [TimelineEntry] = []
        var grouped: Set<String> = []
        for item in rest {
            let pickups = Self.isPickup(item) ? rest.filter { Self.isPickup($0) && $0.time == item.time } : []
            if pickups.count > 1 {
                if grouped.insert(item.time).inserted, let start = TimelineEntry.minutes(of: item.time) {
                    entries.append(TimelineEntry(pickups: pickups, start: start))
                }
            } else if let entry = TimelineEntry(item) {
                entries.append(entry)
            }
        }
        self.entries = entries.sorted { ($0.start, $0.kind.order) < ($1.start, $1.kind.order) }
    }

    private static func isPickup(_ item: AgendaItem) -> Bool {
        item.id.hasPrefix("shipment:") && item.detail.hasSuffix("택배 수거")
    }
}

enum DayRelation {
    case past, today, future
}

/// Tasks end only when checked and are `missed` once their time passes; parcels the server marks
/// unsent stay open and show 기한 지남. Only today has a next row and a time line.
struct TimelinePlan {
    struct Row: Identifiable {
        let entry: TimelineEntry
        let state: CalendarEventState
        /// A parcel past its pickup that has not been sent.
        let isOverdue: Bool
        var id: String { entry.id }
    }

    let rows: [Row]
    let nowIndex: Int?

    init(entries: [TimelineEntry], relation: DayRelation, now: Int) {
        var rows = entries.map { entry -> Row in
            let hasPassed = relation == .past || (relation == .today && !entry.isAllDay && entry.start < now)
            switch entry.kind {
            case .task:
                return Row(entry: entry, state: entry.isDone ? .done : hasPassed ? .missed : .upcoming, isOverdue: false)
            case .delivery where entry.reportsDone:
                return Row(entry: entry, state: entry.isDone ? .done : .upcoming,
                           isOverdue: !entry.isDone && hasPassed)
            case .reservation, .delivery:
                let ended: Bool = switch relation {
                case .past: true
                case .future: false
                case .today: entry.end <= now && entry.start < now
                }
                return Row(entry: entry, state: entry.isDone || ended ? .done : .upcoming, isOverdue: false)
            }
        }
        guard relation == .today else {
            self.rows = rows
            nowIndex = nil
            return
        }
        let next = rows.firstIndex { $0.state == .upcoming && !$0.isOverdue && !$0.entry.isAllDay }
        if let next {
            rows[next] = Row(entry: rows[next].entry, state: .next, isOverdue: false)
        }
        self.rows = rows
        // The line sits between rows that have started (including one in progress) and rows still ahead.
        nowIndex = rows.firstIndex { !$0.entry.isAllDay && $0.entry.start > now } ?? rows.count
    }
}

enum TimelineText {
    static func clock(_ minutes: Int) -> String {
        String(format: "%02d:%02d", minutes / 60 % 24, minutes % 60)
    }

    static func range(_ entry: TimelineEntry) -> String? {
        guard entry.minutes != nil else { return nil }
        if entry.end >= 24 * 60 {
            return "\(clock(entry.start)) ~ 다음날 \(clock(entry.end))"
        }
        return "\(clock(entry.start))–\(clock(entry.end))"
    }

    static func duration(_ minutes: Int) -> String {
        guard minutes >= 60 else { return "\(minutes)분" }
        let rest = minutes % 60
        return rest == 0 ? "\(minutes / 60)시간" : "\(minutes / 60)시간 \(rest)분"
    }

    static func spoken(_ minutes: Int) -> String {
        let hour = minutes / 60 % 24
        let period = hour < 12 ? "오전" : "오후"
        let twelve = hour % 12 == 0 ? 12 : hour % 12
        let minute = minutes % 60
        return minute == 0 ? "\(period) \(twelve)시" : "\(period) \(twelve)시 \(minute)분"
    }

    /// Kind, subject, and range; the status word is added by the row so 지남 can be red.
    static func meta(_ row: TimelinePlan.Row) -> String {
        var parts = [row.entry.kind.label]
        if !row.entry.subject.isEmpty { parts.append(row.entry.subject) }
        if let range = range(row.entry) { parts.append(range) }
        if row.state == .done { parts.append(row.entry.kind == .task ? "완료" : "끝남") }
        return parts.joined(separator: " · ")
    }

    /// Red status words: 지남 for a missed task, 기한 지남 for an unsent parcel.
    static func overdueWord(_ row: TimelinePlan.Row) -> String? {
        if row.state == .missed { return "지남" }
        return row.isOverdue ? "기한 지남" : nil
    }

    /// 진행 중 · N분 남음, N분 후, 1시간 20분 후, then a clock time beyond two hours.
    static func next(_ entry: TimelineEntry, now: Int) -> String {
        if entry.start <= now, entry.minutes != nil {
            return "진행 중 · \(max(entry.end - now, 1))분 남음"
        }
        let wait = entry.start - now
        switch wait {
        case ...0: return "지금 시작"
        case 1..<60: return "\(wait)분 후 시작"
        case 60...120: return "\(duration(wait)) 후 시작"
        default: return "\(twelveHour(entry.start)) 시작"
        }
    }

    /// "오전 9:00"
    static func twelveHour(_ minutes: Int) -> String {
        let hour = minutes / 60 % 24
        return "\(hour < 12 ? "오전" : "오후") \(hour % 12 == 0 ? 12 : hour % 12):\(String(format: "%02d", minutes % 60))"
    }
}

// MARK: - Views

struct DaySection: View {
    let date: Date
    let day: CalendarDay?
    /// Parcels whose pickup was on an earlier day; shown only on today, never carried into past days.
    let overdueShipments: [AgendaItem]
    let now: Date
    let add: () -> Void
    let check: (TimelineEntry, Bool) async -> Bool

    private var calendar: Calendar { .workshop }

    private var relation: DayRelation {
        let day = calendar.startOfDay(for: date), today = calendar.startOfDay(for: now)
        return day < today ? .past : day > today ? .future : .today
    }

    private var nowMinutes: Int {
        let parts = calendar.dateComponents([.hour, .minute], from: now)
        return (parts.hour ?? 0) * 60 + (parts.minute ?? 0)
    }

    var body: some View {
        let schedule = DaySchedule(items: day?.items ?? [])
        VStack(alignment: .leading, spacing: 0) {
            HStack(alignment: .firstTextBaseline) {
                Text(Self.title(date))
                    .font(.title2.bold())
                    .foregroundStyle(CalendarTokens.label)
                    .accessibilityAddTraits(.isHeader)
                Spacer(minLength: 8)
                Text(relation == .today ? "오늘" : "일정 \(day?.items.count ?? 0)건")
                    .font(.subheadline)
                    .foregroundStyle(CalendarTokens.secondary)
            }
            let overdue = relation == .today ? overdueShipments : []
            let hasPinned = !(schedule.allDay.isEmpty && schedule.orders.isEmpty && overdue.isEmpty)
            if hasPinned {
                PinnedSummaryCard(date: date, overdue: overdue, allDay: schedule.allDay, orders: schedule.orders)
                    .padding(.top, 14)
            }
            if schedule.entries.isEmpty {
                if hasPinned {
                    Rectangle().fill(CalendarTokens.separator).frame(height: 1).padding(.top, 20)
                }
                emptyTimeline(hasPinned ? "시간이 정해진 일정이 없어요" : "일정이 없어요")
            } else {
                TimelineList(plan: TimelinePlan(entries: schedule.entries, relation: relation, now: nowMinutes),
                             now: nowMinutes, check: check)
                    .padding(.top, hasPinned ? 20 : 14)
                TimelineLegend()
                    .padding(.top, 8)
            }
        }
    }

    private func emptyTimeline(_ message: String) -> some View {
        VStack(spacing: 10) {
            Image(systemName: "clock")
                .font(.system(size: 28))
                .foregroundStyle(CalendarTokens.tertiary)
                .accessibilityHidden(true)
            Text(message)
                .font(.callout)
                .foregroundStyle(CalendarTokens.secondary)
                .multilineTextAlignment(.center)
            Button("일정 추가", action: add)
                .font(.callout.weight(.semibold))
                .foregroundStyle(CalendarTokens.label)
                .frame(minHeight: 44)
                .accessibilityIdentifier("calendar.empty.add")
        }
        .frame(maxWidth: .infinity)
        .padding(.vertical, 28)
    }

    static func title(_ date: Date) -> String {
        let calendar = Calendar.workshop
        let weekday = ["일", "월", "화", "수", "목", "금", "토"][calendar.component(.weekday, from: date) - 1]
        return "\(calendar.component(.day, from: date))일 \(weekday)요일"
    }
}

struct PinnedSummaryCard: View {
    let date: Date
    let overdue: [AgendaItem]
    let allDay: [AgendaItem]
    let orders: [AgendaItem]
    @Environment(\.dynamicTypeSize) private var dynamicTypeSize

    var body: some View {
        if !overdue.isEmpty || !allDay.isEmpty || !orders.isEmpty {
            VStack(spacing: 0) {
                if !overdue.isEmpty {
                    NavigationLink(value: AreaRoute(area: .deliveries, filter: "scheduled")) {
                        overdueRow
                    }
                    .buttonStyle(.plain)
                    .accessibilityIdentifier("calendar.overdue")
                }
                ForEach(Array(allDay.enumerated()), id: \.element.id) { index, item in
                    if index > 0 || !overdue.isEmpty { separator }
                    allDayRow(item)
                }
                if !orders.isEmpty {
                    if !allDay.isEmpty || !overdue.isEmpty { separator }
                    NavigationLink {
                        DayOrdersView(date: date, orders: orders)
                    } label: {
                        row(symbol: "bag", lead: "새 주문 \(orders.count)건", rest: " · \(total)", chevron: true)
                    }
                    .buttonStyle(.plain)
                    .accessibilityIdentifier("calendar.orders")
                }
            }
            .padding(.horizontal, 14)
            .background(CalendarTokens.pinned, in: .rect(cornerRadius: 16))
        }
    }

    private var overdueRow: some View {
        HStack(spacing: 10) {
            Image(systemName: "clock")
                .font(.subheadline)
                .foregroundStyle(Color.overdueRed)
                .frame(width: 20)
                .accessibilityHidden(true)
            Text("\(Text("기한 지남").foregroundStyle(Color.overdueRed).fontWeight(.semibold)) · 못 보낸 택배 \(overdue.count)건")
                .font(.subheadline)
                .foregroundStyle(CalendarTokens.label)
                .lineLimit(dynamicTypeSize.isAccessibilitySize ? 4 : 1)
            Spacer(minLength: 4)
            Image(systemName: "chevron.forward")
                .font(.footnote.weight(.semibold))
                .foregroundStyle(CalendarTokens.tertiary)
                .accessibilityHidden(true)
        }
        .frame(minHeight: 46)
        .contentShape(.rect)
        .accessibilityElement(children: .combine)
    }

    private var total: String {
        let sum = orders.reduce(0) { $0 + ($1.amountWon ?? 0) }
        return "\(sum.formatted(.number.grouping(.automatic)))원"
    }

    private var separator: some View {
        Rectangle().fill(CalendarTokens.separator).frame(height: 1)
    }

    @ViewBuilder
    private func allDayRow(_ item: AgendaItem) -> some View {
        let status = item.detail.hasPrefix("#")
            ? item.detail.split(separator: "·", maxSplits: 1).last.map { $0.trimmingCharacters(in: .whitespaces) } ?? ""
            : item.detail
        let label = row(symbol: Self.symbol(item), lead: "종일", rest: " · \(item.title) \(status)", chevron: false)
        if let route = item.route {
            NavigationLink(value: route) { label }.buttonStyle(.plain)
        } else {
            label
        }
    }

    private static func symbol(_ item: AgendaItem) -> String {
        switch item.kind {
        case .booking: "calendar"
        case .order: "bag"
        case .delivery: "shippingbox"
        case .todo: "checklist"
        }
    }

    private func row(symbol: String, lead: String, rest: String, chevron: Bool) -> some View {
        HStack(spacing: 10) {
            Image(systemName: symbol)
                .font(.subheadline)
                .foregroundStyle(CalendarTokens.label)
                .frame(width: 20)
                .accessibilityHidden(true)
            Text("\(Text(lead).fontWeight(.semibold))\(rest)")
                .font(.subheadline)
                .foregroundStyle(CalendarTokens.label)
                .lineLimit(dynamicTypeSize.isAccessibilitySize ? 4 : 1)
            Spacer(minLength: 4)
            if chevron {
                Image(systemName: "chevron.forward")
                    .font(.footnote.weight(.semibold))
                    .foregroundStyle(CalendarTokens.tertiary)
                    .accessibilityHidden(true)
            }
        }
        .frame(minHeight: 46)
        .contentShape(.rect)
        .accessibilityElement(children: .combine)
    }
}

struct TimelineList: View {
    let plan: TimelinePlan
    let now: Int
    let check: (TimelineEntry, Bool) async -> Bool

    var body: some View {
        LazyVStack(alignment: .leading, spacing: 0) {
            ForEach(Array(plan.rows.enumerated()), id: \.element.id) { index, row in
                if plan.nowIndex == index {
                    NowIndicator(minutes: now, isFirst: index == 0, isLast: false)
                }
                TimelineRow(row: row, now: now, check: check,
                            isFirst: index == 0 && plan.nowIndex != 0,
                            isLast: index == plan.rows.count - 1 && plan.nowIndex != plan.rows.count)
            }
            if let nowIndex = plan.nowIndex, nowIndex == plan.rows.count {
                NowIndicator(minutes: now, isFirst: plan.rows.isEmpty, isLast: true)
            }
        }
    }
}

enum TimelineMetrics {
    static let nodeColumn: CGFloat = 28
    static let nodeCenter: CGFloat = 11
}

/// The 1pt rail through the node column; it never runs above the first node or below the last.
private struct Rail: View {
    let isFirst: Bool
    let isLast: Bool
    var center: CGFloat = TimelineMetrics.nodeCenter

    var body: some View {
        VStack(spacing: 0) {
            Rectangle().fill(isFirst ? Color.clear : CalendarTokens.separator).frame(width: 1, height: center)
            Rectangle().fill(isLast ? Color.clear : CalendarTokens.separator).frame(width: 1)
                .frame(maxHeight: .infinity)
        }
    }
}

struct TimelineRow: View {
    let row: TimelinePlan.Row
    let now: Int
    let check: (TimelineEntry, Bool) async -> Bool
    let isFirst: Bool
    let isLast: Bool
    @State private var requestedDone: Bool?
    @Environment(AppModel.self) private var app
    @Environment(\.dynamicTypeSize) private var dynamicTypeSize
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @ScaledMetric(relativeTo: .subheadline) private var timeWidth = 48

    private var entry: TimelineEntry { row.entry }
    private var isDone: Bool { requestedDone ?? entry.isDone }

    /// A tap shows its result at once; the reloaded row or a failure settles it.
    private var shown: TimelinePlan.Row {
        guard let requestedDone else { return row }
        let state: CalendarEventState = requestedDone ? .done : row.state == .done ? .upcoming : row.state
        return TimelinePlan.Row(entry: entry, state: state, isOverdue: row.isOverdue && !requestedDone)
    }

    private var state: CalendarEventState { shown.state }

    var body: some View {
        HStack(alignment: .top, spacing: 0) {
            // At accessibility sizes the time moves above the title so neither column is clipped.
            if !dynamicTypeSize.isAccessibilitySize {
                time
                    .frame(width: timeWidth, alignment: .leading)
                    .padding(.top, 1)
            }
            ZStack(alignment: .top) {
                Rail(isFirst: isFirst, isLast: isLast)
                node
            }
            .frame(width: TimelineMetrics.nodeColumn)
            .frame(maxHeight: .infinity)
            content
                .padding(.leading, 8)
            if entry.ownerItem != nil {
                checkButton
            }
        }
        .frame(minHeight: state == .next ? 96 : 68, alignment: .top)
        .fixedSize(horizontal: false, vertical: true)
        .onChange(of: entry.isDone) { requestedDone = nil }
    }

    private var checkButton: some View {
        Button(action: toggle) {
            ZStack {
                Circle()
                    .strokeBorder(isDone ? CalendarTokens.label : CalendarTokens.tertiary, lineWidth: 1.5)
                    .background(isDone ? CalendarTokens.label : Color.clear, in: .circle)
                if isDone {
                    Image(systemName: "checkmark")
                        .font(.system(size: 13, weight: .bold))
                        .foregroundStyle(CalendarTokens.background)
                        .transition(.scale.combined(with: .opacity))
                }
            }
            .frame(width: 26, height: 26)
            .frame(width: 44, height: 44)
            .contentShape(.rect)
        }
        .buttonStyle(.plain)
        .offset(y: -11)
        .disabled(app.isRunning(entry.id))
        .sensoryFeedback(.success, trigger: isDone) { _, done in done }
        .accessibilityLabel("\(entry.title) 완료 표시")
        .accessibilityValue(isDone ? "완료" : "미완료")
        .accessibilityHint(isDone ? "완료를 취소해요" : "완료로 표시해요")
        .accessibilityIdentifier("timeline.check.\(entry.id)")
    }

    private func toggle() {
        let target = !isDone
        withAnimation(reduceMotion ? nil : .snappy(duration: 0.2)) { requestedDone = target }
        Task {
            if await !check(entry, target) {
                withAnimation(reduceMotion ? nil : .snappy(duration: 0.2)) { requestedDone = nil }
            }
        }
    }

    private var time: some View {
        Text(entry.isAllDay ? "종일" : TimelineText.clock(entry.start))
            .font(.subheadline.monospacedDigit().weight(timeWeight))
            .foregroundStyle(state == .done || state == .missed ? CalendarTokens.secondary : CalendarTokens.label)
            .accessibilityHidden(true)
    }

    private var nodeSize: CGFloat { state == .next ? 16 : 14 }

    private var timeWeight: Font.Weight {
        switch state {
        case .done, .missed: .regular
        case .next: .bold
        case .upcoming: .semibold
        }
    }

    private var node: some View {
        TimelineNode(kind: entry.kind, state: state, durationMinutes: entry.minutes)
            .padding(.top, TimelineMetrics.nodeCenter - nodeSize / 2)
            .accessibilityHidden(true)
    }

    @ViewBuilder
    private var content: some View {
        let text = VStack(alignment: .leading, spacing: 3) {
            if dynamicTypeSize.isAccessibilitySize {
                time
            }
            Text(entry.title)
                .font(titleFont)
                .strikethrough(state == .done && entry.ownerItem != nil, color: CalendarTokens.secondary)
                .foregroundStyle(state == .done ? CalendarTokens.secondary : CalendarTokens.label)
                .lineLimit(2)
            metaText
                .font(.footnote)
                .foregroundStyle(CalendarTokens.secondary)
                .lineLimit(2)
            if state == .next {
                Text(TimelineText.next(entry, now: now))
                    .font(.footnote.weight(.semibold))
                    .foregroundStyle(CalendarTokens.label)
                    .padding(.top, 4)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(.bottom, 16)
        .contentShape(.rect)
        link(text)
    }

    @ViewBuilder
    private func link(_ text: some View) -> some View {
        switch entry.destination {
        case .app(let route):
            NavigationLink(value: route) { text }.buttonStyle(.plain).rowAccessibility(spoken, id: entry.id)
        case .area(let route):
            NavigationLink(value: route) { text }.buttonStyle(.plain).rowAccessibility(spoken, id: entry.id)
        case nil:
            text.rowAccessibility(spoken, id: entry.id)
        }
    }

    private var metaText: Text {
        guard let word = TimelineText.overdueWord(shown) else { return Text(TimelineText.meta(shown)) }
        return Text("\(TimelineText.meta(shown)) · \(Text(word).foregroundStyle(Color.overdueRed).fontWeight(.semibold))")
    }

    private var titleFont: Font {
        switch state {
        case .done, .missed: .callout.weight(.medium)
        case .next: .headline.bold()
        case .upcoming: .callout.weight(.semibold)
        }
    }

    private var spoken: String {
        var parts = [entry.kind.label]
        parts.append(entry.minutes == nil
            ? TimelineText.spoken(entry.start)
            : "\(TimelineText.spoken(entry.start))부터 \(TimelineText.spoken(entry.end))")
        parts.append(entry.title)
        if !entry.subject.isEmpty { parts.append(entry.subject) }
        switch state {
        case .done: parts.append("완료됨")
        case .next: parts.append(TimelineText.next(entry, now: now))
        case .missed: parts.append("기한 지남")
        case .upcoming: if row.isOverdue { parts.append("기한 지남") }
        }
        return parts.joined(separator: ", ")
    }
}

private extension View {
    func rowAccessibility(_ label: String, id: String) -> some View {
        accessibilityElement(children: .ignore)
            .accessibilityLabel(label)
            .accessibilityIdentifier("timeline.\(id)")
    }
}

/// Kind is the node's shape; state is its weight and tone. Done rows look the same for every kind.
struct TimelineNode: View {
    let kind: CalendarEventKind
    let state: CalendarEventState
    let durationMinutes: Int?

    var body: some View {
        VStack(spacing: 0) {
            if state == .missed {
                Circle()
                    .stroke(Color.overdueRed, style: StrokeStyle(lineWidth: 2, dash: [3, 2]))
                    .frame(width: 13, height: 13)
                    .frame(width: 14, height: 14)
            } else if state == .next {
                NodeShape(kind: kind, isDone: false, size: 16, lineWidth: 2.5)
                // The next row always carries the bar; without a duration it keeps the 24pt minimum.
                Rectangle()
                    .fill(CalendarTokens.label)
                    .frame(width: 3, height: max(24, min(72, CGFloat(durationMinutes ?? 0) * 0.42)))
            } else {
                NodeShape(kind: kind, isDone: state == .done)
            }
        }
    }
}

struct NodeShape: View {
    let kind: CalendarEventKind
    let isDone: Bool
    var size: CGFloat = 14
    var lineWidth: CGFloat = 2

    var body: some View {
        Group {
            if isDone {
                Image(systemName: "checkmark")
                    .font(.system(size: size * 0.64, weight: .bold))
                    .foregroundStyle(CalendarTokens.secondary)
                    .frame(width: size, height: size)
                    .background(CalendarTokens.separator, in: .circle)
            } else {
                switch kind {
                case .reservation:
                    Circle().fill(CalendarTokens.label)
                case .delivery:
                    RoundedRectangle(cornerRadius: 2)
                        .strokeBorder(CalendarTokens.label, lineWidth: lineWidth)
                        .background(CalendarTokens.background, in: .rect(cornerRadius: 2))
                        .padding(size / 14)
                case .task:
                    Circle()
                        .strokeBorder(CalendarTokens.label, lineWidth: lineWidth)
                        .background(CalendarTokens.background, in: .circle)
                }
            }
        }
        .frame(width: size, height: size)
    }
}

struct NowIndicator: View {
    let minutes: Int
    let isFirst: Bool
    let isLast: Bool
    @Environment(\.dynamicTypeSize) private var dynamicTypeSize
    @ScaledMetric(relativeTo: .subheadline) private var timeWidth = 48

    var body: some View {
        HStack(spacing: 0) {
            Text(TimelineText.clock(minutes))
                .font(.caption.bold().monospacedDigit())
                .foregroundStyle(CalendarTokens.background)
                .padding(.horizontal, 8)
                .frame(height: 22)
                .background(CalendarTokens.label, in: .capsule)
                .fixedSize()
                .frame(width: dynamicTypeSize.isAccessibilitySize ? nil : timeWidth, alignment: .leading)
            ZStack {
                Rail(isFirst: isFirst, isLast: isLast, center: 18)
                Circle().fill(CalendarTokens.label).frame(width: 9, height: 9)
            }
            .frame(width: TimelineMetrics.nodeColumn)
            Rectangle()
                .fill(CalendarTokens.label)
                .frame(height: 2)
        }
        .frame(minHeight: 36)
        .fixedSize(horizontal: false, vertical: true)
        .padding(.bottom, 8)
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("현재 시각 \(TimelineText.spoken(minutes))")
        .accessibilityIdentifier("timeline.now")
    }
}

struct TimelineLegend: View {
    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Rectangle().fill(CalendarTokens.separator).frame(height: 1)
            ViewThatFits(in: .horizontal) {
                HStack(spacing: 14) { items }
                VStack(alignment: .leading, spacing: 6) { items }
            }
            .font(.caption)
            .foregroundStyle(CalendarTokens.secondary)
            .accessibilityElement(children: .ignore)
            .accessibilityLabel("범례: 채운 원 예약, 사각형 배송, 빈 원 할 일, 회색 체크 끝남, 빨간 점선 원 지남")
        }
    }

    @ViewBuilder
    private var items: some View {
        item(.reservation, "예약")
        item(.delivery, "배송")
        item(.task, "할 일")
        HStack(spacing: 5) {
            Circle().fill(CalendarTokens.separator).frame(width: 10, height: 10)
            Text("끝남")
        }
        HStack(spacing: 5) {
            Circle()
                .stroke(Color.overdueRed, style: StrokeStyle(lineWidth: 1.5, dash: [2, 1.5]))
                .frame(width: 10, height: 10)
            Text("지남").foregroundStyle(Color.overdueRed)
        }
    }

    private func item(_ kind: CalendarEventKind, _ label: String) -> some View {
        HStack(spacing: 5) {
            NodeShape(kind: kind, isDone: false, size: 10)
            Text(label)
        }
    }
}

struct DayOrdersView: View {
    let date: Date
    let orders: [AgendaItem]

    var body: some View {
        List {
            CardSection {
                ForEach(orders) { order in
                    if let route = order.route {
                        NavigationLink(value: route) { row(order) }
                    } else {
                        row(order)
                    }
                }
            }
        }
        .cardList()
        .navigationTitle("\(date.koreanDay(weekday: false)) 새 주문")
        .navigationBarTitleDisplayMode(.inline)
    }

    private func row(_ order: AgendaItem) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(keepingWords: order.title).font(.body.weight(.medium))
            Text("\(order.time) 접수 · \(order.detail)")
                .font(.subheadline)
                .foregroundStyle(Color.secondaryText)
        }
        .accessibilityElement(children: .combine)
    }
}

// MARK: - Previews

#if DEBUG
enum CalendarPreviewData {
    static let now = Calendar.workshop.date(
        from: DateComponents(year: 2026, month: 11, day: 18, hour: 13, minute: 30)) ?? .now

    static let days: [String: CalendarDay] = {
        var days = ["2026-11-18": CalendarDay(date: "2026-11-18", events: [], items: items)]
        for (key, count) in [("2026-11-16", 3), ("2026-11-17", 1), ("2026-11-19", 1), ("2026-11-21", 4), ("2026-11-22", 1)] {
            days[key] = CalendarDay(date: key, events: [], items: (0..<count).map { index in
                item("task:\(key)-\(index)", "10:00", "예시 할 일", .todo, "", subject: nil)
            })
        }
        return days
    }()

    static let items: [AgendaItem] = [
        item("shipment:1039", "종일", "도자기 찬기 3종 세트", .delivery, "#1039 · 도착 예정"),
        item("order:1040", "08:12", "머그컵 2종 세트", .order, "#1040 · 김*연 · 42,000원", amount: 42_000),
        item("order:1043", "09:40", "핸드메이드 미니 화병", .order, "#1043 · 정*우 · 28,000원", amount: 28_000),
        item("order:1044", "11:05", "오롯 세라믹 플레이트", .order, "#1044 · 이*진 · 56,000원", amount: 56_000),
        item("session:morning", "10:00", "도자기 원데이 클래스", .booking, "예약 4명 · 90분",
             subject: "정*주 님 외 3명", minutes: 90, done: true),
        item("task:clay", "12:00", "도자기용 점토 50kg 주문", .todo, "도예사", subject: "도예사", done: true, revision: 1),
        item("session:afternoon", "14:00", "나만의 머그컵 만들기", .booking, "예약 4명 · 120분",
             subject: "오*호 님 외 3명", minutes: 120),
        item("shipment:1040", "16:00", "머그컵 2종 세트", .delivery, "#1040 · 택배 수거"),
        item("shipment:1044", "16:00", "오롯 세라믹 플레이트", .delivery, "#1044 · 택배 수거"),
        item("task:market", "17:00", "플리마켓 모집 조건 확인", .todo, "순천그린광장 달빛야행",
             subject: "순천그린광장 달빛야행", revision: 0),
        item("event:keyring", "20:00", "키링 이벤트 결과 올리기", .todo, "행운의 거북이 도자기 키링"),
    ]

    private static func item(_ id: String, _ time: String, _ title: String, _ kind: EventKind, _ detail: String,
                             subject: String? = nil, minutes: Int? = nil, amount: Int? = nil,
                             done: Bool? = nil, revision: Int? = nil) -> AgendaItem {
        AgendaItem(id: id, time: time, title: title, kind: kind, detail: detail, isDone: done,
                   minutes: minutes, subject: subject, amountWon: amount, revision: revision)
    }
}

private struct CalendarPreview: View {
    @State var mode: CalendarMode
    @State var day: Date
    var days = CalendarPreviewData.days
    @State private var app = AppModel()

    var body: some View {
        NavigationStack {
            CalendarContent(days: days, overdueShipments: [], selectedDay: $day, mode: $mode,
                            now: CalendarPreviewData.now, add: {}, check: { _, _ in true })
                .navigationTitle("캘린더")
                .navigationSubtitle("오늘 일정 11건")
        }
        .environment(app)
    }
}

#Preview("주간 · 라이트") {
    CalendarPreview(mode: .week, day: CalendarPreviewData.now)
}

#Preview("주간 · 다크") {
    CalendarPreview(mode: .week, day: CalendarPreviewData.now)
        .preferredColorScheme(.dark)
}

#Preview("월간") {
    CalendarPreview(mode: .month, day: CalendarPreviewData.now)
}

#Preview("빈 날짜") {
    CalendarPreview(mode: .week, day: CalendarPreviewData.now.addingTimeInterval(4 * 86_400))
}

#Preview("큰 글씨") {
    CalendarPreview(mode: .week, day: CalendarPreviewData.now)
        .dynamicTypeSize(.accessibility5)
}
#endif
