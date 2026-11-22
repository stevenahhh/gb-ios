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
            summary: "공방 한 곳이 모든 기능을 한 가격으로 써요.",
            items: [
                PlanItem(id: "reply_check", label: "답장 초안과 사실 검사",
                         allowance: PlanAllowance(amount: 100, unit: "건", isMonthly: true)),
                PlanItem(id: "voice", label: "음성 입력",
                         allowance: PlanAllowance(amount: 30, unit: "분", isMonthly: true)),
                PlanItem(id: "cancel_noshow", label: "취소와 노쇼 처리"),
                PlanItem(id: "outreach_quote", label: "출강 견적 계산"),
                PlanItem(id: "workshops", label: "공방",
                         allowance: PlanAllowance(amount: 1, unit: "곳", isMonthly: false))
            ]
        ),
        Plan(
            id: "none",
            name: "요금제 없이",
            monthlyPriceKRW: 0,
            summary: "새 답장 초안과 음성 입력은 쉬어요.",
            items: [
                PlanItem(id: "records", label: "저장한 기록 보기"),
                PlanItem(id: "manual", label: "직접 적고 고치기")
            ]
        )
    ]

    /// Picked before the owner has chosen anything: the plan pricing.json marks as primary.
    static let defaultPlanID = "gongdori"

    static let paymentNotice = "아직 결제되지 않아요."
    static let paymentDetail = "고른 요금제만 이 기기에 저장해요. 청구되는 금액은 없어요."

    /// pricing.json atLimit: pause and ask, never an automatic charge.
    static let atLimitLines = [
        "그 기능만 멈추고 어떻게 할지 먼저 여쭤봐요.",
        "자동으로 더 결제되지 않아요.",
        "직접 쓰는 건 계속할 수 있어요."
    ]

    /// Status provisional, limits not enforced yet, and a trial that is planned but not available.
    static let footnotes = [
        "가격과 횟수는 아직 정하는 중이라 바뀔 수 있어요.",
        "로그인과 공방 구분이 없어 한도는 아직 안내용이에요.",
        "14일 체험은 준비 중이에요. 체험이 끝나도 자동으로 결제되지 않아요."
    ]
}
