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
        case .calendarAdd: "캘린더에서 일정 추가"
        case .assistantBar: "\(AssistantIdentity.name)에게 부탁하기"
        case .settingsReplay: "설정에서 다시 보기"
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
        case .approvals: "\(AssistantIdentity.name)가 써 둔 답장을 읽어 보고 고치거나 답변 완료를 눌러요."
        case .cancellations: "손님이 보낸 취소 메시지를 붙여넣고 빈자리와 출석을 여기서 챙겨요."
        case .remainingWork: "이 기간에 아직 처리하지 않은 일을 여기서 모아 봐요."
        case .calendarAdd: "일정은 여기서 직접 추가해요."
        case .assistantBar: "어느 화면에서든 여기를 눌러 \(AssistantIdentity.name)에게 부탁해요."
        case .settingsReplay: "이 안내는 여기서 언제든 다시 볼 수 있어요."
        }
    }
}
