import SwiftUI

/// "비서가 기억하는 것": each thing the assistant keeps in mind, the owner's own sentence it came from, and a
/// way to make the assistant forget it.
struct AgentMemoryListView: View {
    @State private var loader = Loader<[AgentMemory]>()
    @State private var forgetting: AgentMemory?
    @Environment(AppModel.self) private var app

    var body: some View {
        LoadableContent(loader: loader, retry: load) { memories in
            if memories.isEmpty {
                ContentUnavailableView {
                    Label("\(AssistantIdentity.name)가 기억하는 것이 없어요", systemImage: "bookmark")
                } description: {
                    Text(verbatim: "기억해 달라고 말씀하신 내용이 여기에 모여요.")
                        .foregroundStyle(Color.secondaryText)
                }
                .accessibilityIdentifier("agent.memories.empty")
            } else {
                List {
                    CardSection {
                        ForEach(memories) { row($0) }
                    } footer: {
                        Text("\(AssistantIdentity.name)는 이 내용을 참고만 해요. 일을 처리하는 근거로 쓰지는 않아요.")
                    }
                }
                .cardList()
                .refreshable { await load() }
            }
        }
        .navigationTitle("\(AssistantIdentity.name)가 기억하는 것")
        .navigationBarTitleDisplayMode(.inline)
        .task(id: app.dataVersion) { await load() }
        .confirmationDialog("이 기억을 지울까요?", isPresented: Binding(
            get: { forgetting != nil }, set: { if !$0 { forgetting = nil } }
        ), titleVisibility: .visible, presenting: forgetting) { memory in
            Button("지우기", role: .destructive) { forget(memory) }
            Button("그대로 두기", role: .cancel) {}
        } message: { memory in
            Text("이 기억을 지우면 \(AssistantIdentity.name)가 더는 참고하지 않아요: ‘\(memory.text)’")
        }
    }

    private func load() async {
        await loader.load { try await RoundupAPI.agentMemories() }
    }

    private func runID(_ memory: AgentMemory) -> String { "agent.memory.\(memory.id)" }

    private func row(_ memory: AgentMemory) -> some View {
        let source = (["사장님 말씀 ‘\(memory.sourceQuote)’"]
            + [memory.date.map { RelativeDayFormatter.day($0, now: .now) }].compactMap { $0 }).joined(separator: " · ")
        return HStack(spacing: 8) {
            VStack(alignment: .leading, spacing: 2) {
                Text(verbatim: memory.text)
                Text(verbatim: source)
                    .font(.subheadline)
                    .foregroundStyle(Color.secondaryText)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .accessibilityElement(children: .combine)
            .accessibilityIdentifier("agent.memory.\(memory.id)")
            Button {
                forgetting = memory
            } label: {
                Image(systemName: "trash")
                    .frame(minWidth: 44, minHeight: 44)
                    .contentShape(.rect)
            }
            .buttonStyle(.borderless)
            .foregroundStyle(.primary)
            .disabled(app.isRunning(runID(memory)))
            .accessibilityLabel("‘\(memory.text)’ 기억 지우기")
            .accessibilityIdentifier("agent.memory.forget.\(memory.id)")
        }
        .swipeActions(edge: .trailing, allowsFullSwipe: false) {
            Button("지우기", systemImage: "trash", role: .destructive) { forgetting = memory }
        }
    }

    private func forget(_ memory: AgentMemory) {
        Task {
            if await app.run(id: runID(memory), { try await RoundupAPI.forget(memory) }) {
                app.showToast("기억을 지웠어요")
            }
        }
    }
}
