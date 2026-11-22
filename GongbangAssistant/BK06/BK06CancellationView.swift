import SwiftUI
import UIKit

/// Paste a message, pick the booking, decide, and copy the reply. Nothing is sent and no money moves.
struct BK06CancellationView: View {
    @State private var message = ""
    @State private var pastedAt = Date.now
    @State private var intake: BK06Intake?
    @State private var isBusy = false
    @State private var errorMessage: String?
    @State private var selected: BK06Candidate?

    private var trimmed: String { message.trimmingCharacters(in: .whitespacesAndNewlines) }

    var body: some View {
        List {
            CardSection {
                TextField("손님한테 받은 취소 문자를 여기에 붙여 넣어 주세요", text: $message, axis: .vertical)
                    .lineLimit(4...12)
                    .accessibilityLabel("손님이 보낸 문자")
                    .accessibilityIdentifier("k06.message")
                PasteButton(payloadType: String.self) { values in
                    Task { @MainActor in message = values.first ?? "" }
                }
            } header: {
                Text("손님이 보낸 문자")
            } footer: {
                Text("붙여 넣으신 문자는 예약 찾을 때만 쓰고 어디에도 남기지 않아요.")
            }
            if let errorMessage {
                CardSection { BK06ErrorRow(message: errorMessage) }
            }
            if let intake {
                results(intake)
            }
            CardSection {
                BK06PrimaryButton(title: "예약 찾아보기", isBusy: isBusy, identifier: "k06.find") { find() }
                    .disabled(trimmed.isEmpty)
            }
        }
        .cardList()
        .navigationTitle("손님이 보낸 취소 문자")
        .navigationBarTitleDisplayMode(.inline)
        .navigationDestination(item: $selected) { booking in
            BK06QuoteView(booking: booking, category: intake?.reasonCategory, pastedAt: pastedAt)
        }
    }

    @ViewBuilder
    private func results(_ intake: BK06Intake) -> some View {
        if intake.candidates.isEmpty {
            CardSection {
                Text("이 문자에 맞는 예약이 안 보여요")
                    .accessibilityIdentifier("k06.notFound")
                ForEach(intake.recent) { candidateRow($0) }
            } footer: {
                Text(intake.recent.isEmpty ? "다음 7일 동안은 잡혀 있는 예약이 하나도 없어요." : "다음 7일 안의 목록에서 하나 골라 주세요.")
            }
        } else {
            CardSection(intake.candidates.count > 1 ? "어떤 예약 말씀이세요?" : "이 예약 같아요") {
                ForEach(intake.candidates) { candidateRow($0) }
            }
        }
    }

    private func candidateRow(_ item: BK06Candidate) -> some View {
        Button { selected = item } label: {
            VStack(alignment: .leading, spacing: 4) {
                Text("\(item.customerName) 님 · \(item.seats)명").font(.headline)
                PhraseText(text: "\(item.classTitle) · \(BK06Format.when(item.sessionStartsAt))")
                    .font(.subheadline)
                    .foregroundStyle(Color.secondaryText)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .contentShape(.rect)
        }
        .foregroundStyle(Color.primary)
        .accessibilityIdentifier("k06.candidate.\(item.bookingId)")
    }

    private func find() {
        isBusy = true
        errorMessage = nil
        pastedAt = .now
        Task {
            do {
                let found = try await RoundupAPI.k06Intake(message: trimmed)
                intake = found
                if found.candidates.count == 1 { selected = found.candidates[0] }
            } catch {
                errorMessage = error.localizedDescription
            }
            isBusy = false
        }
    }
}

struct BK06QuoteView: View {
    let booking: BK06Candidate
    let category: String?
    let pastedAt: Date
    @State private var loader = Loader<BK06Quote>()
    @State private var shownAt: Date?
    @State private var decision: BK06Decision = .byRule
    @State private var reason = ""
    @State private var customWon = ""
    @State private var result: BK06DecisionResult?
    @State private var draft = ""
    @State private var isFresh = false
    @State private var isWriting = false
    @State private var usedFixedText = false
    @State private var isApproved = false
    @State private var isBusy = false
    @State private var errorMessage: String?
    @Environment(AppModel.self) private var app

