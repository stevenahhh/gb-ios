import RoundupCore
import SwiftUI

/// 실시간 수집 현황: what each channel's collector is doing, asked again about every five seconds while the card is
/// on screen. Until a channel is connected the card plays sample rows and says so; `CollectionDisplay` decides.
struct CollectionStatusSection: View {
    @State private var loader = Loader<CollectorStatus>()
    @State private var appeared = Date.now
    @Environment(AppModel.self) private var app
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    private static let pollInterval: Duration = .seconds(5)
    private static let clock = Date.FormatStyle(date: .omitted, time: .shortened, locale: Locale(identifier: "ko_KR"),
                                                timeZone: Calendar.workshop.timeZone)

    /// Before the first answer the card only waits, so sample rows never flash ahead of real ones.
    private var hasAnswered: Bool { loader.value != nil || loader.errorMessage != nil }

    /// The last answer the card may still show. A 404 or another refusal makes a kept answer stale; a connection
    /// failure does not, because the next poll is expected to succeed.
    private var answer: CollectorStatus? {
        let wasRefused = loader.errorMessage != nil && loader.connectionFailures == 0
        return wasRefused ? nil : loader.value
    }

    private var display: CollectionDisplay { .choose(states: answer?.sources.map(\.state)) }

    /// The sample ticks with the clock. With motion reduced it holds one moment of its cycle: two sources collecting,
    /// one waiting, one unconnected.
    private func sampleElapsed(at now: Date) -> TimeInterval {
        reduceMotion ? 20 : now.timeIntervalSince(appeared)
    }

    var body: some View {
        CardSection {
            // A ZStack, not a Group: the polling task belongs to one view that outlives every change of content.
            ZStack {
                if !hasAnswered {
                    ProgressView()
                        .frame(maxWidth: .infinity, minHeight: 44)
                        .accessibilityIdentifier("operations.collection.loading")
                } else if display == .live, let answer {
                    rows { _ in answer }
                } else {
                    rows { now in .sample(elapsed: sampleElapsed(at: now), now: now) }
                }
            }
            .task(id: app.dataVersion) { await poll() }
        } header: {
            ViewThatFits(in: .horizontal) {
                HStack {
                    title
                    Spacer()
                    sampleTag
                }
                VStack(alignment: .leading, spacing: 8) {
                    title
                    sampleTag
                }
            }
        } footer: {
            if hasAnswered {
                switch display {
                case .live:
                    if let answer {
                        Text("\(answer.updatedAt.formatted(Self.clock)) 기준이에요. 5초마다 새로 확인해요.")
                    }
                case .sampleWithoutStatus:
                    Text("지금 보이는 숫자는 예시예요. 채널 수집이 시작되면 실제 현황으로 바뀌어요.")
                case .sampleBeforeConnection:
                    Text("아직 연결된 채널이 없어요. 지금 보이는 숫자는 예시예요. 채널을 연결하면 실제 현황으로 바뀌어요.")
                }
            }
        }
    }

    /// One clock for the whole card: it rolls every "n초 전" and drives the sample rows.
    private func rows(_ status: @escaping (Date) -> CollectorStatus) -> some View {
        TimelineView(.periodic(from: appeared, by: 1)) { context in
            VStack(alignment: .leading, spacing: 18) {
                // The rows read one clock, so each starts at its own point of the cycle and they do not move in step.
                ForEach(Array(status(context.date).sources.enumerated()), id: \.element.id) { index, source in
                    CollectionSourceRow(source: source, now: context.date, stagger: Double(index) * 0.37)
                }
            }
            .padding(.vertical, 6)
        }
    }

    private var title: some View {
        Text("실시간 수집 현황")
            .accessibilityAddTraits(.isHeader)
            .accessibilityIdentifier("operations.collection.title")
    }

    @ViewBuilder
    private var sampleTag: some View {
        if hasAnswered, display != .live {
            StatusBadge(Status(text: "예시 데이터", tone: .neutral))
                .textCase(nil)
                .accessibilityIdentifier("operations.collection.sample")
        }
    }

    private func poll() async {
        while !Task.isCancelled {
            await loader.load { try await RoundupAPI.collectorStatus() }
            var wait = Self.pollInterval
            if loader.errorMessage != nil {
                // A 404 or another refusal does not change by asking again, so the sample rows stay until the screen
                // comes back. Connection failures back off the way every other screen does.
                guard loader.connectionFailures > 0 else { return }
                wait = max(wait, ReconnectBackoff.delay(afterFailures: loader.connectionFailures))
            }
            do { try await Task.sleep(for: wait) } catch { return }
        }
    }
}

