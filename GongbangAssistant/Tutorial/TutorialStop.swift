import SwiftUI

/// The stops in the order they are shown. A stop whose element is not on screen drops out of the run.
enum TutorialStop: Int, CaseIterable, Identifiable {
    case approvals
    case cancellations
    case remainingWork
    case calendarAdd
    case assistantBar
    case settingsReplay

    var id: Int { rawValue }

    /// The elements this stop can point at, best first. The first one on screen gets the cut-out.
    var anchors: [TutorialAnchorID] {
        switch self {
        case .approvals: [.approvals]
        case .cancellations: [.cancellations]
        case .remainingWork: [.remainingWork]
        case .calendarAdd: [.calendarAdd, .calendarAddToolbar]
        case .assistantBar: [.assistantBar]
        case .settingsReplay: [.settingsReplay]
        }
    }

    /// The tab the element lives on. The assistant bar is on every tab, so it has none.
    var tab: AppTab? {
        switch self {
        case .approvals, .cancellations: .today
        case .remainingWork: .operations
        case .calendarAdd: .calendar
        case .assistantBar: nil
        case .settingsReplay: .settings
        }
    }

    /// The row in the onboarding step's list of what will be shown.
    var title: String {
        switch self {
        case .approvals: "확인해 주실 일과 답장"
        case .cancellations: "취소·노쇼"
        case .remainingWork: "운영의 남은 일"
        case .calendarAdd: "캘린더에 새 일정 넣기"
        case .assistantBar: "\(AssistantIdentity.name)에게 맡기기"
        case .settingsReplay: "설정 메뉴에 늘 있어요"
        }
    }

    var symbol: String {
        switch self {
        case .approvals: "checkmark.bubble"
        case .cancellations: "calendar.badge.exclamationmark"
        case .remainingWork: "tray.full"
        case .calendarAdd: "calendar.badge.plus"
        case .assistantBar: "text.bubble"
        case .settingsReplay: "gearshape"
        }
    }

    /// The coach mark's one sentence.
    var sentence: String {
        switch self {
        case .approvals: "\(AssistantIdentity.name)가 미리 써 둔 답장이 여기 있어요. 손볼 곳은 고치고, 괜찮으면 답장 완료를 누르시면 돼요."
        case .cancellations: "손님이 보내온 취소 문자를 붙이면 빈자리와 출석 체크를 이 화면 하나로 챙겨요."
        case .remainingWork: "이 기간 동안 마무리 못 한 일들을 이 자리에 모아 둬요."
        case .calendarAdd: "일정은 이 버튼으로 손수 넣어요."
        case .assistantBar: "화면 어디서든 이 버튼을 누르면 \(AssistantIdentity.name)에게 일을 부탁할 수 있어요."
        case .settingsReplay: "이 안내가 다시 필요하면 언제든 이 메뉴를 누르면 돼요."
        }
    }
}
