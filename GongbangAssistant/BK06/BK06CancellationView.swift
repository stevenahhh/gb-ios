#if BUILD_B
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
                TextField("손님이 보낸 글을 붙여넣어 주세요", text: $message, axis: .vertical)
                    .lineLimit(4...12)
                    .accessibilityLabel("손님 메시지")
                    .accessibilityIdentifier("k06.message")
                PasteButton(payloadType: String.self) { values in
                    Task { @MainActor in message = values.first ?? "" }
                }
            } header: {
                Text("손님 메시지")
            } footer: {
                Text("메시지는 예약을 찾는 데만 쓰고 저장하지 않아요.")
            }
            if let errorMessage {
                CardSection { BK06ErrorRow(message: errorMessage) }
            }
            if let intake {
                results(intake)
            }
            CardSection {
                BK06PrimaryButton(title: "예약 찾기", isBusy: isBusy, identifier: "k06.find") { find() }
                    .disabled(trimmed.isEmpty)
            }
        }
        .cardList()
        .navigationTitle("취소 메시지")
        .navigationBarTitleDisplayMode(.inline)
        .navigationDestination(item: $selected) { booking in
            BK06QuoteView(booking: booking, category: intake?.reasonCategory, pastedAt: pastedAt)
        }
    }

    @ViewBuilder
    private func results(_ intake: BK06Intake) -> some View {
        if intake.candidates.isEmpty {
            CardSection {
                Text("이 메시지와 맞는 예약을 찾지 못했어요")
                    .accessibilityIdentifier("k06.notFound")
                ForEach(intake.recent) { candidateRow($0) }
            } footer: {
                Text(intake.recent.isEmpty ? "앞으로 7일 안에 잡힌 예약이 없어요." : "앞으로 7일 예약에서 직접 골라 주세요.")
            }
        } else {
            CardSection(intake.candidates.count > 1 ? "어느 예약인가요?" : "찾은 예약") {
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
        .navigationTitle("취소 카드")
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
        guard let noticed = quote.noticedAt else { return "지금 규정 \(version)판 기준" }
        return "\(BK06Format.day(noticed + "T00:00:00+09:00"))에 안내한 규정 \(version)판 기준"
    }

    private func calculation(_ quote: BK06Quote) -> some View {
        CardSection {
            BK06ValueRow(label: "남은 기간", value: quote.daysLeft <= 0 ? "당일" : "\(quote.daysLeft)일 전")
            BK06ValueRow(label: "낸 예약금", value: BK06Format.won(quote.paid))
            BK06ValueRow(label: "환불액", value: quote.refund.map(BK06Format.won) ?? "사장님 판단", tag: "참고 계산")
                .accessibilityIdentifier("k06.refund")
            if let label = quote.matchedLabel { BK06ValueRow(label: "근거", value: label) }
        } header: {
            Text("계산")
        } footer: {
            BK06Disclaimer()
        }
    }

    @ViewBuilder
    private func precedents(_ quote: BK06Quote) -> some View {
        if !quote.precedents.isEmpty {
            CardSection("지난번 비슷한 경우") {
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
            Picker("결정", selection: $decision) {
                ForEach(BK06Decision.allCases.filter { $0 != .byRule || quote.refund != nil }) { item in
                    Text(verbatim: item.title).tag(item)
                }
            }
            .accessibilityIdentifier("k06.decision")
            if decision == .custom {
                TextField("환불할 금액(원)", text: $customWon)
                    .keyboardType(.numberPad)
                    .accessibilityIdentifier("k06.customWon")
            }
            if decision != .byRule {
                TextField("규정과 다르게 정한 이유", text: $reason)
                    .accessibilityIdentifier("k06.reason")
            }
            if let errorMessage { BK06ErrorRow(message: errorMessage) }
            BK06PrimaryButton(title: "결정하고 초안 만들기", isBusy: isBusy, identifier: "k06.decide") { decide(quote) }
                .disabled(!canDecide(quote))
        } header: {
            Text("결정")
        } footer: {
            Text("결정하면 이 예약이 취소로 바뀌어요. 돈은 앱이 보내지 않아요.")
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
                GeneratingIndicator(label: "답장 초안을 쓰고 있어요")
            } else {
                KoreanTextEditor(text: $draft, isFresh: $isFresh)
                    .frame(minHeight: 140)
                    .disabled(isApproved)
                    .accessibilityLabel("답장 초안")
                    .accessibilityIdentifier("k06.draft")
                if usedFixedText && !isApproved {
                    Text("비서가 글을 쓰지 못해 정해 둔 문장을 넣었어요.")
                        .font(.subheadline)
                        .foregroundStyle(Color.secondaryText)
                    Button("다시 쓰기") { Task { await write() } }
                        .buttonStyle(.bordered)
                }
            }
            if let errorMessage { BK06ErrorRow(message: errorMessage) }
            if isApproved {
                Button("다시 복사하기", systemImage: "doc.on.doc") { UIPasteboard.general.string = draft }
                    .buttonStyle(.bordered)
                if let result, result.seatOpened {
                    NavigationLink("빈자리 보기") { BK06RefillView(sessionID: result.sessionId) }
                        .accessibilityIdentifier("k06.openRefill")
                }
            } else {
                BK06PrimaryButton(title: "승인하고 복사", isBusy: isBusy, identifier: "k06.approve") { approve() }
                    .disabled(isWriting || draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
            }
        } header: {
            // The assistant's label is kept for text it really wrote.
            if isWriting || usedFixedText {
                Text("답장 초안")
            } else {
                Label { Text("비서가 쓴 답변") } icon: { AssistantFace(size: .card) }
                    .foregroundStyle(Color.assistantAccent)
            }
        } footer: {
            Text("복사한 글은 쓰시는 채널에서 직접 보내 주세요.")
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
        app.showToast("‘\(booking.customerName) 님’ 취소했어요") {
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
                app.showToast("복사했어요. 쓰시는 채널에서 보내 주세요", seconds: 3)
            } catch {
                errorMessage = error.localizedDescription
            }
            isBusy = false
        }
    }
}
#endif