private extension CollectorState {
    var label: String {
        switch self {
        case .collecting: "수집 중"
        case .idle: "대기"
        case .needsConnection: "연결 필요"
        case .error: "오류"
        }
    }
}

/// One source. Only a collecting source moves; every other state rests.
private struct CollectionSourceRow: View {
    let source: CollectorStatus.Source
    let now: Date
    /// This row's offset into the animation cycle, as a share of one cycle.
    let stagger: Double
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @Environment(\.dynamicTypeSize) private var dynamicTypeSize
    @ScaledMetric(relativeTo: .body) private var markColumn: CGFloat = 14
    @ScaledMetric(relativeTo: .body) private var markLift: CGFloat = 6

    private var isCollecting: Bool { source.state == .collecting }
    private var ago: String? { source.lastCollectedAt.map { RelativeDayFormatter.elapsed(since: $0, now: now) } }

    /// A source that never ran has no numbers worth a line; its message says what to do next.
    private var showsNumbers: Bool {
        switch source.state {
        case .collecting, .idle: true
        case .needsConnection, .error: source.collectedToday > 0 || source.lastCollectedAt != nil
        }
    }

    var body: some View {
        // Read here: the alignment guide's closure runs off the main actor.
        let lift = markLift
        HStack(alignment: .firstTextBaseline, spacing: 10) {
            CollectionStateMark(state: source.state, isPulsing: isCollecting && !reduceMotion, stagger: stagger)
                .frame(width: markColumn)
                .alignmentGuide(.firstTextBaseline) { $0[VerticalAlignment.center] + lift }
            VStack(alignment: .leading, spacing: 6) {
                line {
                    Text(verbatim: source.name)
                        .font(.body.weight(.medium))
                } trailing: {
                    Text(source.state.label)
                        .font(.subheadline.weight(.semibold))
                        .foregroundStyle(source.state == .idle ? Color.secondaryText : Color.primary)
                }
                if isCollecting || source.state == .idle {
                    SweepBar(isCollecting: isCollecting, isMoving: isCollecting && !reduceMotion, stagger: stagger)
                }
                if showsNumbers {
                    numbers
                }
                if let message = source.message {
                    // An error line is label-colored; only its mark is orange.
                    PhraseText(text: message)
                        .font(.subheadline)
                        .foregroundStyle(source.state == .error ? Color.primary : Color.secondaryText)
                }
            }
        }
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("\(source.name), \(source.state.label)")
        .accessibilityValue(spokenValue)
        .accessibilityIdentifier("operations.collection.source.\(source.id)")
    }

    private var numbers: some View {
        line {
            Text("수집 \(source.collectedToday.formatted())건")
                .font(.subheadline.weight(.semibold))
                .contentTransition(reduceMotion ? .identity : .numericText(value: Double(source.collectedToday)))
                .animation(reduceMotion ? nil : .snappy, value: source.collectedToday)
        } trailing: {
            if let ago {
                Text(ago)
                    .font(.subheadline)
                    .foregroundStyle(Color.secondaryText)
                    .contentTransition(reduceMotion ? .identity : .numericText())
                    .animation(reduceMotion ? nil : .default, value: ago)
            }
        }
        .monospacedDigit()
    }

    private var spokenValue: String {
        let numbers = showsNumbers ? ["오늘 \(source.collectedToday.formatted())건 수집", ago] : []
        return (numbers + [source.message]).compactMap { $0 }.joined(separator: ", ")
    }

    /// Two texts on one line, or stacked at accessibility sizes so neither is squeezed.
    private func line(@ViewBuilder _ leading: () -> some View, @ViewBuilder trailing: () -> some View) -> some View {
        let isStacked = dynamicTypeSize.isAccessibilitySize
        let layout = isStacked
            ? AnyLayout(VStackLayout(alignment: .leading, spacing: 2))
            : AnyLayout(HStackLayout(alignment: .firstTextBaseline, spacing: 8))
        return layout {
            leading()
            if !isStacked {
                Spacer(minLength: 0)
            }
            trailing()
        }
    }
}

private struct CollectionStateMark: View {
    let state: CollectorState
    let isPulsing: Bool
    let stagger: Double
    @ScaledMetric(relativeTo: .body) private var dot: CGFloat = 8

    var body: some View {
        switch state {
        case .collecting:
            Circle()
                .fill(CalendarTokens.label)
                .frame(width: dot, height: dot)
                .background {
                    if isPulsing {
                        PulseRing(stagger: stagger)
                    }
                }
        case .idle:
            Circle()
                .fill(CalendarTokens.tertiary)
                .frame(width: dot, height: dot)
        case .needsConnection:
            Circle()
                .fill(Color.pendingOrange)
                .frame(width: dot, height: dot)
        case .error:
            Image(systemName: "exclamationmark.circle.fill")
                .font(.footnote)
                .foregroundStyle(Color.pendingOrange)
        }
    }
}

