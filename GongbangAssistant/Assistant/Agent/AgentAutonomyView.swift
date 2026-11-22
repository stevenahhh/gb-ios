import SwiftUI

extension AgentMode {
    var title: String {
        switch self {
        case .off: "끔"
        case .ask: "물어보고"
        case .auto: "알아서"
        }
    }

    var explanation: String {
        switch self {
        case .off: "\(AssistantIdentity.name)가 스스로 하는 일이 없어요. 물어보시면 답만 해요."
        case .ask: "바꾸는 일은 모두 제안으로 올려요. 승인하시면 그때 처리해요."
        case .auto: "근거가 있는 일은 바로 해요. 되돌릴 수 있는 일에는 되돌리기 버튼을 보여 드려요. 근거가 없으면 제안으로 올려요."
        }
    }
}

/// The owner's words for each tool. The server names tools in English and sends no wording for them.
enum AgentToolCatalog {
    struct Entry {
        let title: String
        let note: String
    }

    static let tools: [String: Entry] = [
        "save_reply_draft": Entry(title: "문의 답장 초안 쓰기", note: "초안만 써 둬요. 손님에게 보내는 건 사장님이 해요."),
        "save_content_draft": Entry(title: "홍보 글 초안 쓰기", note: "초안만 써 둬요. 올리는 건 사장님이 해요."),
        "add_event": Entry(title: "일정 넣기", note: "캘린더에 일정을 넣어요."),
        "move_event": Entry(title: "일정 옮기기", note: "일정의 날짜와 시간을 바꿔요."),
        "complete_task": Entry(title: "할 일 완료 표시", note: "끝난 할 일에 완료 표시를 해요."),
        "reopen_task": Entry(title: "할 일 다시 열기", note: "완료한 할 일을 다시 열어요."),
        "remember": Entry(title: "기억해 두기", note: "기억해 달라고 하신 내용을 적어 둬요."),
        "forget": Entry(title: "기억 지우기", note: "지워 달라고 하신 기억을 지워요."),
        "confirm_order": Entry(title: "주문 확인", note: "결제된 주문을 확인 상태로 바꿔요."),
        "mark_packed": Entry(title: "포장 완료 처리", note: "소포를 포장 완료로 바꿔요."),
        "register_invoice": Entry(
            title: "송장 등록", note: "송장번호는 말씀하시거나 붙여 넣으신 그대로 등록해요. 번호가 맞는지 택배사에 확인하지 않아요."),
        "mark_delivered": Entry(title: "배송 완료 처리", note: "소포를 배송 완료로 바꿔요."),
        "confirm_deposit": Entry(title: "예약금 확인", note: "예약금이 들어온 예약을 확인 처리해요."),
        "create_booking": Entry(title: "예약 넣기", note: "말씀하신 손님과 인원으로 예약을 넣어요."),
        "decide_cancellation": Entry(title: "취소 결정 기록", note: "사장님이 정하신 취소 결정을 적어 둬요. 환불을 보내지는 않아요."),
        "record_quote_outcome": Entry(title: "출강 견적 결과 기록", note: "출강 견적이 성사됐는지 적어 둬요."),
    ]

    /// What no setting hands to the assistant; the server offers it no tool for any of these.
    static let neverDelegated = [
        "손님에게 메시지 보내기", "결제와 환불", "기록 삭제", "가격, 규칙, 설정 바꾸기", "손님 답장을 완료로 바꾸기",
        "답장에 쓴 숫자 확인 건너뛰기",
    ]
}

private enum ToolGroup: String, CaseIterable, Identifiable {
    case workshop = "T1"
    case customer = "T2"

    var id: Self { self }

    var title: String {
        switch self {
        case .workshop: "공방 안에서 끝나는 일"
        case .customer: "돈, 택배, 손님 상태가 바뀌는 일"
        }
    }

    var footer: String {
        switch self {
        case .workshop: "초안과 일정, 할 일처럼 손님에게 나가지 않고 되돌릴 수 있는 일이에요."
        case .customer: "‘알아서’여도 방금 하신 말씀에 근거가 있을 때 바로 해요. 없으면 제안으로 올려요."
        }
    }
}

/// "비서 자율성": how far the assistant may go. The stop control comes first, and every change saves at once.
struct AgentAutonomyView: View {
    @State private var loader = Loader<AgentSettings>()
    @State private var center = AgentCenter.shared

