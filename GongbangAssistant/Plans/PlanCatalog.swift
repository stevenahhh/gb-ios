import Foundation

/// A cap on one included thing: an allowance that refills each month, or a fixed total such as one workshop.
struct PlanAllowance: Hashable {
    let amount: Int
    let unit: String
    let isMonthly: Bool
}

struct PlanItem: Identifiable, Hashable {
    let id: String
    let label: String
    var allowance: PlanAllowance?
}

struct Plan: Identifiable, Hashable {
    let id: String
    let name: String
    /// Per month in KRW, VAT included. Zero is the option without a subscription.
    let monthlyPriceKRW: Int
    let summary: String
    let items: [PlanItem]
}

/// Every price, limit and sentence the 요금제 screens show. Data only: edit here and each screen follows.
/// Mirrors .omo/evidence/onboarding/pricing.json (version 1, status provisional, 2026-11-22).
enum PlanCatalog {
    static let options: [Plan] = [
        Plan(
            id: "gongdori",
            name: "공도리",
            monthlyPriceKRW: 14_900,
            summary: "요금제 하나로 공방 한 곳이 기능 전부를 써요.",
            items: [
                PlanItem(id: "reply_check", label: "초안 쓰기·숫자 비교",
                         allowance: PlanAllowance(amount: 100, unit: "건", isMonthly: true)),
                PlanItem(id: "voice", label: "음성 입력",
                         allowance: PlanAllowance(amount: 30, unit: "분", isMonthly: true)),
                PlanItem(id: "cancel_noshow", label: "취소·노쇼 챙기기"),
                PlanItem(id: "outreach_quote", label: "출장 수업 견적 계산"),
                PlanItem(id: "workshops", label: "공방",
                         allowance: PlanAllowance(amount: 1, unit: "곳", isMonthly: false))
            ]
        ),
        Plan(
            id: "none",
            name: "요금제 없이",
            monthlyPriceKRW: 0,
            summary: "새 답장 초안 쓰기와 음성 입력은 멈춰요.",
            items: [
                PlanItem(id: "records", label: "예전 기록 보기"),
                PlanItem(id: "manual", label: "손으로 적고 고치기")
            ]
        )
    ]

    /// Picked before the owner has chosen anything: the plan pricing.json marks as primary.
    static let defaultPlanID = "gongdori"

    static let paymentNotice = "아직 결제되지 않아요."
    static let paymentDetail = "고르신 요금제는 지금 이 아이폰 안에만 적어 둬요. 돈이 빠져나가는 일은 없어요."

    /// pricing.json atLimit: pause and ask, never an automatic charge.
    static let atLimitLines = [
        "그 기능만 잠시 멈추고 어떻게 할지 사장님께 먼저 여쭤볼게요.",
        "더 쓴다고 돈이 저절로 빠져나가지 않아요.",
        "손으로 쓰고 고치는 건 그대로 이어서 하셔도 돼요."
    ]

    /// Status provisional, limits not enforced yet, and a trial that is planned but not available.
    static let footnotes = [
        "요금과 이용 횟수는 확정 전이라 앞으로 달라질 수 있어요.",
        "아직 로그인이 없고 공방끼리 계정도 안 나뉘어서 한도는 참고로만 보여 드려요.",
        "무료로 14일 써 보는 기능은 아직 만드는 중이에요. 써 보는 기간이 끝나도 돈이 저절로 빠져나가지 않아요."
    ]
}