    var body: some View {
        LoadableContent(loader: loader, retry: load) { quote in
            List {
                header(quote)
                if quote.policyVersion != nil { calculation(quote) }
                precedents(quote)
                if result == nil {
                    decisionSection(quote)
                } else {
                    draftSection
                }
            }
            .cardList()
        }
        .navigationTitle("취소 정리하기")
        .navigationBarTitleDisplayMode(.inline)
        .task { await load() }
        // The tab reloads only once this card is left, so its own row cannot be pulled away.
        .onDisappear { if result != nil { app.dataDidChange() } }
    }

    private func load() async {
        guard result == nil else { return }
        await loader.load { try await RoundupAPI.k06Quote(bookingID: booking.bookingId, category: category) }
        if loader.value != nil, shownAt == nil { shownAt = .now }
        if let quote = loader.value, quote.refund == nil, decision == .byRule { decision = .custom }
    }

    private func header(_ quote: BK06Quote) -> some View {
        CardSection {
            VStack(alignment: .leading, spacing: 4) {
                Text("\(quote.customerName) 님").font(.headline)
                PhraseText(text: "\(quote.classTitle) · \(BK06Format.when(quote.sessionStartsAt))")
                    .font(.subheadline)
                    .foregroundStyle(Color.secondaryText)
            }
            if let version = quote.policyVersion {
                NavigationLink { BK06PolicyView() } label: {
                    Text(verbatim: basis(quote, version))
                }
                .accessibilityIdentifier("k06.basis")
            }
            ForEach(quote.warnings, id: \.self) { warning in
                if warning == .noPolicy {
                    NavigationLink { BK06PolicyView() } label: { Text(verbatim: warning.text) }
                } else if warning == .unreadRule {
                    NavigationLink { BK06PolicyView() } label: {
                        VStack(alignment: .leading, spacing: 6) {
                            Text(verbatim: warning.text)
                            ForEach(quote.unread, id: \.self) { BK06PendingLabel(text: $0) }
                        }
                    }
                    .accessibilityIdentifier("k06.unread")
                } else {
                    Label { Text(verbatim: warning.text) } icon: { Image(systemName: "info.circle") }
                        .font(.subheadline)
                        .foregroundStyle(Color.secondaryText)
                }
            }
        }
    }

    private func basis(_ quote: BK06Quote, _ version: Int) -> String {
        guard let noticed = quote.noticedAt else { return "현재 \(version)번째 규정으로 계산" }
        return "\(BK06Format.day(noticed + "T00:00:00+09:00"))에 손님께 보여 드린 \(version)번째 규정으로 계산"
    }

    private func calculation(_ quote: BK06Quote) -> some View {
        CardSection {
            BK06ValueRow(label: "수업까지 남은 날", value: quote.daysLeft <= 0 ? "수업 당일" : "수업 \(quote.daysLeft)일 전")
            BK06ValueRow(label: "손님이 낸 예약금", value: BK06Format.won(quote.paid))
            BK06ValueRow(label: "돌려드릴 금액", value: quote.refund.map(BK06Format.won) ?? "사장님이 직접 정하기", tag: "미리 계산해 본 금액")
                .accessibilityIdentifier("k06.refund")
            if let label = quote.matchedLabel { BK06ValueRow(label: "계산 기준", value: label) }
        } header: {
            Text("계산 과정")
        } footer: {
            BK06Disclaimer()
        }
    }

    @ViewBuilder
    private func precedents(_ quote: BK06Quote) -> some View {
        if !quote.precedents.isEmpty {
            CardSection("예전에 비슷했던 일") {
                ForEach(quote.precedents) { item in
                    VStack(alignment: .leading, spacing: 4) {
                        Text(verbatim: item.reason)
                        Text("\(BK06Format.day(item.decidedAt)) · \(item.decision.title)")
                            .font(.subheadline)
                            .foregroundStyle(Color.secondaryText)
                    }
                }
            }
        }
    }

    private func decisionSection(_ quote: BK06Quote) -> some View {
        CardSection {
            Picker("어떻게 할까요", selection: $decision) {
                ForEach(BK06Decision.allCases.filter { $0 != .byRule || quote.refund != nil }) { item in
                    Text(verbatim: item.title).tag(item)
                }
            }
            .accessibilityIdentifier("k06.decision")
            if decision == .custom {
                TextField("돌려드릴 금액(원)", text: $customWon)
                    .keyboardType(.numberPad)
                    .accessibilityIdentifier("k06.customWon")
            }
            if decision != .byRule {
                TextField("규정과 다르게 정하신 이유", text: $reason)
                    .accessibilityIdentifier("k06.reason")
            }
            if let errorMessage { BK06ErrorRow(message: errorMessage) }
            BK06PrimaryButton(title: "정하고 답장 초안 받기", isBusy: isBusy, identifier: "k06.decide") { decide(quote) }
                .disabled(!canDecide(quote))
        } header: {
            Text("어떻게 할까요")
        } footer: {
            Text("이 예약은 정하시는 순간 취소돼요. 환불금 송금은 앱이 하지 않아요.")
        }
    }