    var body: some View {
        LoadableContent(loader: loader, retry: load) { _ in
            if let settings = center.settings {
                form(settings)
            }
        }
        .navigationTitle("\(AssistantIdentity.name) 자율성")
        .navigationBarTitleDisplayMode(.inline)
        .task { await load() }
    }

    private func load() async {
        await loader.load { try await RoundupAPI.agentSettings() }
        if loader.errorMessage == nil, let loaded = loader.value { center.adopt(loaded) }
    }

    private func form(_ settings: AgentSettings) -> some View {
        ScrollViewReader { proxy in
            list(settings)
                // The refused control may be far below the reason, so the list moves to it.
                .onChange(of: center.settingsWarning) { _, warning in
                    guard let warning else { return }
                    withAnimation { proxy.scrollTo("agent.settings.state", anchor: .top) }
                    AccessibilityNotification.Announcement(warning).post()
                }
        }
    }

    private func list(_ settings: AgentSettings) -> some View {
        let isStopped = settings.mode == .off
        return List {
            stopSection(settings)
            if let warning = center.settingsWarning {
                CardSection {
                    HStack(alignment: .firstTextBaseline, spacing: 8) {
                        Image(systemName: "exclamationmark.circle.fill")
                            .foregroundStyle(.orange)
                            .accessibilityHidden(true)
                        Text(verbatim: warning)
                    }
                    .accessibilityElement(children: .combine)
                    .accessibilityIdentifier("agent.settings.warning")
                }
            }

            CardSection {
                Picker("맡기는 방식", selection: binding(settings.mode) { .mode($0) }) {
                    ForEach(AgentMode.allCases) { Text($0.title).tag($0) }
                }
                .adaptivePickerStyle()
                .accessibilityIdentifier("agent.settings.mode")
                Text(settings.mode.explanation)
                    .font(.subheadline)
                    .foregroundStyle(Color.secondaryText)
                    .accessibilityIdentifier("agent.settings.mode.explanation")
            } header: {
                Text("맡기는 방식")
            }

            CardSection {
                Toggle(isOn: binding(settings.proactive) { .proactive($0) }) {
                    explained("먼저 챙겨서 제안하기",
                              "확인이 늦은 주문이나 송장이 빠진 소포를 \(AssistantIdentity.name)가 먼저 찾아서 제안으로 올려요.")
                }
                .disabled(isStopped)
                .accessibilityIdentifier("agent.settings.proactive")
            }

            ForEach(ToolGroup.allCases) { group in
                let tools = settings.tools.filter { $0.tier == group.rawValue }
                if !tools.isEmpty {
                    CardSection {
                        if isStopped {
                            Text("멈춘 동안에는 일마다 따로 고를 수 없어요. 다시 맡기면 고를 수 있어요.")
                                .font(.subheadline)
                        }
                        ForEach(tools) { tool in
                            Picker(selection: binding(tool.mode) { .tool(tool.tool, $0) }) {
                                ForEach(AgentMode.allCases) { Text($0.title).tag($0) }
                            } label: {
                                explained(AgentToolCatalog.tools[tool.tool]?.title ?? tool.tool,
                                          AgentToolCatalog.tools[tool.tool]?.note)
                            }
                            .pickerStyle(.menu)
                            .disabled(isStopped)
                            .accessibilityIdentifier("agent.settings.tool.\(tool.tool)")
                        }
                    } header: {
                        Text(group.title)
                    } footer: {
                        Text(group.footer)
                    }
                }
            }

            CardSection {
                ForEach(AgentToolCatalog.neverDelegated, id: \.self) { title in
                    LabeledContent {
                        // A Label here stretches the row to several times its text.
                        HStack(spacing: 6) {
                            Image(systemName: "lock.fill")
                                .accessibilityHidden(true)
                            Text("맡길 수 없음")
                        }
                        .font(.subheadline)
                        .foregroundStyle(Color.secondaryText)
                    } label: {
                        Text(title)
                    }
                    .accessibilityElement(children: .combine)
                }
            } header: {
                Text("맡길 수 없는 일")
            } footer: {
                Text("손님에게 보내기, 결제, 환불, 기록 삭제는 어떤 설정으로도 \(AssistantIdentity.name)에게 맡길 수 없어요. \(AssistantIdentity.name)는 문장을 준비하고 보내는 일은 사장님이 직접 해요.")
            }

            limits(settings)

            CardSection {
                NavigationLink {
                    AgentMemoryListView()
                } label: {
                    Label { Text("\(AssistantIdentity.name)가 기억하는 것") } icon: { MenuIcon(systemName: "bookmark") }
                }
                .accessibilityIdentifier("agent.settings.memories")
            }
        }
        .cardList()
        .refreshable { await load() }
    }

