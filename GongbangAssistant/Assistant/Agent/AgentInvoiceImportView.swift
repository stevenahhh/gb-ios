import SwiftUI
import UniformTypeIdentifiers

/// A carrier export the owner picked, read into memory. It is never written to disk: the review screen holds
/// it until the owner approves or leaves, because approving sends the same bytes again.
struct InvoiceFile: Identifiable, Hashable {
    let id = UUID()
    let name: String
    let data: Data

    static let contentTypes: [UTType] = [.commaSeparatedText] + [UTType(filenameExtension: "xlsx")].compactMap { $0 }
    private static let maxBytes = 2 * 1024 * 1024

    init(contentsOf url: URL) throws {
        guard ["csv", "xlsx"].contains(url.pathExtension.lowercased()) else {
            throw RoundupAPIError(message: "엑셀 파일, 그러니까 CSV나 XLSX만 열어 볼 수 있어요.")
        }
        let isScoped = url.startAccessingSecurityScopedResource()
        defer { if isScoped { url.stopAccessingSecurityScopedResource() } }
        guard let data = try? Data(contentsOf: url) else {
            throw RoundupAPIError(message: "이 파일은 안 열려요. 다른 파일로 다시 골라 주세요.")
        }
        guard data.count <= Self.maxBytes else {
            throw RoundupAPIError(message: "한 번에 2MB까지 불러와요. 파일을 쪼개서 다시 올려 주세요.")
        }
        name = url.lastPathComponent
        self.data = data
    }
}

extension EnvironmentValues {
    /// Opens the file picker for a carrier export on the screen that can review one. The id names the file
    /// proposal the pick replaces, if a card asked for it. Nil where no screen can review a file.
    @Entry var pickInvoiceFile: (@MainActor (AgentProposal.ID?) -> Void)?
}

/// Picks a carrier export and pushes its review. A screen with this modifier offers the pick to the cards
/// inside it through the environment.
private struct InvoiceFilePicking: ViewModifier {
    let onPage: Bool
    @State private var isChoosing = false
    @State private var picked: InvoiceFile?
    @State private var replaced: AgentProposal.ID?
    @State private var failure: String?

    func body(content: Content) -> some View {
        // Read here: the destination is built outside this body, where a change to `replaced` would go unseen.
        let replaced = replaced
        content
            .environment(\.pickInvoiceFile) { proposal in
                self.replaced = proposal
                choose()
            }
            .navigationDestination(item: $picked) { file in
                AgentInvoiceImportView(file: file, replaced: replaced, onPage: onPage)
            }
            .fileImporter(isPresented: $isChoosing, allowedContentTypes: InvoiceFile.contentTypes) { result in
                switch result {
                case .success(let url): open(url)
                case .failure(let error): failure = error.localizedDescription
                }
            }
            .alert("파일을 열어 보지 못했어요", isPresented: Binding(get: { failure != nil }, set: { if !$0 { failure = nil } })) {
                Button("확인", role: .cancel) {}
            } message: {
                Text(failure ?? "")
            }
    }

    private func choose() {
        #if DEBUG
        // UI tests cannot drive the system's file picker, so they name the file a pick would have returned.
        if let path = ProcessInfo.processInfo.environment["ROUNDUP_UITEST_INVOICE_FILE"] {
            return open(URL(fileURLWithPath: path))
        }
        #endif
        isChoosing = true
    }

    private func open(_ url: URL) {
        do {
            picked = try InvoiceFile(contentsOf: url)
        } catch {
            failure = error.localizedDescription
        }
    }
}

extension View {
    func invoiceFilePicking(onPage: Bool) -> some View {
        modifier(InvoiceFilePicking(onPage: onPage))
    }
}

extension AgentInvoiceImport.Row {
    enum Standing {
        /// No problem, one parcel, a certain carrier: the approval registers it.
        case ready
        /// Only the number's format is in doubt: the approval registers it when the owner switches it on.
        case formatWarned
        /// The approval leaves it out, whatever the owner chooses.
        case leftOut
    }

    var standing: Standing {
        if !needsOwner { return .ready }
        let isOnlyFormat = problems.map(\.code) == ["wrong_format"] && target != nil && carrier != nil
        return isOnlyFormat ? .formatWarned : .leftOut
    }