    private func canDecide(_ quote: BK06Quote) -> Bool {
        guard decision != .byRule else { return quote.refund != nil }
        guard !reason.trimmingCharacters(in: .whitespaces).isEmpty else { return false }
        guard decision == .custom else { return true }
        return Int(customWon).map { (0...quote.paid).contains($0) } ?? false
    }

    private var draftSection: some View {
        CardSection {
            if isWriting {
                GeneratingIndicator(label: "답장 초안을 준비하는 중이에요")
            } else {
                KoreanTextEditor(text: $draft, isFresh: $isFresh)
                    .frame(minHeight: 140)
                    .disabled(isApproved)
                    .accessibilityLabel("답장 초안")
                    .accessibilityIdentifier("k06.draft")
                if usedFixedText && !isApproved {
                    Text("비서가 답장을 못 써서 미리 준비해 둔 기본 문장으로 채웠어요.")
                        .font(.subheadline)
                        .foregroundStyle(Color.secondaryText)
                    Button("다시 쓰기") { Task { await write() } }
                        .buttonStyle(.bordered)
                }
            }
            if let errorMessage { BK06ErrorRow(message: errorMessage) }
            if isApproved {
                Button("한 번 더 복사", systemImage: "doc.on.doc") { UIPasteboard.general.string = draft }
                    .buttonStyle(.bordered)
                if let result, result.seatOpened {
                    NavigationLink("빈자리 찾아보기") { BK06RefillView(sessionID: result.sessionId) }
                        .accessibilityIdentifier("k06.openRefill")
                }
            } else {
                BK06PrimaryButton(title: "수락하고 복사하기", isBusy: isBusy, identifier: "k06.approve") { approve() }
                    .disabled(isWriting || draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
            }
        } header: {
            // The assistant's label is kept for text it really wrote.
            if isWriting || usedFixedText {
                Text("답장 초안")
            } else {
                Text("비서가 준비한 답장")
                    .foregroundStyle(Color.assistantAccent)
            }
        } footer: {
            Text("평소 쓰시는 채널에 붙여서 사장님이 직접 보내 주세요.")
        }
    }

    private func decide(_ quote: BK06Quote) {
        isBusy = true
        errorMessage = nil
        Task {
            do {
                let decided = try await RoundupAPI.k06Decide(bookingID: quote.bookingId, body: .init(
                    decision: decision, reason: decision == .byRule ? "" : reason, reasonCategory: category,
                    refundWon: decision == .custom ? Int(customWon) : nil, expectedRevision: quote.revision,
                    pastedAt: pastedAt.ISO8601Format(), cardShownAt: (shownAt ?? pastedAt).ISO8601Format()))
                result = decided
                draft = decided.draft
                isBusy = false
                showUndo(decided.caseId)
                await write()
            } catch {
                errorMessage = error.localizedDescription
                isBusy = false
            }
        }
    }

    private func showUndo(_ caseID: String) {
        app.showToast("‘\(booking.customerName) 님’ 예약을 취소했어요") {
            guard await app.run(id: "k06.undo", { try await RoundupAPI.k06UndoDecision(caseID: caseID) }) else { return }
            result = nil
            isApproved = false
            await load()
        }
    }

    /// The calculation and the fixed sentence stay when the model or the network fails.
    private func write() async {
        guard let result else { return }
        isWriting = true
        do {
            let written = try await RoundupAPI.k06Draft(caseID: result.caseId)
            usedFixedText = written.source == "rules"
            isFresh = !usedFixedText
            draft = written.draft
        } catch {
            usedFixedText = true
        }
        isWriting = false
    }

    private func approve() {
        guard let result else { return }
        let text = draft
        isBusy = true
        errorMessage = nil
        Task {
            do {
                try await RoundupAPI.k06Approve(caseID: result.caseId, draft: text)
                UIPasteboard.general.string = text
                isApproved = true
                app.showToast("복사 끝! 카톡이든 문자든 평소 쓰시는 채널에 붙여 보내 주세요", seconds: 3)
            } catch {
                errorMessage = error.localizedDescription
            }
            isBusy = false
        }
    }
}