    @ViewBuilder
    private func stopSection(_ settings: AgentSettings) -> some View {
        let isStopped = settings.mode == .off
        CardSection {
            Label {
                explained(isStopped ? "\(AssistantIdentity.name)를 멈췄어요" : "\(AssistantIdentity.name)가 일하고 있어요",
                          isStopped ? "스스로 하는 일도 올리는 제안도 없어요. 물어보시면 답만 해요."
                              : "지금은 ‘\(settings.mode.title)’ 방식이에요.", titleFont: .headline)
            } icon: {
                MenuIcon(systemName: isStopped ? "pause.circle" : "play.circle")
            }
            .accessibilityElement(children: .combine)
            .accessibilityIdentifier("agent.settings.state")
            .id("agent.settings.state")
            if isStopped {
                Button {
                    center.change(.mode(.ask))
                } label: {
                    Text("‘물어보고’로 다시 맡기기")
                        .font(.subheadline.weight(.semibold))
                        .frame(maxWidth: .infinity, minHeight: 30)
                }
                .buttonStyle(.bordered)
                .controlSize(.large)
                .accessibilityIdentifier("agent.settings.resume")
            } else {
                BK06PrimaryButton(title: "지금 모두 멈추기", identifier: "agent.settings.stop") {
                    center.change(.mode(.off))
                }
            }
        } footer: {
            Text("멈추면 진행 중인 일도 다음 단계에서 바로 멈춰요. 이미 끝낸 일은 그대로 남아요.")
        }
    }

    private func limits(_ settings: AgentSettings) -> some View {
        CardSection {
            Stepper(value: binding(settings.dailyCap) { .dailyCap($0) }, in: 1...50) {
                explained("하루에 알아서 하는 일", "최대 \(settings.dailyCap)건")
            }
            .accessibilityValue("최대 \(settings.dailyCap)건")
            .accessibilityIdentifier("agent.settings.cap")
            Toggle("조용한 시간", isOn: Binding(get: { settings.quietHours != nil }, set: { isOn in
                center.change(.quietHours(isOn ? AgentSettings.QuietHours(start: "22:00", end: "08:00") : nil))
            }))
            .accessibilityIdentifier("agent.settings.quiet")
            if let quiet = settings.quietHours {
                DatePicker("시작", selection: clock(quiet.start) { setQuiet(start: $0, end: quiet.end) },
                           displayedComponents: .hourAndMinute)
                    .accessibilityIdentifier("agent.settings.quiet.start")
                DatePicker("끝", selection: clock(quiet.end) { setQuiet(start: quiet.start, end: $0) },
                           displayedComponents: .hourAndMinute)
                    .accessibilityIdentifier("agent.settings.quiet.end")
            }
        } header: {
            Text("한도와 조용한 시간")
        } footer: {
            Text("하루 한도를 다 쓰면 맡기신 일은 제안으로 올려요. 먼저 챙겨서 올리는 제안도 하루에 이 건수까지예요. 조용한 시간에는 \(AssistantIdentity.name)가 먼저 제안하지 않아요.")
        }
        .environment(\.timeZone, Calendar.workshop.timeZone)
    }

    private func explained(_ title: String, _ note: String?, titleFont: Font = .body) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(verbatim: title)
                .font(titleFont)
            if let note {
                Text(verbatim: note)
                    .font(.subheadline)
                    .foregroundStyle(Color.secondaryText)
            }
        }
    }

    private func binding<Value>(_ value: Value, _ change: @escaping (Value) -> AgentSettingsChange) -> Binding<Value> {
        Binding(get: { value }, set: { center.change(change($0)) })
    }

    /// A stored "HH:mm" as a moment of today in the workshop's time zone, for a time picker.
    private func clock(_ text: String, save: @escaping (String) -> Void) -> Binding<Date> {
        let parts = text.split(separator: ":").compactMap { Int($0) }
        let moment = Calendar.workshop.date(
            bySettingHour: parts.first ?? 0, minute: parts.dropFirst().first ?? 0, second: 0, of: .now) ?? .now
        return Binding(get: { moment }, set: { save($0.clockTime) })
    }

    private func setQuiet(start: String, end: String) {
        guard start != end else {
            return center.rejectSetting("시작과 끝이 같으면 조용한 시간을 정할 수 없어요.")
        }
        center.change(.quietHours(AgentSettings.QuietHours(start: start, end: end)))
    }
}
