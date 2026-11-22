import SwiftUI

/// 근거: where each number in the reply comes from. A number that differs from the ledger locks 답변 완료 until it is
/// fixed, or until the owner says why it should go out as it is.
struct BK25GroundingSection: View {
    let grounding: BK25Grounding
    let inquiryID: String
    @Binding var draft: String
    let approve: () -> Void
    /// Puts text the assistant just wrote into the editor.
    let showDraft: (String) -> Void
    @State private var isAskingReason = false
    @State private var isAnswering = false

    private static let overrideReasons = ["장부가 아직 안 맞아요", "손님과 따로 정했어요", "다른 이유예요"]

    var body: some View {
        if grounding.loadFailed && grounding.arm == nil {
            CardSection {
                LabeledContent {
                    Button("다시 시도") {
                        Task { await grounding.load(inquiryID, draft: draft) }
                    }
                } label: {
                    Text("근거를 불러오지 못했어요")
                        .foregroundStyle(Color.secondaryText)
                }
                .accessibilityIdentifier("bk25.loadFailed")
            }
        }
        if let judgment = grounding.judgment {
            judgmentCard(judgment)
        }
        if grounding.isGrounded {
            CardSection {
                VStack(alignment: .leading, spacing: 6) {
                    summary
                    if !grounding.isVerifying && !grounding.checkedKinds.isEmpty {
                        Text(verbatim: "맞춰 본 숫자: \(grounding.checkedKinds.joined(separator: ", "))")
                            .font(.subheadline)
                            .foregroundStyle(Color.secondaryText)
                            .accessibilityIdentifier("bk25.checkedKinds")
                    }
                }
                .task(id: draft) { await verifyAfterTyping() }
                ForEach(Array(grounding.claims.enumerated()), id: \.offset) { index, claim in
                    ClaimRow(claim: claim, index: index) {
                        draft = grounding.replacing(claim, in: draft)
                    }
                }
            } header: {
                Text("근거")
            } footer: {
                Text("가격, 예약금, 할인, 남은 자리, 날짜, 요일, 시각, 수업 길이, 정원과 주차·환불·재료의 숫자만 맞춰 봐요. 나머지 내용은 확인하지 않으니 보내기 전에 한 번 더 읽어 주세요.")
            }
        }
    }

    private func judgmentCard(_ judgment: BK25Judgment) -> some View {
        CardSection {
            VStack(alignment: .leading, spacing: 6) {
                HStack(alignment: .firstTextBaseline, spacing: 6) {
                    Circle()
                        .fill(Color.pendingOrange)
                        .frame(width: 7, height: 7)
                        .accessibilityHidden(true)
                    Text(verbatim: judgment.issue)
                        .font(.headline)
                }
                Text(verbatim: "장부와 카드로 답할 수 없는 질문이에요. 한 줄로 답해 주시면 답장을 써 드려요.")
                    .font(.subheadline)
                    .foregroundStyle(Color.secondaryText)
                Button("답하기") { isAnswering = true }
                    .buttonStyle(.bordered)
                    .controlSize(.large)
                    .accessibilityIdentifier("bk25.judgment.answer")
                    .sheet(isPresented: $isAnswering) {
                        BK25JudgmentSheet(judgment: judgment) { answer in
                            grounding.apply(answer)
                            if !answer.draft.isEmpty { showDraft(answer.draft) }
                        }
                    }
            }
            .padding(.vertical, 4)
        } header: {
            Text("판단 필요")
        }
    }

