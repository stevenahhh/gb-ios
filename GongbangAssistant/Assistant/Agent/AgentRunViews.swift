import SwiftUI

/// How a run that is still going, or one that was cut short, stands. A finished run shows nothing here.
struct AgentRunStatusLine: View {
    let record: AgentRecord

    private var progress: String {
        let finished = record.steps.filter { $0.decision == .auto && !$0.isRead }.count
        return finished == 0 ? "처리 중이에요" : "처리 중 · \(finished)건 끝냈어요"
    }

    var body: some View {
        switch record.status {
        case .queued, .running:
            VStack(alignment: .leading, spacing: 4) {
                GeneratingIndicator(label: progress)
                Text("화면을 닫아도 계속 처리해요.")
                    .font(.subheadline)
                    .foregroundStyle(Color.secondaryText)
            }
        case .stopped:
            notice("\(AssistantIdentity.name)를 멈춰서 남은 일은 하지 않았어요.", symbol: "pause.circle")
        case .failed:
            notice(record.changedData ? "끝까지 처리하지 못했어요. 아래 일까지만 했어요." : "처리하지 못했어요. 바뀐 것은 없어요.",
                   symbol: "exclamationmark.circle")
        case .done, .fallback:
            EmptyView()
        }
    }

    private func notice(_ text: String, symbol: String) -> some View {
        Label {
            Text(verbatim: text)
        } icon: {
            Image(systemName: symbol)
                .foregroundStyle(Color.secondaryText)
        }
        .accessibilityIdentifier("agent.run.notice")
    }
}

extension AgentRecord {
    /// A run that is still going or was cut short says so even before it has done anything.
    var hasStatusLine: Bool { status != .done && status != .fallback }

    func hasDetail(showingStatus: Bool) -> Bool {
        (showingStatus && hasStatusLine) || !steps.isEmpty || !proposals.isEmpty
    }
}

/// Under an answer: how its run stands, what the run did, and what it asks the owner to approve.
struct AgentRunDetail: View {
    let record: AgentRecord
    /// False when the status line already stands in for an answer that has no words yet.
    var showsStatus = true
    /// The live voice screen draws its cards on its own backdrop.
    var isLive = false
    /// The one card on the screen that takes the prominent button, when it is among this answer's.
    var primaryID: AgentProposal.ID?

    var body: some View {
        // A proposed step whose proposal has its card below is that card, so a row would say it twice.
        let steps = record.steps.filter { step in !record.proposals.contains { $0.wasRaised(by: step) } }
        VStack(alignment: .leading, spacing: 10) {
            if showsStatus && record.hasStatusLine {
                AgentRunStatusLine(record: record)
            }
            if !steps.isEmpty {
                box(AgentStepList(steps: steps))
            }
            ForEach(record.proposals) { proposal in
                box(AgentProposalCard(proposal: proposal, isPrimary: proposal.id == primaryID))
            }
        }
    }

    @ViewBuilder
    private func box(_ content: some View) -> some View {
        if isLive {
            content
                .padding(12)
                .background(AppPalette.card, in: .inner)
        } else {
            content
                .padding(16)
                .background(AppPalette.card, in: .card)
        }
    }
}
