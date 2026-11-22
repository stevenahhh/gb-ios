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
        .navigationTitle((adjusted ?? loader.value)?.title ?? "출장 수업 견적")
        .navigationBarTitleDisplayMode(.inline)
        .task(id: app.dataVersion) { await load() }
        .task(id: change) { await recalculate() }
        .sheet(isPresented: $isPreviewing) {
            if let quote = adjusted ?? loader.value {
                OutreachPDFPreview(quote: quote) { seconds in shared(quote, seconds: seconds) } startedAt: { opened.startedAt }
            }
        }
        .alert("조정한 뒤 합계", isPresented: $asksFinalTotal) {
            TextField("총액", value: $finalTotal, format: .number).keyboardType(.numberPad)
            Button("취소", role: .cancel) {}
            Button("저장") { record(.acceptedAdjusted) }
                .disabled((finalTotal ?? 0) <= 0)
        }
        .alert("출장 수업 일정을 캘린더에 넣어 둘까요?", isPresented: $offersEvent) {
            Button("다음에 할게요", role: .cancel) {}
            Button("만들기") { addEvent() }
        } message: {
            Text("떠나실 시각은 이동 시간만큼 앞당겨 넣어 둬요.")
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
                Text("견적서 뽑기")
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
        return CardSection("맡아도 될까요") {
            if result.verdict == .unknown {
                Text("재료비와 시간이 비어 있어서 아직 따져 볼 수 없어요").font(.headline)
                    .accessibilityIdentifier("outreach.verdict")
                NavigationLink {
                    ClassCostListView()
                } label: {
                    Label { Text("재료비와 시간 채우기") } icon: { MenuIcon(systemName: "square.and.pencil") }
                }
                .accessibilityIdentifier("outreach.enterCosts")
            } else {
                VStack(alignment: .leading, spacing: 6) {
                    Text(result.verdict == .better ? "원데이 클래스보다 더 남아요" : "원데이 클래스보다 덜 남아요")
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
                OutreachValueRow(title: "1인당 남는 돈", value: OutreachFormat.won(result.netPerPersonOutreach))
                OutreachValueRow(title: "원데이 클래스 1인당 남는 돈", value: OutreachFormat.won(result.netPerPersonOneday))
                if let outreach = result.netPerHourOutreach, let oneday = result.netPerHourOneday {
                    OutreachValueRow(title: "한 시간에 남는 돈", value: OutreachFormat.won(outreach))
                    OutreachValueRow(title: "원데이 클래스 한 시간에 남는 돈", value: OutreachFormat.won(oneday))
                }
                if let minimum = result.breakEvenHeadcount {
                    OutreachValueRow(title: "최소 인원", value: "1인 \(OutreachFormat.won(result.perPersonKrw))이라면 적어도 \(minimum)명")
                }
                if let limit = result.maxHeadcount, let budget = quote.fields.budgetKrw {
                    OutreachValueRow(title: "예산에 맞는 인원", value: "\(OutreachFormat.won(budget))이라면 \(limit)명까지 가능")
                }
                if result.verdict == .worse, let needed = result.neededTotalKrw {
                    OutreachValueRow(title: "이 인원으로 받아야 할 합계", value: OutreachFormat.won(needed))
                }
            }
        }
    }

    private func suggestion(_ result: OutreachCalculation) -> String {
        switch result.suggestion {
        case .accept: "맡으시는 걸 추천해요."
        case .raise: "맡으시려면 최소 인원이나 금액을 올리시길 권해요."
        case .decline: "이번엔 정중하게 거절하시길 권해요."
        case .unknown: ""
        }
    }

    // MARK: Adjust

    private func adjustSection(_ quote: OutreachQuote) -> some View {
        let inputs = quote.inputs
        return CardSection {
            Stepper("\(change?.headcount ?? inputs.headcount)명이 온다면",
                    value: Binding { change?.headcount ?? inputs.headcount } set: { adjust { $0.headcount = $1 }($0) },
                    in: 1...1000)
                .accessibilityIdentifier("outreach.stepHeadcount")
            let perPerson = change?.perPersonKrw ?? inputs.perPersonKrw ?? quote.calculation.perPersonKrw
            Stepper("1인 \(OutreachFormat.won(perPerson))",
                    value: Binding { perPerson } set: { adjust { $0.perPersonKrw = $1 }($0) },
                    in: 1000...1_000_000, step: 1000)
                .accessibilityIdentifier("outreach.stepPrice")
            Stepper("보조 강사 \(change?.assistants ?? inputs.assistants)명이라면",
                    value: Binding { change?.assistants ?? inputs.assistants } set: { adjust { $0.assistants = $1 }($0) },
                    in: 0...20)
            OutreachNumberField(
                title: "가는 데 걸리는 시간(편도)",
                value: Binding { change?.travelMinutes ?? inputs.travelMinutes } set: { adjust { $0.travelMinutes = $1 }($0) },
                unit: "분", identifier: "outreach.adjustTravel")
            if quote.calculation.travelUnknown {
                Text("가는 데 걸리는 시간이나 거리를 손으로 채워 주세요.")
                    .font(.subheadline)
                    .foregroundStyle(Color.secondaryText)
            }
        } header: {
            Text("조건 바꿔서 다시 계산")
        } footer: {
            Text("조건을 바꾸면 금액을 바로 다시 계산해 드려요.")
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
        return CardSection("견적 네 가지 보기") {
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
            OutreachValueRow(title: "1인당 가격", value: OutreachFormat.won(result.perPersonKrw))
            if result.instructorGapKrw < 0 {
                Text("평소 강사비에 \(OutreachFormat.won(-result.instructorGapKrw))만큼 못 미쳐요.")
                    .font(.subheadline)
            }
        }
    }

    private func conflictSection(_ quote: OutreachQuote) -> some View {
        CardSection("비워 둬야 하는 일정") {
            ForEach(quote.conflicts) { conflict in
                LabeledContent {
                    Text(conflict.lostKrw.map { "-\(OutreachFormat.won($0))" } ?? "원가 없음")
                        .monospacedDigit()
                } label: {
                    Text(verbatim: conflict.title)
                    Text("\(conflict.time) · \(conflict.bookedCount)명 예약돼 있어요")
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
                .accessibilityLabel("기관에 보낼 답장 초안")
                .accessibilityIdentifier("outreach.reply")
            Button("답장 복사하기") {
                UIPasteboard.general.string = reply
                app.showToast("복사 끝!")
            }
            .buttonStyle(.bordered)
            .accessibilityIdentifier("outreach.copyReply")
        } header: {
            Text("기관에 보낼 답장 초안")
        } footer: {
            Text("앱이 대신 전송하는 일은 없어요. 글을 복사해 문자나 메일에 붙여서 사장님이 직접 보내 주세요.")
        }
    }

    private func followUpSection(_ quote: OutreachQuote) -> some View {
        CardSection("답이 없으면 한 번 더 연락하기") {
            if let due = quote.followUpDue {
                DueLabel(due: due)
            }
            DatePicker("다시 연락드릴 시간", selection: $followUp)
                .environment(\.timeZone, Calendar.workshop.timeZone)
            Button {
                remind(quote)
            } label: {
                BusyLabel(title: quote.followUpDue == nil ? "오늘 화면 할 일에 추가" : "시각 바꾸기", isBusy: app.isRunning(runID))
            }
            .buttonStyle(.bordered)
            .disabled(quote.locked || app.isRunning(runID))
            .accessibilityIdentifier("outreach.remind")
        }
    }

    private func outcomeSection(_ quote: OutreachQuote) -> some View {
        CardSection("기관에서 온 답") {
            HStack {
                StatusBadge(quote.status.badge)
                Spacer()
                if let total = quote.finalTotalKrw {
                    Text(OutreachFormat.won(total)).monospacedDigit()
                }
            }
            Menu("어떻게 됐는지 고르기") {
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
            }) { app.showToast("오늘 화면 할 일 목록에 넣어 뒀어요") }
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
        let detail = "\(quote.fields.timeRange ?? "시간 확인 필요") 수업 · 가고 오는 데 각각 \(travel)분"
        let departure = lesson.addingTimeInterval(TimeInterval(-60 * travel))
        Task {
            if await app.run(id: runID, {
                try await RoundupAPI.createEvent(title: "\(quote.title) 출장 수업", kind: .booking, detail: detail, startsAt: departure)
            }) { app.showToast("캘린더에 넣어 뒀어요") }
        }
    }
}
