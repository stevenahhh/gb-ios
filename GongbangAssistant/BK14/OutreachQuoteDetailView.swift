#if BUILD_B
import SwiftUI

struct OutreachQuoteDetailView: View {
    let opened: OutreachOpened
    @State private var loader = Loader<OutreachQuote>()
    @State private var adjusted: OutreachQuote?
    @State private var change: OutreachAdjustment?
    @State private var isRecalculating = false
    @State private var reply = ""
    @State private var replyIsEdited = false
    @State private var isPreviewing = false
    @State private var followUp = Date.now
    @State private var finalTotal: Int?
    @State private var asksFinalTotal = false
    @State private var offersEvent = false
    @Environment(AppModel.self) private var app

    private var runID: String { "outreach.\(opened.id)" }

    var body: some View {
        LoadableContent(loader: loader, retry: load) { loaded in
            content(adjusted ?? loaded)
        }
        .navigationTitle((adjusted ?? loader.value)?.title ?? "출강 견적")
        .navigationBarTitleDisplayMode(.inline)
        .task(id: app.dataVersion) { await load() }
        .task(id: change) { await recalculate() }
        .sheet(isPresented: $isPreviewing) {
            if let quote = adjusted ?? loader.value {
                OutreachPDFPreview(quote: quote) { seconds in shared(quote, seconds: seconds) } startedAt: { opened.startedAt }
            }
        }
        .alert("조정한 총액", isPresented: $asksFinalTotal) {
            TextField("총액", value: $finalTotal, format: .number).keyboardType(.numberPad)
            Button("취소", role: .cancel) {}
            Button("저장") { record(.acceptedAdjusted) }
                .disabled((finalTotal ?? 0) <= 0)
        }
        .alert("캘린더에 출강 일정을 만들까요?", isPresented: $offersEvent) {
            Button("나중에", role: .cancel) {}
            Button("만들기") { addEvent() }
        } message: {
            Text("이동 시간을 앞에 붙여 출발 시각으로 넣어요.")
        }
    }

    private func content(_ quote: OutreachQuote) -> some View {
        List {
            if !quote.signals.isEmpty {
                OutreachWarningCard(signals: quote.signals, isVerified: !quote.locked && quote.orgVerifiedAt != nil,
                                    isBusy: app.isRunning(runID)) { verify(quote) }
            }
            verdictSection(quote)
            adjustSection(quote)
            linesSection(quote)
            if !quote.conflicts.isEmpty { conflictSection(quote) }
            replySection(quote)
            if quote.outcome == nil { followUpSection(quote) }
            outcomeSection(quote)
        }
        .cardList()
        .opacity(isRecalculating ? 0.6 : 1)
        .refreshable { await load() }
        .safeAreaInset(edge: .bottom) {
            Button {
                isPreviewing = true
            } label: {
                Text("견적표 만들기")
                    .foregroundStyle(Color(.systemBackground))
                    .frame(maxWidth: .infinity)
            }
            .buttonStyle(.borderedProminent)
            .controlSize(.large)
            .padding(.horizontal, 16)
            .padding(.vertical, 8)
            .background(AppPalette.listBackground)
            .accessibilityIdentifier("outreach.makePDF")
        }
    }

    // MARK: Verdict

    private func verdictSection(_ quote: OutreachQuote) -> some View {
        let result = quote.calculation
        return CardSection("가부 판단") {
            if result.verdict == .unknown {
                Text("원가가 비어 판단할 수 없습니다").font(.headline)
                    .accessibilityIdentifier("outreach.verdict")
                NavigationLink {
                    ClassCostListView()
                } label: {
                    Label { Text("원가 입력하기") } icon: { MenuIcon(systemName: "square.and.pencil") }
                }
                .accessibilityIdentifier("outreach.enterCosts")
            } else {
                VStack(alignment: .leading, spacing: 6) {
                    Text(result.verdict == .better ? "원데이보다 남습니다" : "원데이보다 덜 남습니다")
                        .font(.title3.weight(.semibold))
                        .accessibilityIdentifier("outreach.verdict")
                    Text(suggestion(result))
                    Text(verbatim: quote.summary)
                        .font(.subheadline)
                        .foregroundStyle(Color.secondaryText)
                    VStack(alignment: .leading, spacing: 2) {
                        PhraseText(text: result.outreachBasis)
                        PhraseText(text: result.onedayBasis)
                    }
                    .font(.subheadline)
                    .foregroundStyle(Color.secondaryText)
                }
                OutreachValueRow(title: "1인 순수익", value: OutreachFormat.won(result.netPerPersonOutreach))
                OutreachValueRow(title: "원데이 1인 순수익", value: OutreachFormat.won(result.netPerPersonOneday))
                if let outreach = result.netPerHourOutreach, let oneday = result.netPerHourOneday {
                    OutreachValueRow(title: "시간당 순수익", value: OutreachFormat.won(outreach))
                    OutreachValueRow(title: "원데이 시간당 순수익", value: OutreachFormat.won(oneday))
                }
                if let minimum = result.breakEvenHeadcount {
                    OutreachValueRow(title: "최소 인원", value: "1인 \(OutreachFormat.won(result.perPersonKrw))이면 \(minimum)명부터")
                }
                if let limit = result.maxHeadcount, let budget = quote.fields.budgetKrw {
                    OutreachValueRow(title: "예산 기준 인원", value: "\(OutreachFormat.won(budget))이면 \(limit)명까지")
                }
                if result.verdict == .worse, let needed = result.neededTotalKrw {
                    OutreachValueRow(title: "이 인원에 필요한 총액", value: OutreachFormat.won(needed))
                }
            }
        }
    }

