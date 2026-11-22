import SwiftUI

/// 채널 연결 in 설정: every service worth linking, what is stored, and what is really being collected.
struct ConnectionsView: View {
    var body: some View {
        ConnectionsList(order: ConnectionCatalog.all)
            .navigationTitle("채널 연결")
            .navigationBarTitleDisplayMode(.inline)
    }
}

/// The rows, shared by 설정 and the onboarding step. Loading, a failed load, and a lost connection are drawn by
/// `LoadableContent`; this view adds the rows, the edit sheet, and delete with undo.
struct ConnectionsList: View {
    /// Services in the order to show; each group keeps this order.
    let order: [ConnectionService]
    @State private var loader = Loader<ConnectionsData>()
    @State private var editing: ConnectionService?
    @State private var failure: String?
    @Environment(AppModel.self) private var app

    var body: some View {
        LoadableContent(loader: loader, retry: load) { data in
            list(data)
        }
        .task(id: app.dataVersion) { await load() }
        .sheet(item: $editing) { service in
            if let item = loader.value?.item(for: service) {
                ConnectionEditSheet(service: service, current: item, saved: { await load() },
                                    remove: { delete(item, service) })
            }
        }
        .alert("못 지웠어요", isPresented: Binding(get: { failure != nil }, set: { if !$0 { failure = nil } })) {
            Button("확인", role: .cancel) {}
        } message: {
            Text(verbatim: failure ?? "")
        }
    }

    private func load() async {
        await loader.load { try await RoundupAPI.connectionsScreen() }
    }

    private func list(_ data: ConnectionsData) -> some View {
        let savable = order.filter { data.item(for: $0) != nil }
        let planned = order.filter { data.item(for: $0) == nil }
        let hasNothingSaved = !data.items.contains { $0.isSaved }
        return List {
            if data.statusFailed {
                CardSection {
                    notice("가져오기가 잘 되는지 살피지 못했어요. 입력해 둔 값은 지워지지 않았어요.", symbol: "exclamationmark.circle.fill")
                        .accessibilityIdentifier("connections.statusFailed")
                }
            } else if hasNothingSaved, !savable.isEmpty {
                CardSection {
                    Text("아직 넣어 둔 채널이 하나도 없네요. 평소 많이 쓰는 채널부터 골라서 링크나 아이디만 넣어 보세요. 비밀번호 같은 건 안 물어봐요.")
                        .font(.subheadline)
                        .foregroundStyle(Color.secondaryText)
                        .accessibilityIdentifier("connections.empty")
                }
            }
            CardSection("지금 저장할 수 있는 곳") {
                if savable.isEmpty {
                    Text("지금 저장할 수 있는 채널이 없네요. 화면을 아래로 끌어내리면 목록을 새로 받아 와요.")
                        .font(.subheadline)
                        .foregroundStyle(Color.secondaryText)
                }
                ForEach(savable) { service in
                    savableRow(service, data)
                }
            }
            CardSection("준비 중이에요") {
                ForEach(planned) { service in
                    ConnectionRow(service: service, state: .planned)
                }
            }
        }
        .cardList()
        .refreshable { await load() }
    }

    @ViewBuilder
    private func savableRow(_ service: ConnectionService, _ data: ConnectionsData) -> some View {
        let item = data.item(for: service)
        let state = ConnectionRowState.resolve(service: service, item: item, source: data.source(for: service))
        Button {
            editing = service
        } label: {
            ConnectionRow(service: service, state: state, value: item?.value, note: data.note(for: service))
        }
        .buttonStyle(.plain)
        .accessibilityHint(item?.isSaved == true ? "넣은 값 고치기" : "값을 입력해요")
        .swipeActions(edge: .trailing, allowsFullSwipe: false) {
            // No destructive role: the row stays in place, and the toast can undo the delete.
            if let item, item.isSaved {
                Button {
                    delete(item, service)
                } label: {
                    Label("지우기", systemImage: "trash")
                }
            }
        }
    }

    /// Label-colored words beside an orange symbol, as every error line in the app.
    private func notice(_ text: String, symbol: String) -> some View {
        Label {
            Text(verbatim: text)
                .font(.subheadline)
        } icon: {
            Image(systemName: symbol)
                .foregroundStyle(Color.pendingOrange)
        }
    }

    private func delete(_ item: ServiceConnection, _ service: ConnectionService) {
        guard let value = item.value else { return }
        Task {
            do {
                let removed = try await RoundupAPI.deleteConnection(service: service.id, revision: item.revision)
                await load()
                app.showToast("‘\(service.name)’ 값 삭제 완료", undo: {
                    await restore(value, service: service, revision: removed.revision)
                })
            } catch is CancellationError {
                // The screen went away; nothing to report.
            } catch {
                failure = RoundupAPI.connectionFailureText(error)
                await load()
            }
        }
    }

