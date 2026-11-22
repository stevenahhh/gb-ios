import Foundation

/// Where a new quote starts: the id to open and when the owner began reading the inquiry.
struct OutreachOpened: Hashable, Identifiable {
    let id: String
    let startedAt: Date?
}

struct OutreachQuoteRequest: Encodable {
    let fields: OutreachFields
    let classId: String
    let headcount: Int
    let assistants: Int
    let travelMinutes: Int?
    let distanceKm: Int?
    let signals: [OutreachSignal]
    let abArm = "B"
}

/// Only the changed numbers; a missing key keeps the stored value.
struct OutreachAdjustment: Encodable, Hashable {
    var headcount: Int?
    var perPersonKrw: Int?
    var assistants: Int?
    var travelMinutes: Int?
    var distanceKm: Int?
}

struct OutreachClassCostUpdate: Encodable {
    let materialPerPersonKrw: Int
    let onedayPriceKrw: Int
    let prepMinutes: Int
    let cleanupMinutes: Int
    let maxHeadcount: Int
}

extension RoundupAPI {
    private struct Empty: Encodable {}

    static func extractOutreach(text: String) async throws -> OutreachExtraction {
        struct Body: Encodable { let text: String }
        return try await post("outreach/extract", Body(text: text))
    }

    static func outreachQuotes() async throws -> [OutreachQuoteRow] { try await get("outreach/quotes") }
    static func outreachQuote(id: String) async throws -> OutreachQuote { try await get("outreach/quotes/\(id)") }

    static func createOutreachQuote(_ request: OutreachQuoteRequest) async throws -> OutreachQuote {
        try await post("outreach/quotes", request)
    }

    static func recalculateOutreachQuote(id: String, _ change: OutreachAdjustment) async throws -> OutreachQuote {
        try await post("outreach/quotes/\(id)/recalculate", change)
    }

    static func verifyOutreachOrg(id: String) async throws {
        struct Verified: Decodable { let locked: Bool }
        let _: Verified = try await post("outreach/quotes/\(id)/verify-org", Empty())
    }

    static func markOutreachSent(id: String, elapsedSeconds: Int?, followUpAt: Date?) async throws -> OutreachQuote {
        struct Body: Encodable { let elapsedSeconds: Int?; let followUpAt: String? }
        return try await post("outreach/quotes/\(id)/sent", Body(
            elapsedSeconds: elapsedSeconds, followUpAt: followUpAt?.ISO8601Format()))
    }

    static func recordOutreachOutcome(id: String, outcome: OutreachOutcome, finalTotal: Int?) async throws -> OutreachQuote {
        struct Body: Encodable { let outcome: OutreachOutcome; let finalTotalKrw: Int? }
        return try await post("outreach/quotes/\(id)/outcome", Body(outcome: outcome, finalTotalKrw: finalTotal))
    }

    static func outreachCosts() async throws -> OutreachCostSettings { try await get("settings/class-costs") }

    static func saveClassCost(classID: String, _ cost: OutreachClassCostUpdate) async throws -> OutreachCostSettings {
        try await send(method: "PUT", path: "settings/class-costs/\(classID)", body: cost)
    }

    static func saveOutreachDefaults(_ defaults: OutreachDefaults) async throws -> OutreachCostSettings {
        try await send(method: "PUT", path: "settings/outreach-defaults", body: defaults)
    }
}