    private func suggestion(_ result: OutreachCalculation) -> String {
        switch result.suggestion {
        case .accept: "받기를 권해요."
        case .raise: "최소 인원이나 금액을 올려 받기를 권해요."
        case .decline: "정중히 사양하기를 권해요."
        case .unknown: ""
        }
    }

    // MARK: Adjust

    private func adjustSection(_ quote: OutreachQuote) -> some View {
        let inputs = quote.inputs
        return CardSection {
            Stepper("인원 \(change?.headcount ?? inputs.headcount)명",
                    value: Binding { change?.headcount ?? inputs.headcount } set: { adjust { $0.headcount = $1 }($0) },
                    in: 1...1000)
                .accessibilityIdentifier("outreach.stepHeadcount")
            let perPerson = change?.perPersonKrw ?? inputs.perPersonKrw ?? quote.calculation.perPersonKrw
            Stepper("1인 \(OutreachFormat.won(perPerson))",
                    value: Binding { perPerson } set: { adjust { $0.perPersonKrw = $1 }($0) },
                    in: 1000...1_000_000, step: 1000)
                .accessibilityIdentifier("outreach.stepPrice")
            Stepper("보조 강사 \(change?.assistants ?? inputs.assistants)명",
                    value: Binding { change?.assistants ?? inputs.assistants } set: { adjust { $0.assistants = $1 }($0) },
                    in: 0...20)
            OutreachNumberField(
                title: "편도 이동 시간",
                value: Binding { change?.travelMinutes ?? inputs.travelMinutes } set: { adjust { $0.travelMinutes = $1 }($0) },
                unit: "분", identifier: "outreach.adjustTravel")
            if quote.calculation.travelUnknown {
                Text("이동 시간이나 거리를 직접 입력해 주세요.")
                    .font(.subheadline)
                    .foregroundStyle(Color.secondaryText)
            }
        } header: {
            Text("조건 바꿔 보기")
        } footer: {
            Text("바꾸면 서버가 바로 다시 계산해요.")
        }
    }

    private func adjust<Value>(_ write: @escaping (inout OutreachAdjustment, Value) -> Void) -> (Value) -> Void {
        { value in
            var next = change ?? OutreachAdjustment()
            write(&next, value)
            change = next
        }
    }

    // MARK: Cells

    private func linesSection(_ quote: OutreachQuote) -> some View {
        let result = quote.calculation
        return CardSection("네 칸 견적") {
            ForEach(result.lines) { line in
                DisclosureGroup {
                    Text(verbatim: line.formula)
                        .font(.subheadline)
                        .foregroundStyle(Color.secondaryText)
                } label: {
                    LabeledContent(line.label) {
                        Text(OutreachFormat.won(line.amountKrw))
                            .monospacedDigit()
                            .foregroundStyle(Color.secondaryText)
                    }
                }
            }
            LabeledContent("합계") {
                Text(OutreachFormat.won(result.totalKrw)).font(.headline).monospacedDigit()
            }
            OutreachValueRow(title: "1인 단가", value: OutreachFormat.won(result.perPersonKrw))
            if result.instructorGapKrw < 0 {
                Text("기준 강사비보다 \(OutreachFormat.won(-result.instructorGapKrw)) 적어요.")
                    .font(.subheadline)
            }
        }
    }

    private func conflictSection(_ quote: OutreachQuote) -> some View {
        CardSection("비워야 하는 일정") {
            ForEach(quote.conflicts) { conflict in
                LabeledContent {
                    Text(conflict.lostKrw.map { "-\(OutreachFormat.won($0))" } ?? "원가 없음")
                        .monospacedDigit()
                } label: {
                    Text(verbatim: conflict.title)
                    Text("\(conflict.time) · 예약 \(conflict.bookedCount)명")
                        .foregroundStyle(Color.secondaryText)
                }
            }
        }
    }

    // MARK: Reply, follow-up, outcome

    private func replySection(_ quote: OutreachQuote) -> some View {
        CardSection {
            // The editor has no height of its own, so hidden copy of the text sizes the row at every text size.
            // The extra lines leave room for the caret and for word wrapping that differs by a line.
            Text(verbatim: reply + "\n\n")
                .frame(maxWidth: .infinity, minHeight: 160, alignment: .topLeading)
                .fixedSize(horizontal: false, vertical: true)
                .hidden()
                .overlay { KoreanTextEditor(text: Binding { reply } set: { reply = $0; replyIsEdited = true }) }
                .accessibilityLabel("회신 초안")
                .accessibilityIdentifier("outreach.reply")
            Button("회신 복사하기") {
                UIPasteboard.general.string = reply
                app.showToast("복사했어요")
            }
            .buttonStyle(.bordered)
            .accessibilityIdentifier("outreach.copyReply")
        } header: {
            Text("회신 초안")
        } footer: {
            Text("보내는 일은 직접 해요. 복사해서 문자나 메일로 보내 주세요.")
        }
    }

