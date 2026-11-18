import Foundation

enum SampleData {
    static let inquiries: [Inquiry] = [
        Inquiry(
            id: "inquiry-clay", customer: "김하늘 (가상 고객)", subject: "도자기 체험 준비물",
            question: "처음 도자기를 만들어 봐요. 준비물이 있을까요? 완성품은 당일 가져갈 수 있나요?",
            facts: ["공방 안내 · 앞치마와 도구는 공방에서 제공합니다.",
                    "수업 안내 · 초보자도 참여할 수 있는 90분 수업입니다.",
                    "제작 안내 · 건조와 소성에 약 3주가 필요하며 당일 수령은 불가합니다."],
            draft: "안녕하세요! 처음 오셔도 괜찮아요. 앞치마와 도구는 준비되어 있습니다. 수업은 90분이며, 작품은 건조와 소성 후 약 3주 뒤 수령하실 수 있어요.",
            status: .pending
        ),
        Inquiry(
            id: "inquiry-group", customer: "이도윤 (가상 고객)", subject: "두 사람 함께 참여",
            question: "친구와 둘이 같은 시간에 참여하고 싶어요. 예약이 바로 확정되나요?",
            facts: ["예약 규정 · 예약은 별도 확인 후 확정합니다.",
                    "수업 정원 · 한 회차 최대 6명입니다.",
                    "데모 규칙 · 문의 답변 승인으로 예약이 생성되지 않습니다."],
            draft: "두 분이 함께 참여하실 수 있습니다. 원하시는 날짜와 회차를 알려 주시면 잔여 자리를 확인해 드릴게요. 이 답변만으로 예약이 확정되지는 않습니다.",
            status: .pending
        ),
        Inquiry(
            id: "inquiry-change", customer: "박서연 (가상 고객)", subject: "수업 일정 변경 안내",
            question: "예약한 수업 날짜를 바꾸고 싶어요. 어떻게 하면 되나요?",
            facts: ["변경 규정 · 수업 2일 전까지 일정 변경을 요청할 수 있습니다.",
                    "예약 규정 · 변경할 회차의 잔여 자리 확인이 필요합니다."],
            draft: "수업 2일 전까지 일정 변경을 요청하실 수 있어요. 현재 예약일과 원하시는 날짜를 알려 주시면 잔여 자리를 확인해 드리겠습니다.",
            status: .pending
        )
    ]

    static func sessions(on day: Date) -> [WorkshopSession] {
        [
            WorkshopSession(id: "session-morning", title: "흙으로 빚는 나의 첫 그릇",
                            startsAt: day.addingTimeInterval(10 * 3600), durationMinutes: 90, capacity: 6,
                            reservations: [
                                Reservation(id: "r1", customer: "정여름 (가상 고객)", people: 2),
                                Reservation(id: "r2", customer: "최바다 (가상 고객)", people: 1)
                            ]),
            WorkshopSession(id: "session-afternoon", title: "손으로 만드는 도자기 컵",
                            startsAt: day.addingTimeInterval(14 * 3600), durationMinutes: 90, capacity: 6,
                            reservations: [Reservation(id: "r3", customer: "윤새봄 (가상 고객)", people: 2)]),
            WorkshopSession(id: "session-tomorrow", title: "흙으로 빚는 나의 첫 그릇",
                            startsAt: day.addingTimeInterval(86400 + 11 * 3600), durationMinutes: 90, capacity: 6,
                            reservations: [Reservation(id: "r4", customer: "임가을 (가상 고객)", people: 1)])
        ]
    }
}