    /// Why the row needs the owner, in the server's words where it sent any.
    var reasons: [String] {
        if !problems.isEmpty { return problems.map(\.text) }
        if target == nil { return ["이 줄이 어느 주문 건인지 딱 하나로 못 골랐어요."] }
        if carrier == nil { return ["어느 택배사 번호인지 모르겠어요."] }
        return ["번호 자릿수를 보고 택배사를 추측했어요. 한 번 봐 주세요."]
    }

    var title: String { target?.label ?? "파일 \(line)번째 줄" }
}

/// What the server read from a picked carrier export. One approval registers the clean rows together with the
/// format-warned rows the owner switched on; every other row says why it is left out. Nothing is registered
/// before that yes, and the file goes along with it again.
struct AgentInvoiceImportView: View {
    let file: InvoiceFile
    /// The file proposal whose card asked for this pick. The new read replaces it.
    var replaced: AgentProposal.ID?
    var onPage = false
    @State private var loader = Loader<AgentInvoiceImport>()
    /// Lines whose format warning the owner accepted.
    @State private var accepted: Set<Int> = []
    @State private var registered: Int?
    @Environment(AppModel.self) private var app

    private static let runID = "agent.invoices.approve"
    private typealias IndexedRow = (offset: Int, element: AgentInvoiceImport.Row)

    var body: some View {
        LoadableContent(loader: loader, retry: load) { read in
            content(read)
        }
        .navigationTitle("송장 파일 훑어보기")
        .navigationBarTitleDisplayMode(.inline)
        // Reading raises a proposal, so coming back to this screen must not read again.
        .task { if loader.value == nil { await load() } }
    }

    private func load() async {
        let file = file
        await loader.load { try await RoundupAPI.importInvoices(file: file.data, named: file.name) }
        // Reading the file again raised a new proposal for it, so the one that asked for the pick is done with.
        if let replaced, let read = loader.value, let fresh = read.proposalId, fresh != replaced,
           let stale = AgentCenter.shared.proposals.first(where: { $0.id == replaced }) {
            _ = try? await RoundupAPI.dismiss(stale)
            await AgentCenter.shared.loadProposals()
        }
    }

    private func content(_ read: AgentInvoiceImport) -> some View {
        let rows = Array(read.rows.enumerated())
        let ready = rows.filter { $0.element.standing == .ready }
        let warned = rows.filter { $0.element.standing == .formatWarned }
        let leftOut = rows.filter { $0.element.standing == .leftOut }
        let chosen = ready.count + warned.filter { accepted.contains($0.element.line) }.count
        return List {
            CardSection {
                VStack(alignment: .leading, spacing: 4) {
                    Text(verbatim: file.name)
                        .font(.headline)
                    Group {
                        Text("파일에서 찾은 송장번호 \(rows.count)개")
                        Text("사장님이 수락하시기 전엔 한 건도 넣지 않아요.")
                    }
                    .font(.subheadline)
                    .foregroundStyle(Color.secondaryText)
                }
                .accessibilityElement(children: .combine)
                .accessibilityIdentifier("invoice.import.summary")
                approval(read, chosen: chosen, remaining: rows.count - (registered ?? 0))
            } footer: {
                Text("이 화면을 벗어나면 파일은 바로 사라져요. 휴대폰에 따로 남기지 않아요.\n쓰여 있는 송장번호를 숫자 하나 안 바꾸고 그대로 넣어요.\n택배사에 그 번호가 맞는지 물어보지는 않아요.")
            }

            if !ready.isEmpty {
                CardSection("문제없이 들어갈 송장 \(ready.count)건") {
                    ForEach(ready, id: \.offset) { InvoiceRowLine(row: $0.element) }
                }
            }
            if !warned.isEmpty {
                CardSection("번호를 다시 봐 주실 송장 \(warned.count)건") {
                    ForEach(warned, id: \.offset) { warnedRow($0.element) }
                }
            }
            if !leftOut.isEmpty {
                CardSection {
                    ForEach(leftOut, id: \.offset) { row in
                        VStack(alignment: .leading, spacing: 6) {
                            InvoiceRowLine(row: row.element)
                            InvoiceReasons(reasons: row.element.reasons)
                        }
                        .accessibilityElement(children: .combine)
                        .accessibilityIdentifier("invoice.import.leftOut.\(row.element.line)")
                    }
                } header: {
                    Text("이번엔 넣지 않고 빼 둔 송장 \(leftOut.count)건")
                } footer: {
                    Text("엑셀 파일을 고쳐서 다시 올리시거나 배송 관리에서 하나씩 넣어 주세요.")
                }
            }
        }
        .cardList(onPage: onPage)
    }