    private func followUpSection(_ quote: OutreachQuote) -> some View {
        CardSection("답이 없으면 다시 연락") {
            if let due = quote.followUpDue {
                DueLabel(due: due)
            }
            DatePicker("다시 연락할 때", selection: $followUp)
                .environment(\.timeZone, Calendar.workshop.timeZone)
            Button {
                remind(quote)
            } label: {
                BusyLabel(title: quote.followUpDue == nil ? "오늘 탭에 할 일 걸기" : "시각 바꾸기", isBusy: app.isRunning(runID))
            }
            .buttonStyle(.bordered)
            .disabled(quote.locked || app.isRunning(runID))
            .accessibilityIdentifier("outreach.remind")
        }
    }

    private func outcomeSection(_ quote: OutreachQuote) -> some View {
        CardSection("기관의 답") {
            HStack {
                StatusBadge(quote.status.badge)
                Spacer()
                if let total = quote.finalTotalKrw {
                    Text(OutreachFormat.won(total)).monospacedDigit()
                }
            }
            Menu("결과 고르기") {
                ForEach(OutreachOutcome.allCases) { outcome in
                    Button(outcome.label) {
                        if outcome == .acceptedAdjusted {
                            finalTotal = quote.calculation.totalKrw
                            asksFinalTotal = true
                        } else {
                            record(outcome)
                        }
                    }
                }
            }
            .menuStyle(.button)
            .buttonStyle(.bordered)
            .accessibilityIdentifier("outreach.outcome")
        }
    }

    // MARK: Work

    private func load() async {
        await loader.load { try await RoundupAPI.outreachQuote(id: opened.id) }
        guard let quote = loader.value else { return }
        adjusted = nil
        if !quote.missingCosts.isEmpty {
            // Costs may have been entered since the quote was made; an empty change recomputes it.
            adjusted = try? await RoundupAPI.recalculateOutreachQuote(id: opened.id, OutreachAdjustment())
        }
        show(adjusted ?? quote)
    }

    private func show(_ quote: OutreachQuote) {
        if !replyIsEdited { reply = quote.replyDraft }
        if let due = quote.followUpDue?.date ?? (try? Date(quote.followUpAt, strategy: .iso8601)) { followUp = due }
    }

    /// Quick taps settle for a moment, so only the last value is sent.
    private func recalculate() async {
        guard let change else { return }
        isRecalculating = true
        defer { isRecalculating = false }
        do {
            try await Task.sleep(for: .milliseconds(300))
            let quote = try await RoundupAPI.recalculateOutreachQuote(id: opened.id, change)
            adjusted = quote
            show(quote)
        } catch is CancellationError {
            return
        } catch {
            app.failureMessage = error.localizedDescription
        }
    }

    private func verify(_ quote: OutreachQuote) {
        Task { await app.run(id: runID) { try await RoundupAPI.verifyOutreachOrg(id: quote.id) } }
    }

    private func shared(_ quote: OutreachQuote, seconds: Int?) {
        Task {
            await app.run(id: runID) {
                _ = try await RoundupAPI.markOutreachSent(id: quote.id, elapsedSeconds: seconds, followUpAt: nil)
            }
        }
    }

    private func remind(_ quote: OutreachQuote) {
        let moment = followUp
        Task {
            if await app.run(id: runID, {
                _ = try await RoundupAPI.markOutreachSent(id: quote.id, elapsedSeconds: nil, followUpAt: moment)
            }) { app.showToast("오늘 탭에 할 일을 걸었어요") }
        }
    }

    private func record(_ outcome: OutreachOutcome) {
        let total = outcome == .acceptedAdjusted ? finalTotal : nil
        Task {
            let saved = await app.run(id: runID) {
                _ = try await RoundupAPI.recordOutreachOutcome(id: opened.id, outcome: outcome, finalTotal: total)
            }
            let accepted = outcome == .accepted || outcome == .acceptedAdjusted
            if saved, accepted, loader.value?.fields.date != nil { offersEvent = true }
        }
    }

    private func addEvent() {
        guard let quote = loader.value, let day = quote.fields.date else { return }
        let start = quote.fields.timeRange?.split(separator: "-").first.map(String.init) ?? "09:00"
        guard let lesson = OutreachFormat.moment(day: day, clock: start) else { return }
        let travel = quote.inputs.travelMinutes ?? 0
        let detail = "\(quote.fields.timeRange ?? "시간 확인 필요") 수업, 앞뒤 이동 각 \(travel)분"
        let departure = lesson.addingTimeInterval(TimeInterval(-60 * travel))
        Task {
            if await app.run(id: runID, {
                try await RoundupAPI.createEvent(title: "\(quote.title) 출강", kind: .booking, detail: detail, startsAt: departure)
            }) { app.showToast("캘린더에 넣었어요") }
        }
    }
}
#endif
