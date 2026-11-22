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

    private static let overrideReasons = ["장부 숫자와 차이가 있어요", "손님이랑 따로 얘기 끝났어요", "이유가 따로 있어요"]

    var body: some View {
        if grounding.loadFailed && grounding.arm == nil {
            CardSection {
                LabeledContent {
                    Button("다시 시도") {
                        Task { await grounding.load(inquiryID, draft: draft) }
                    }
                } label: {
                    Text("살펴본 내용을 받아 오지 못했어요")
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
                        Text(verbatim: "비교한 항목: \(grounding.checkedKinds.joined(separator: ", "))")
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
                Text("숫자 확인")
            } footer: {
                Text("숫자만 장부와 대조해 드려요. 금액, 예약금, 할인, 빈자리, 요일과 시간, 수업 길이, 인원, 주차와 환불, 재료에 나온 숫자가 여기에 들어가요. 글의 뜻까지는 못 보니 손님께 가기 전에 사장님이 꼭 읽어 보세요.")
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
                Text(verbatim: "장부나 수업 정보로는 답이 안 나오는 질문이에요. 짧게 알려 주시면 그 말씀으로 답장을 쓸게요.")
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
            Text("사장님 답 필요")
        }
    }

    @ViewBuilder
    private var summary: some View {
        if grounding.isVerifying {
            HStack(spacing: 10) {
                ProgressView()
                Text("장부 숫자랑 하나씩 비교하고 있어요")
            }
            .font(.subheadline)
            .foregroundStyle(Color.secondaryText)
        } else {
            switch grounding.lock {
            case .locked:
                HStack(alignment: .firstTextBaseline, spacing: 8) {
                    // An identifier on the row would replace the menu's own.
                    Label("장부와 다른 숫자 \(grounding.mismatchCount)개", systemImage: "exclamationmark.triangle.fill")
                        .font(.headline)
                        .accessibilityIdentifier("bk25.locked")
                    Spacer(minLength: 8)
                    // Kept behind a menu, so a reply is never sent past the check by one mistaken tap.
                    Menu {
                        Button("이번 한 번만 그냥 보내기") { isAskingReason = true }
                    } label: {
                        Image(systemName: "ellipsis.circle")
                            .accessibilityLabel("펼쳐 보기")
                    }
                    .accessibilityIdentifier("bk25.more")
                }
                .confirmationDialog("숫자가 장부랑 안 맞는데 이대로 보낼까요?", isPresented: $isAskingReason, titleVisibility: .visible) {
                    ForEach(Self.overrideReasons, id: \.self) { reason in
                        Button(reason) {
                            grounding.overrideReason = reason
                            approve()
                        }
                    }
                    Button("취소", role: .cancel) {}
                } message: {
                    Text("왜 그런지 적어 주시면 이 답장 하나만 손대지 않고 내보내요. 다음 초안이 오면 장부 숫자와 또 대조할게요.")
                }
            case .unchecked:
                // Rows below may still show numbers found in the ledger; this says the whole reply was not confirmed.
                Label(grounding.claims.isEmpty ? "숫자 대조가 중간에 멈췄어요. 손님께 가기 전에 사장님이 꼼꼼히 훑어보세요."
                                               : "숫자 몇 개만 찾아냈어요. 글 전체를 본 게 아니니 손님께 가기 전에 꼼꼼히 훑어보세요.",
                      systemImage: "exclamationmark.circle")
                    .font(.subheadline.weight(.semibold))
                    .accessibilityIdentifier("bk25.unchecked")
            case .clear:
                Label(grounding.checkedKinds.isEmpty ? "비교할 만한 숫자가 안 보여요" : "장부와 어긋난 숫자는 없어요",
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
            Label("장부와 다른 숫자 \(grounding.mismatchCount)개", systemImage: "exclamationmark.triangle.fill")
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
                Text("장부엔 맞는 기록이 없어요")
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
        Label("장부랑 달라요", systemImage: "exclamationmark.triangle.fill")
            .font(.subheadline.weight(.semibold))
        if let note = claim.note {
            Text(verbatim: note)
                .font(.subheadline)
                .foregroundStyle(Color.secondaryText)
        }
        if let ledgerValue = claim.ledgerValue {
            Text(verbatim: "장부 값 \(ledgerValue)")
                .font(.subheadline)
        }
        if claim.replacement != nil {
            Button("장부에 적힌 걸로 고치기", action: fix)
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
        .accessibilityLabel("출처 \(claim.sourceLabel)")
    }
}
