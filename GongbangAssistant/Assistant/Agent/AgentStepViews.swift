import SwiftUI

extension AgentStep {
    /// Where a step stands for the owner; a proposed step follows what became of its proposal.
    enum Standing: Equatable {
        case done
        case undone
        case waiting
        case approved
        case dismissed
        case expired
        case closed
        case refused
        case clarify

        var word: String {
            switch self {
            case .done: "완료"
            case .undone: "되돌림"
            case .waiting: "승인 대기"
            case .approved: "승인함"
            case .dismissed: "하지 않기로 함"
            case .expired: "만료"
            case .closed: "끝난 제안"
            case .refused: "하지 않음"
            case .clarify: "확인 필요"
            }
        }

        var symbol: String {
            switch self {
            case .done, .approved: "checkmark"
            case .undone: "arrow.uturn.backward"
            case .dismissed, .refused, .closed: "minus"
            case .expired: "clock"
            case .waiting, .clarify: "circle.fill"
            }
        }

        var needsOwner: Bool { self == .waiting || self == .clarify }
    }

    func standing(proposal: AgentCenter.ProposalStanding?) -> Standing {
        if undone { return .undone }
        switch decision {
        case .auto: return .done
        case .refused: return .refused
        case .clarify: return .clarify
        case .proposed:
            // An approved step keeps its decision; that it can be undone tells that it ran.
            if undoable { return .approved }
            switch proposal {
            case .approved: return .approved
            case .dismissed: return .dismissed
            case .expired: return .expired
            case .closed: return .closed
            case .open, nil: return .waiting
            }
        }
    }

    /// The owner's own words a finished step rested on; for any other step, why it stopped.
    var note: String? {
        let quoted = evidence.map { "\($0.kind == "adapter" ? "택배사 확인" : "사장님 말씀") ‘\($0.excerpt)’" }
        if decision == .auto, !quoted.isEmpty { return quoted.joined(separator: " · ") }
        return reason.isEmpty ? nil : reason
    }
}

/// One step of a run on a few lines: what it was, where it stands and on which order or person, then the words
/// it rested on or the reason it stopped. A step the server can still take back carries 되돌리기.
struct AgentStepRow: View {
    let step: AgentStep
    /// The proposal a proposed step raised, when the run that shows the step knows it.
    var proposal: AgentProposal?
    @State private var center = AgentCenter.shared
    @Environment(\.dynamicTypeSize) private var dynamicTypeSize

    var body: some View {
        let step = center.current(step)
        let standing = step.standing(proposal: proposal.map { center.standing(of: $0, at: .now) })
        let layout = dynamicTypeSize.isAccessibilitySize
            ? AnyLayout(VStackLayout(alignment: .leading, spacing: 8))
            : AnyLayout(HStackLayout(alignment: .center, spacing: 8))
        layout {
            HStack(alignment: .top, spacing: 10) {
                StandingMark(standing: standing)
                VStack(alignment: .leading, spacing: 2) {
                    Text(verbatim: step.title)
                        .font(.body.weight(.medium))
                        .foregroundStyle(standing == .undone ? Color.secondaryText : Color.primary)
                    PhraseText(text: ([standing.word] + [step.target?.label].compactMap { $0 }).joined(separator: " · "))
                    if let note = step.note {
                        Text(verbatim: note)
                    }
                }
                .font(.subheadline)
                .foregroundStyle(Color.secondaryText)
                .frame(maxWidth: .infinity, alignment: .leading)
            }
            .accessibilityElement(children: .ignore)
            .accessibilityLabel([step.title, standing.word, step.target?.label, step.note].compactMap { $0 }
                .joined(separator: ", "))
            .accessibilityIdentifier("agent.step.\(step.id)")
            if step.undoable && !step.undone {
                AgentUndoButton(step: step, showsTitle: dynamicTypeSize.isAccessibilitySize)
            }
        }
    }
}

private struct StandingMark: View {
    let standing: AgentStep.Standing

    var body: some View {
        Group {
            if standing.needsOwner {
                Circle()
                    .fill(Color.pendingOrange)
                    .frame(width: 8, height: 8)
            } else if standing.symbol == "checkmark" {
                DoneMark(isDone: true)
            } else {
                Image(systemName: standing.symbol)
                    .font(.footnote.weight(.bold))
                    .foregroundStyle(CalendarTokens.secondary)
                    .frame(width: 24, height: 24)
                    .background(CalendarTokens.separator, in: .circle)
            }
        }
        .frame(width: 24, height: 24)
        .accessibilityHidden(true)
    }
}

/// Takes one step of the assistant back: the circle beside the row, or a full-width button that names itself.
struct AgentUndoButton: View {
    let step: AgentStep
    var showsTitle = false
    @State private var isConfirming = false
    @Environment(AppModel.self) private var app

    private var isBusy: Bool { app.isRunning(AgentCenter.runID(step)) }

    var body: some View {
        Button {
            // Going back clears the carrier and tracking number, which only typing them again restores.
            if step.tool == "register_invoice" {
                isConfirming = true
            } else {
                undo()
            }
        } label: {
            if showsTitle {
                BusyLabel(title: "되돌리기", isBusy: isBusy)
                    .font(.subheadline.weight(.semibold))
                    .frame(maxWidth: .infinity, minHeight: 30)
            } else {
                ZStack {
                    Image(systemName: "arrow.uturn.backward")
                        .opacity(isBusy ? 0 : 1)
                    if isBusy {
                        ProgressView()
                            .controlSize(.regular)
                    }
                }
                .font(.body.weight(.semibold))
                .frame(minWidth: 30, minHeight: 30)
            }
        }
        .buttonStyle(.bordered)
        .buttonBorderShape(showsTitle ? .automatic : .circle)
        .controlSize(.large)
        .disabled(isBusy)
        .accessibilityLabel("\(step.title) 되돌리기")
        .accessibilityValue(isBusy ? "처리 중" : "")
        .accessibilityHint("\(AssistantIdentity.name)가 한 이 일을 되돌려요.")
        .accessibilityIdentifier("agent.step.undo.\(step.id)")
        .confirmationDialog("송장을 지우고 되돌릴까요?", isPresented: $isConfirming, titleVisibility: .visible) {
            Button("송장 지우고 되돌리기", role: .destructive, action: undo)
            Button("그대로 두기", role: .cancel) {}
        } message: {
            Text("등록한 택배사와 송장번호가 지워져요.")
        }
    }

    private func undo() {
        Task { await AgentCenter.shared.undo(step, app: app) }
    }
}

/// The steps of one run: every change, refusal, and question as a row, and the lookups together on one line.
struct AgentStepList: View {
    let steps: [AgentStep]
    var proposals: [AgentProposal] = []

    private var lookupTitles: [String] {
        var seen = Set<String>()
        return steps.filter(\.isRead).map(\.title).filter { seen.insert($0).inserted }
    }

    var body: some View {
        let rows = steps.filter { !$0.isRead }
        VStack(alignment: .leading, spacing: 12) {
            ForEach(Array(rows.enumerated()), id: \.element.id) { index, step in
                if index > 0 {
                    Divider()
                }
                AgentStepRow(step: step, proposal: proposals.first { $0.wasRaised(by: step) })
            }
            if !lookupTitles.isEmpty {
                if !rows.isEmpty {
                    Divider()
                }
                PhraseText(text: (["확인한 것"] + lookupTitles).joined(separator: " · "))
                    .font(.subheadline)
                    .foregroundStyle(Color.secondaryText)
            }
        }
    }
}