    /// Puts a deleted value back with the revision the delete returned.
    private func restore(_ value: String, service: ConnectionService, revision: Int) async {
        do {
            _ = try await RoundupAPI.saveConnection(service: service.id, value: value, revision: revision)
        } catch {
            app.showToast("되돌리기가 안 됐어요. 값을 한 번 더 넣어 보세요.")
        }
        await load()
    }
}

/// One field for one service: the format it expects, a check on the device before anything is sent, and the
/// server's refusal beside the field when it still says no.
struct ConnectionEditSheet: View {
    let service: ConnectionService
    let current: ServiceConnection
    /// Reloads the list after a save.
    let saved: () async -> Void
    /// Deletes the stored value through the list, which owns the undo toast.
    let remove: () -> Void
    @State private var text: String
    @State private var problem: String?
    @State private var isSaving = false
    @FocusState private var isFocused: Bool
    @Environment(\.dismiss) private var dismiss

    init(service: ConnectionService, current: ServiceConnection, saved: @escaping () async -> Void,
         remove: @escaping () -> Void) {
        self.service = service
        self.current = current
        self.saved = saved
        self.remove = remove
        _text = State(initialValue: current.value ?? "")
    }

    private var cleaned: String { text.trimmingCharacters(in: .whitespacesAndNewlines) }
    private var canSave: Bool { !isSaving && !cleaned.isEmpty && cleaned != (current.value ?? "") }

    var body: some View {
        NavigationStack {
            List {
                CardSection(content: {
                    TextField(service.format?.placeholder ?? "", text: $text)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                        .keyboardType(service.format?.id == nil ? .URL : .default)
                        .submitLabel(.done)
                        .focused($isFocused)
                        .onSubmit(save)
                        .frame(minHeight: 44)
                        .accessibilityLabel("\(service.name) \(service.needs)")
                        .accessibilityIdentifier("connections.edit.field")
                    if let problem {
                        Label {
                            Text(verbatim: problem)
                                .font(.subheadline)
                        } icon: {
                            Image(systemName: "exclamationmark.circle.fill")
                                .foregroundStyle(Color.pendingOrange)
                        }
                        .accessibilityIdentifier("connections.edit.problem")
                    }
                }, header: {
                    Text(verbatim: service.needs)
                }, footer: {
                    EmptyView()
                })
                CardSection("이렇게 입력해요") {
                    ForEach(service.format?.examples ?? [], id: \.self) { example in
                        Text(verbatim: example)
                            .font(.subheadline)
                            .textSelection(.enabled)
                    }
                    Text("공도리는 비밀번호와 인증번호를 묻는 일이 없어요. 여기에 절대 적지 마세요.")
                        .font(.subheadline)
                        .foregroundStyle(Color.secondaryText)
                    Text(verbatim: service.today)
                        .font(.subheadline)
                        .foregroundStyle(Color.secondaryText)
                }
                if current.isSaved {
                    CardSection {
                        Button("저장한 값 지우기") {
                            dismiss()
                            remove()
                        }
                        .frame(minHeight: 44)
                        .disabled(isSaving)
                        .accessibilityIdentifier("connections.edit.remove")
                    }
                }
            }
            .cardList()
            .navigationTitle(service.name)
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("취소") { dismiss() }
                        .disabled(isSaving)
                }
                ToolbarItem(placement: .confirmationAction) {
                    // One button whose title is replaced by the spinner, so the toolbar item keeps its shape.
                    Button(action: save) {
                        BusyLabel(title: "저장", isBusy: isSaving)
                    }
                    .disabled(!canSave)
                    .accessibilityIdentifier("connections.edit.save")
                }
            }
            .onChange(of: text) { problem = nil }
            .task { isFocused = true }
        }
        .presentationDetents([.medium, .large])
        .interactiveDismissDisabled(isSaving)
    }

    private func save() {
        guard canSave else { return }
        let value = cleaned
        if let found = service.problem(in: value) {
            problem = found
            return
        }
        problem = nil
        isSaving = true
        Task {
            defer { isSaving = false }
            do {
                _ = try await RoundupAPI.saveConnection(service: service.id, value: value, revision: current.revision)
                await saved()
                dismiss()
            } catch is CancellationError {
                // The sheet went away; nothing to report.
            } catch {
                problem = RoundupAPI.connectionFailureText(error)
                // A conflict means the list is out of date; the transport's words already say it was reloaded.
                if (error as? RoundupAPIError)?.isConflict == true {
                    await saved()
                }
            }
        }
    }
}