/// A ring that grows out of the dot and fades. It reads the clock instead of keeping its own state, so it cannot
/// drift or stop while the row is on screen.
private struct PulseRing: View {
    let stagger: Double

    private static let period = 1.4

    var body: some View {
        TimelineView(.animation) { context in
            let phase = (context.date.timeIntervalSinceReferenceDate / Self.period + stagger)
                .truncatingRemainder(dividingBy: 1)
            let spread = 1 - (1 - phase) * (1 - phase)
            Circle()
                .stroke(CalendarTokens.label, lineWidth: 1.5)
                .scaleEffect(1 + 1.8 * spread)
                .opacity(0.6 * (1 - phase))
        }
    }
}

/// An indeterminate bar: a short segment crosses the track for as long as the source collects, and the track is
/// empty while it waits. With motion reduced the segment rests in the middle.
private struct SweepBar: View {
    let isCollecting: Bool
    let isMoving: Bool
    let stagger: Double

    private static let period = 1.6
    private static let segment: CGFloat = 0.32

    var body: some View {
        Capsule()
            .fill(Color.progressTrack)
            .frame(height: 4)
            .overlay {
                if isCollecting {
                    GeometryReader { proxy in
                        TimelineView(.animation(paused: !isMoving)) { context in
                            Capsule()
                                .fill(CalendarTokens.label)
                                .frame(width: proxy.size.width * Self.segment)
                                .offset(x: proxy.size.width * offset(at: context.date))
                        }
                    }
                }
            }
            .clipShape(.capsule)
            .accessibilityHidden(true)
    }

    /// The segment's leading edge as a share of the track, from fully off the leading end to fully off the trailing end.
    private func offset(at date: Date) -> CGFloat {
        guard isMoving else { return (1 - Self.segment) / 2 }
        let phase = (date.timeIntervalSinceReferenceDate / Self.period + stagger).truncatingRemainder(dividingBy: 1)
        let eased = CGFloat(phase * phase * (3 - 2 * phase))
        return eased * (1 + Self.segment) - Self.segment
    }
}

extension CollectorStatus {
    /// Sample rows for a server that reports no source. Every value follows from the seconds since the card appeared,
    /// so the rows keep moving with no stored state: two sources collect, the blog alternates, and one needs the owner.
    static func sample(elapsed: TimeInterval, now: Date) -> CollectorStatus {
        let second = max(0, Int(elapsed))
        func source(_ id: String, _ name: String, base: Int, marks: [Int], cycle: Int, busyUntil: Int? = nil) -> Source {
            let (count, secondsAgo) = arrivals(at: marks, every: cycle, by: second)
            let isBusy = busyUntil.map { second % cycle < $0 } ?? true
            return Source(id: id, name: name, state: isBusy ? .collecting : .idle,
                          lastCollectedAt: now.addingTimeInterval(-TimeInterval(secondsAgo)),
                          collectedToday: base + count, message: nil)
        }
        return CollectorStatus(sources: [
            source("instagram", "인스타그램", base: 128, marks: [2, 5, 6, 10, 12], cycle: 12),
            source("naver_smartstore", "네이버 스마트스토어", base: 46, marks: [4, 10, 13], cycle: 13),
            source("naver_blog", "네이버 블로그", base: 12, marks: [3, 7, 12], cycle: 40, busyUntil: 14),
            Source(id: "naver_booking_talktalk", name: "네이버 예약·톡톡", state: .needsConnection, lastCollectedAt: nil,
                   collectedToday: 0, message: "네이버 예약과 톡톡은 아직 자동으로 가져올 수 없어요."),
        ], updatedAt: now)
    }

    /// How many items have arrived by second `second`, and how long ago the newest one did, when arrivals repeat
    /// every `cycle` seconds at `marks`. A mark equal to `cycle` is the arrival that opens the next round.
    private static func arrivals(at marks: [Int], every cycle: Int, by second: Int) -> (count: Int, secondsAgo: Int) {
        let (rounds, rest) = second.quotientAndRemainder(dividingBy: cycle)
        let passed = marks.filter { $0 <= rest }
        let secondsAgo = passed.last.map { rest - $0 } ?? rest + cycle - (marks.last ?? cycle)
        return (rounds * marks.count + passed.count, secondsAgo)
    }
}