    @ViewBuilder
    private var summary: some View {
        if grounding.isVerifying {
            HStack(spacing: 10) {
                ProgressView()
                Text("장부와 맞춰 보는 중이에요")
            }
            .font(.subheadline)
            .foregroundStyle(Color.secondaryText)
        } else {
            switch grounding.lock {
            case .locked:
                HStack(alignment: .firstTextBaseline, spacing: 8) {
                    // An identifier on the row would replace the menu's own.
                    Label("숫자 \(grounding.mismatchCount)개가 장부와 달라요", systemImage: "exclamationmark.triangle.fill")
                        .font(.headline)
                        .accessibilityIdentifier("bk25.locked")
                    Spacer(minLength: 8)
                    // Kept behind a menu, so a reply is never sent past the check by one mistaken tap.
                    Menu {
                        Button("이번만 그대로 보내기") { isAskingReason = true }
                    } label: {
                        Image(systemName: "ellipsis.circle")
                            .accessibilityLabel("더 보기")
                    }
                    .accessibilityIdentifier("bk25.more")
                }
                .confirmationDialog("장부와 다른 그대로 보낼까요?", isPresented: $isAskingReason, titleVisibility: .visible) {
                    ForEach(Self.overrideReasons, id: \.self) { reason in
                        Button(reason) {
                            grounding.overrideReason = reason
                            approve()
                        }
                    }
                    Button("취소", role: .cancel) {}
                } message: {
                    Text("이유를 남기면 이번 답장만 그대로 보내고, 다음 초안부터는 다시 장부와 맞춰 봐요.")
                }
            case .unchecked:
                Label("숫자 확인을 하지 못했어요. 직접 읽고 보내 주세요.", systemImage: "exclamationmark.circle")
                    .font(.subheadline.weight(.semibold))
                    .accessibilityIdentifier("bk25.unchecked")
            case .clear:
                Label(grounding.checkedKinds.isEmpty ? "맞춰 볼 숫자를 찾지 못했어요" : "장부와 다른 숫자를 찾지 못했어요",
                      systemImage: "doc.text.magnifyingglass")
                    .font(.subheadline.weight(.semibold))
                    .accessibilityIdentifier("bk25.clear")
            }
        }
    }

    /// The text is checked shortly after typing stops; a later change cancels the wait.
    private func verifyAfterTyping() async {
        guard grounding.needsVerification(draft) else { return }
        do {
            try await Task.sleep(for: .milliseconds(700))
        } catch {
            return
        }
        await grounding.verify(inquiryID, text: draft)
    }
}

/// Under 답변 완료: why the button waits.
struct BK25LockLine: View {
    let grounding: BK25Grounding

    var body: some View {
        if grounding.isGrounded && grounding.lock == .locked && !grounding.isVerifying {
            Label("숫자 \(grounding.mismatchCount)개가 장부와 달라요", systemImage: "exclamationmark.triangle.fill")
                .font(.subheadline.weight(.semibold))
                .accessibilityIdentifier("bk25.lockLine")
        }
    }
}

private struct ClaimRow: View {
    let claim: BK25Claim
    let index: Int
    let fix: () -> Void

    private var isMismatch: Bool { claim.status == .mismatched }

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            ViewThatFits(in: .horizontal) {
                HStack(spacing: 8) {
                    quote
                    Spacer(minLength: 8)
                    SourceChip(claim: claim)
                }
                VStack(alignment: .leading, spacing: 6) {
                    quote
                    SourceChip(claim: claim)
                }
            }
            if isMismatch {
                mismatch
            } else if claim.status == .unsupported {
                Text("장부에서 근거를 찾지 못했어요")
                    .font(.subheadline)
                    .foregroundStyle(Color.secondaryText)
            }
        }
        .padding(.vertical, 2)
    }

    private var quote: some View {
        Text("‘\(claim.text)’")
            .font(.body)
            .fontWeight(isMismatch ? .semibold : .regular)
            .accessibilityIdentifier("bk25.claim.\(index)")
    }

    @ViewBuilder
    private var mismatch: some View {
        Label("장부와 다름", systemImage: "exclamationmark.triangle.fill")
            .font(.subheadline.weight(.semibold))
        if let note = claim.note {
            Text(verbatim: note)
                .font(.subheadline)
                .foregroundStyle(Color.secondaryText)
        }
        if let ledgerValue = claim.ledgerValue {
            Text(verbatim: "장부에는 \(ledgerValue)")
                .font(.subheadline)
        }
        if claim.replacement != nil {
            Button("장부 값으로 바꾸기", action: fix)
                .font(.subheadline.weight(.semibold))
                .buttonStyle(.bordered)
                .accessibilityIdentifier("bk25.fix")
        }
    }
}

private struct SourceChip: View {
    let claim: BK25Claim

    var body: some View {
        HStack(spacing: 4) {
            Image(systemName: claim.source.symbol)
                .imageScale(.small)
                .accessibilityHidden(true)
            Text(verbatim: claim.sourceLabel)
        }
        .font(.subheadline.weight(.semibold))
        .padding(.horizontal, 8)
        .padding(.vertical, 4)
        .background(.fill.tertiary, in: .capsule)
        .fixedSize()
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("근거 \(claim.sourceLabel)")
    }
}