    /// The one approval for the whole file, or what stands in for it: the result once approved, and the reason
    /// when the file has no row that can be registered.
    @ViewBuilder
    private func approval(_ read: AgentInvoiceImport, chosen: Int, remaining: Int) -> some View {
        if let registered {
            VStack(alignment: .leading, spacing: 4) {
                Label("송장 \(registered)건 등록 끝!", systemImage: "checkmark")
                    .font(.subheadline.weight(.medium))
                if remaining > 0 {
                    Text("나머지 \(remaining)건은 파일을 한 번 더 올리셔야 들어가요.")
                        .font(.subheadline)
                        .foregroundStyle(Color.secondaryText)
                }
            }
            .accessibilityElement(children: .combine)
            .accessibilityIdentifier("invoice.import.registered")
            NavigationLink(value: AreaRoute(area: .deliveries)) {
                Text("혹시 잘못 넣으셨다면 배송 관리에서 되돌리시면 돼요.")
                    .font(.subheadline)
                    .foregroundStyle(Color.secondaryText)
            }
            .accessibilityIdentifier("invoice.import.deliveries")
        } else if let proposal = read.proposalId {
            BK06PrimaryButton(title: "\(chosen)건 수락하고 등록", isBusy: app.isRunning(Self.runID),
                              identifier: "invoice.import.approve") {
                approve(proposal, lines: read.rows.map(\.line).filter(accepted.contains))
            }
            .disabled(chosen == 0)
        } else {
            Text("지금은 수락할 송장이 한 건도 없네요. 아래에서 줄마다 왜 빠졌는지 보여 드릴게요.")
                .font(.subheadline)
                .accessibilityIdentifier("invoice.import.nothing")
        }
    }

    private func warnedRow(_ row: AgentInvoiceImport.Row) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            InvoiceRowLine(row: row)
            InvoiceReasons(reasons: row.reasons)
            Toggle("번호 형식이 달라도 이대로 등록할게요", isOn: Binding(
                get: { accepted.contains(row.line) },
                set: { isOn in
                    if isOn { accepted.insert(row.line) } else { accepted.remove(row.line) }
                }))
                .disabled(registered != nil || app.isRunning(Self.runID))
                .accessibilityLabel("\(row.title) 번호 형식이 달라도 이대로 등록할게요")
                .accessibilityIdentifier("invoice.import.accept.\(row.line)")
        }
        .padding(.vertical, 2)
    }

    private func approve(_ proposalID: String, lines: [Int]) {
        let file = file
        Task {
            var outcome: AgentInvoiceOutcome?
            let wasApproved = await app.run(id: Self.runID) {
                outcome = try await RoundupAPI.approveImportedInvoices(
                    proposalID: proposalID, file: file.data, named: file.name, acceptedLines: lines)
            }
            guard wasApproved, let outcome else { return }
            registered = outcome.registered
            AgentCenter.shared.noteApproved(outcome.proposal)
            ConversationStore.shared.recordExchange(
                "‘\(file.name)’ 파일의 송장 등록 수락",
                answer: AssistantAnswer(text: "송장 \(outcome.registered)건 등록 끝!", items: [], agent: nil))
            await AgentCenter.shared.loadProposals()
        }
    }
}

private struct InvoiceRowLine: View {
    let row: AgentInvoiceImport.Row

    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(verbatim: row.title)
                .font(.body.weight(.medium))
            PhraseText(text: [row.carrier, row.number].compactMap { $0 }.joined(separator: " · "), selectable: true)
                .font(.subheadline.monospacedDigit())
                .foregroundStyle(Color.secondaryText)
        }
    }
}

private struct InvoiceReasons: View {
    let reasons: [String]

    var body: some View {
        ForEach(reasons, id: \.self) { reason in
            HStack(alignment: .firstTextBaseline, spacing: 6) {
                Image(systemName: "exclamationmark.circle.fill")
                    .foregroundStyle(.orange)
                    .accessibilityHidden(true)
                Text(verbatim: reason)
            }
            .font(.subheadline)
            .accessibilityElement(children: .combine)
        }
    }
}
