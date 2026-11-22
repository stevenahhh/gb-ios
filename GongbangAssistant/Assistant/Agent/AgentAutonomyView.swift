import SwiftUI

extension AgentMode {
    var title: String {
        switch self {
        case .off: "꺼 두기"
        case .ask: "물어보고 하기"
        case .auto: "알아서 하기"
        }
    }

    var explanation: String {
        switch self {
        case .off: "\(AssistantIdentity.name)는 먼저 나서지 않아요. 물어보실 때만 대답해요."
        case .ask: "무언가 바꿔야 할 땐 확인 요청부터 보내요. 사장님이 수락하시면 그때 움직여요."
        case .auto: "말씀하신 내용이 있으면 묻지 않고 바로 해요. 되돌릴 수 있는 일이면 되돌리기 버튼도 같이 띄워요. 말씀하신 게 없을 땐 확인 요청을 보내요."
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
        "save_reply_draft": Entry(title: "문의 답장 초안 준비", note: "사장님 대신 손님께 보내지는 않아요. 초안까지만 준비해 둘게요."),
        "save_content_draft": Entry(title: "홍보 글 초안 준비", note: "초안까지만 준비해요. 게시는 사장님이 직접 하세요."),
        "add_event": Entry(title: "새 일정 추가", note: "캘린더에 새 일정을 추가해요."),
        "move_event": Entry(title: "일정 날짜 바꾸기", note: "잡아 둔 일정을 다른 날이나 다른 시간으로 옮겨요."),
        "complete_task": Entry(title: "할 일 끝냈다고 체크", note: "다 하신 할 일에 체크를 해 드려요."),
        "reopen_task": Entry(title: "할 일 체크 풀기", note: "체크해 둔 할 일을 다시 해야 할 일로 돌려요."),
        "remember": Entry(title: "메모해 두기", note: "‘이거 기억해 줘’ 하신 말을 메모장에 남겨요."),
        "forget": Entry(title: "메모 지우기", note: "‘이건 잊어 줘’ 하신 메모를 지워 드려요."),
        "confirm_order": Entry(title: "주문 확인", note: "돈이 들어온 주문에 확인 표시를 해요."),
        "mark_packed": Entry(title: "포장 완료로 바꾸기", note: "다 싼 소포를 포장 완료로 바꿔요."),
        "register_invoice": Entry(
            title: "송장 등록", note: "말씀하시거나 붙여 넣으신 송장번호를 숫자 하나 바꾸지 않고 등록해요. 그 번호가 맞는지 택배사에 물어보지는 않아요."),
        "mark_delivered": Entry(title: "배송 완료로 바꾸기", note: "손님이 받은 소포를 배송 완료로 바꿔요."),
        "confirm_deposit": Entry(title: "예약금 확인", note: "돈이 들어온 예약을 입금 확인으로 바꿔요."),
        "create_booking": Entry(title: "예약 잡기", note: "이름이랑 인원만 말씀해 주시면 그대로 예약을 잡아 드려요."),
        "decide_cancellation": Entry(title: "취소 결정 기록", note: "취소를 어떻게 할지 사장님이 정하신 내용만 메모해요. 환불금을 보내지는 않아요."),
        "record_quote_outcome": Entry(title: "출장 수업 견적 결과 메모", note: "출장 수업 견적이 잘 됐는지 안 됐는지 메모해요."),
    ]

    /// What no setting hands to the assistant; the server offers it no tool for any of these.
    static let neverDelegated = [
        "손님께 메시지 전송", "결제와 환불", "기록 지우기", "가격이나 규칙, 설정 고치기", "손님 답장을 끝난 일로 표시",
        "답장 속 숫자를 확인하지 않고 넘기기",
    ]
}

private enum ToolGroup: String, CaseIterable, Identifiable {
    case workshop = "T1"
    case customer = "T2"

    var id: Self { self }

    var title: String {
        switch self {
        case .workshop: "공방 안에서만 마무리되는 일"
        case .customer: "돈이 오가거나 택배, 손님 쪽에 영향 가는 일"
        }
    }

