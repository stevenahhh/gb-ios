import RoundupCore
import SwiftUI

/// What each channel's collector is doing, as one ring per channel at the top of 운영 현황. The server is asked again
/// about every five seconds while the rings are on screen. Until a channel is connected the rings play a sample and
/// say so; `CollectionDisplay` decides.
struct CollectionStatusRings: View {
    @State private var loader = Loader<CollectorStatus>()
    @Environment(AppModel.self) private var app
    @Environment(\.dynamicTypeSize) private var dynamicTypeSize

    private static let pollInterval: Duration = .seconds(5)
    private static let clock = Date.FormatStyle(date: .omitted, time: .shortened, locale: Locale(identifier: "ko_KR"),
                                                timeZone: Calendar.workshop.timeZone)

    /// Before the first answer the rings only wait, so the sample never flashes ahead of real states.
    private var hasAnswered: Bool { loader.value != nil || loader.errorMessage != nil }

    /// The last answer the rings may still show. A 404 or another refusal makes a kept answer stale; a connection
    /// failure does not, because the next poll is expected to succeed.
    private var answer: CollectorStatus? {
        let wasRefused = loader.errorMessage != nil && loader.connectionFailures == 0
        return wasRefused ? nil : loader.value
    }

    private var display: CollectionDisplay { .choose(states: answer?.sources.map(\.state)) }

    var body: some View {
        // The polling task belongs to one view that outlives every change of content.
        VStack(alignment: .leading, spacing: 16) {
            if hasAnswered {
                rings
                notice
            } else {
                ProgressView()
                    .frame(maxWidth: .infinity, minHeight: 44)
                    .accessibilityIdentifier("operations.collection.loading")
            }
        }
        .padding(.vertical, 10)
        .task(id: app.dataVersion) { await poll() }
    }

    private var rings: some View {
        let layout = dynamicTypeSize.isAccessibilitySize
            ? AnyLayout(VStackLayout(spacing: 20))
            : AnyLayout(HStackLayout(alignment: .top, spacing: 0))
        return layout {
            // The rings read one clock, so each starts at its own point of the turn and they do not move in step.
            ForEach(Array(CollectionChannel.allCases.enumerated()), id: \.element) { index, channel in
                let source = display == .live ? answer?.sources.first { $0.id == channel.rawValue } : nil
                if display != .live || source != nil {
                    CollectionRing(channel: channel, source: source, stagger: Double(index) * 0.37)
                        .frame(maxWidth: .infinity)
                }
            }
        }
    }

    private var notice: some View {
        VStack(alignment: .leading, spacing: 6) {
            if display != .live {
                StatusBadge(Status(text: "보기용 예시", tone: .neutral))
                    .accessibilityIdentifier("operations.collection.sample")
            }
            PhraseText(text: noticeText)
                .font(.subheadline)
                .foregroundStyle(Color.secondaryText)
        }
    }

    private var noticeText: String {
        switch display {
        case .live:
            "\((answer?.updatedAt ?? .now).formatted(Self.clock))에 본 숫자예요. 5초 간격으로 다시 받아 와요."
        case .sampleWithoutStatus:
            "샘플 숫자로 채워 둔 화면이에요. 채널에서 실제로 불러오기 시작하면 공방 숫자로 바뀌어요."
        case .sampleBeforeConnection:
            "아직은 샘플 숫자예요. 채널을 하나라도 연결하시면 그때부터 공방 숫자로 바뀌어요."
        }
    }

    private func poll() async {
        while !Task.isCancelled {
            await loader.load { try await RoundupAPI.collectorStatus() }
            var wait = Self.pollInterval
            if loader.errorMessage != nil {
                // A 404 or another refusal does not change by asking again, so the sample stays until the screen
                // comes back. Connection failures back off the way every other screen does.
                guard loader.connectionFailures > 0 else { return }
                wait = max(wait, ReconnectBackoff.delay(afterFailures: loader.connectionFailures))
            }
            do { try await Task.sleep(for: wait) } catch { return }
        }
    }
}

/// The channels that have a ring, in the order they are drawn.
private enum CollectionChannel: String, CaseIterable {
    case store = "naver_smartstore"
    case instagram
    case blog = "naver_blog"

    /// The name inside the ring, broken where it fits the circle.
    var title: String {
        switch self {
        case .store: "네이버\n스토어"
        case .instagram: "INSTA\nGRAM"
        case .blog: "블로그"
        }
    }

    var spokenName: String {
        switch self {
        case .store: "네이버 스토어"
        case .instagram: "인스타그램"
        case .blog: "블로그"
        }
    }
}

private extension CollectorState {
    var label: String {
        switch self {
        case .collecting: "가져오는 중"
        case .idle: "대기"
        case .needsConnection: "연결해 주세요"
        case .error: "문제가 생겼어요"
        }
    }
}

/// One channel. A collecting ring keeps turning like a loading mark; every other state rests, and a channel that is
/// not connected is an empty track. Without a source the ring is the sample, which collects.
private struct CollectionRing: View {
    let channel: CollectionChannel
    let source: CollectorStatus.Source?
    /// This ring's offset into the turn, as a share of one turn.
    let stagger: Double
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @ScaledMetric(relativeTo: .subheadline) private var scaledDiameter: CGFloat = 88

    private static let turn = 1.6
    private static let arc = 0.75
    private static let lineWidth: CGFloat = 9

    private var state: CollectorState { source?.state ?? .collecting }
    private var isTurning: Bool { state == .collecting && !reduceMotion }
    private var diameter: CGFloat { min(scaledDiameter, 160) }

    var body: some View {
        VStack(spacing: 8) {
            ZStack {
                Circle()
                    .stroke(Color.progressTrack, lineWidth: Self.lineWidth)
                if state != .needsConnection {
                    TimelineView(.animation(paused: !isTurning)) { context in
                        Circle()
                            .trim(from: 0, to: Self.arc)
                            .stroke(state == .error ? Color.pendingOrange : CalendarTokens.label, lineWidth: Self.lineWidth)
                            .rotationEffect(.degrees(angle(at: context.date)))
                    }
                }
                Text(channel.title)
                    .font(.subheadline.weight(.bold))
                    .multilineTextAlignment(.center)
                    .minimumScaleFactor(0.7)
                    .padding(Self.lineWidth)
            }
            .padding(Self.lineWidth / 2)
            .frame(width: diameter, height: diameter)
            Text(state.label)
                .font(.subheadline.weight(.semibold))
                .foregroundStyle(state == .collecting ? Color.primary : Color.secondaryText)
            if let source, source.collectedToday > 0 {
                Text("오늘 \(source.collectedToday.formatted())건")
                    .font(.subheadline)
                    .monospacedDigit()
                    .foregroundStyle(Color.secondaryText)
            }
        }
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("\(channel.spokenName), \(state.label)")
        .accessibilityValue(spokenValue)
        .accessibilityIdentifier("operations.collection.source.\(channel.rawValue)")
    }

    /// The turn starts at twelve o'clock, where a resting ring keeps its arc.
    private func angle(at date: Date) -> Double {
        guard isTurning else { return -90 }
        let share = (date.timeIntervalSinceReferenceDate / Self.turn + stagger).truncatingRemainder(dividingBy: 1)
        return share * 360 - 90
    }

    private var spokenValue: String {
        guard let source else { return "" }
        let count = source.collectedToday > 0 ? "오늘 \(source.collectedToday.formatted())건 가져옴" : nil
        let ago = source.lastCollectedAt.map { RelativeDayFormatter.elapsed(since: $0, now: .now) }
        return [count, ago, source.message].compactMap { $0 }.joined(separator: ", ")
    }
}