    var footer: String {
        switch self {
        case .workshop: "손님께 나가지 않고 되돌릴 수 있는 일이에요. 초안, 일정, 할 일 같은 것들요."
        case .customer: "‘알아서 하기’로 맡기셔도 방금 말씀하신 내용이 있어야 바로 움직여요. 그게 없으면 확인 요청부터 보내요."
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
        .navigationTitle("\(AssistantIdentity.name)에게 맡기는 범위")
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
                Picker("어떻게 맡길까요", selection: binding(settings.mode) { .mode($0) }) {
                    ForEach(AgentMode.allCases) { Text($0.title).tag($0) }
                }
                .adaptivePickerStyle()
                .accessibilityIdentifier("agent.settings.mode")
                Text(settings.mode.explanation)
                    .font(.subheadline)
                    .foregroundStyle(Color.secondaryText)
                    .accessibilityIdentifier("agent.settings.mode.explanation")
            } header: {
                Text("어떻게 맡길까요")
            }

            CardSection {
                Toggle(isOn: binding(settings.proactive) { .proactive($0) }) {
                    explained("먼저 챙겨서 확인 요청 보내기",
                              "주문 확인이 밀렸거나 소포에 송장이 빠졌으면 \(AssistantIdentity.name)가 미리 찾아 확인 요청으로 알려 드려요.")
                }
                .disabled(isStopped)
                .accessibilityIdentifier("agent.settings.proactive")
            }

            ForEach(ToolGroup.allCases) { group in
                let tools = settings.tools.filter { $0.tier == group.rawValue }
                if !tools.isEmpty {
                    CardSection {
                        if isStopped {
                            Text("꺼 두신 동안엔 일마다 정할 수 없어요. 다시 켜시면 그때 하나하나 고르시면 돼요.")
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
                            Text("맡기실 수 없어요")
                        }
                        .font(.subheadline)
                        .foregroundStyle(Color.secondaryText)
                    } label: {
                        Text(title)
                    }
                    .accessibilityElement(children: .combine)
                }
            } header: {
                Text("비서가 손댈 수 없는 일")
            } footer: {
                Text("설정을 어떻게 바꾸셔도 \(AssistantIdentity.name)는 손님께 연락하거나 돈을 주고받거나 기록을 지우지 않아요. 글을 써 두는 데까지가 \(AssistantIdentity.name)의 일이고 전송은 사장님 손으로 하세요.")
            }

            limits(settings)

            CardSection {
                NavigationLink {
                    AgentMemoryListView()
                } label: {
                    Label { Text("\(AssistantIdentity.name)가 메모해 둔 말") } icon: { MenuIcon(systemName: "bookmark") }
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
                explained(isStopped ? "\(AssistantIdentity.name)가 쉬고 있어요" : "\(AssistantIdentity.name)가 지금 일하는 중이에요",
                          isStopped ? "먼저 나서지도, 확인 요청을 보내지도 않아요. 물어보실 때만 대답해요."
                              : "‘\(settings.mode.title)’로 맡겨 두신 상태예요.", titleFont: .headline)
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
                    Text("다시 켜고 ‘물어보고 하기’로 두기")
                        .font(.subheadline.weight(.semibold))
                        .frame(maxWidth: .infinity, minHeight: 30)
                }
                .buttonStyle(.bordered)
                .controlSize(.large)
                .accessibilityIdentifier("agent.settings.resume")
            } else {
                BK06PrimaryButton(title: "전부 멈추기", identifier: "agent.settings.stop") {
                    center.change(.mode(.off))
                }
            }
        } footer: {
            Text("누르시면 하던 일도 다음 단계로 가기 전에 멈춰요. 벌써 마친 일은 되돌리지 않아요.")
        }
    }

    private func limits(_ settings: AgentSettings) -> some View {
        CardSection {
            Stepper(value: binding(settings.dailyCap) { .dailyCap($0) }, in: 1...50) {
                explained("하루에 혼자 해도 되는 일", "하루 \(settings.dailyCap)건까지")
            }
            .accessibilityValue("하루 \(settings.dailyCap)건까지")
            .accessibilityIdentifier("agent.settings.cap")
            Toggle("방해 금지 시간", isOn: Binding(get: { settings.quietHours != nil }, set: { isOn in
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
            Text("하루 한도와 방해 금지 시간")
        } footer: {
            Text("오늘 몫을 다 채우면 그다음 부탁부터는 확인 요청으로 보내요. \(AssistantIdentity.name)가 나서서 챙기는 확인 요청도 똑같이 세요. 방해 금지 시간이 되면 먼저 말을 걸지 않아요.")
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
            return center.rejectSetting("시작과 끝 시각을 다르게 골라야 방해 금지 시간을 정할 수 있어요.")
        }
        center.change(.quietHours(AgentSettings.QuietHours(start: start, end: end)))
    }
}
