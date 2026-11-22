import Foundation

extension RoundupAPI {
    private struct Empty: Encodable {}

    // MARK: K06 rules

    static func k06Policies() async throws -> [BK06PolicyVersion] { try await get("policy/versions") }

    static func k06Extract(text: String) async throws -> BK06PolicyDraft {
        struct Body: Encodable { let text: String }
        return try await post("policy/extract", Body(text: text))
    }

    static func k06SavePolicy(rules: [BK06Rule], late: BK06LateRule?, unread: [String], sourceText: String)
        async throws -> BK06PolicyVersion {
        struct Body: Encodable { let rules: [BK06Rule]; let late: BK06LateRule?; let unread: [String]; let sourceText: String }
        return try await post("policy/versions", Body(rules: rules, late: late, unread: unread, sourceText: sourceText))
    }

    static func k06Notice(bookingID: String) async throws -> BK06Notice {
        struct Body: Encodable { let bookingId: String }
        return try await post("policy/notices", Body(bookingId: bookingID))
    }

    // MARK: K06 cancellations

    static func k06Intake(message: String) async throws -> BK06Intake {
        struct Body: Encodable { let message: String }
        return try await post("cancellations/intake", Body(message: message))
    }

    static func k06Quote(bookingID: String, category: String?) async throws -> BK06Quote {
        struct Body: Encodable { let bookingId: String; let reasonCategory: String? }
        return try await post("cancellations/quote", Body(bookingId: bookingID, reasonCategory: category))
    }

    struct BK06DecisionBody: Encodable {
        let decision: BK06Decision
        let reason: String
        let reasonCategory: String?
        let refundWon: Int?
        let expectedRevision: Int
        let pastedAt: String
        let cardShownAt: String
    }

    static func k06Decide(bookingID: String, body: BK06DecisionBody) async throws -> BK06DecisionResult {
        try await post("cancellations/\(bookingID)/decision", body)
    }

    static func k06Draft(caseID: String) async throws -> BK06Draft {
        try await post("cancellations/cases/\(caseID)/draft", Empty())
    }

    static func k06Approve(caseID: String, draft: String) async throws {
        struct Body: Encodable { let draft: String }
        struct Approved: Decodable { let editChars: Int }
        let _: Approved = try await post("cancellations/cases/\(caseID)/approve", Body(draft: draft))
    }

    static func k06UndoDecision(caseID: String) async throws {
        let _: BK06Removed = try await post("cancellations/cases/\(caseID)/undo", Empty())
    }

    static func k06Cases() async throws -> [BK06Case] { try await get("cancellations/cases") }

    static func k06RemoveCases(bookingID: String) async throws {
        let _: BK06Removed = try await send(
            method: "DELETE", path: "bookings/\(bookingID)/cancellation-cases", body: Empty())
    }

    // MARK: K06 classes

    static func k06Cards() async throws -> BK06Cards {
        #if DEBUG
        // Demos and screenshots move only this read's clock, for example to 15 minutes after a class starts.
        // Sent in UTC, because a query leaves the "+" of an offset unescaped and the server reads it as a space.
        if let at = ProcessInfo.processInfo.environment["ROUNDUP_K06_AT"].flatMap(BK06Format.date) {
            return try await get("k06/cards", query: ["at": at.ISO8601Format()])
        }
        #endif
        return try await get("k06/cards")
    }

    static func k06Attendance(bookingID: String, arrived: Bool) async throws -> BK06Attendance {
        struct Body: Encodable { let status: String }
        return try await post("bookings/\(bookingID)/attendance", Body(status: arrived ? "arrived" : "no_show"))
    }

    static func k06UndoAttendance(bookingID: String) async throws {
        let _: BK06Attendance = try await post("bookings/\(bookingID)/undo-attendance", Empty())
    }

    static func k06Session(id: String) async throws -> BK06SessionDetail { try await get("class-sessions/\(id)/k06") }
    static func k06Refill(sessionID: String) async throws -> BK06Refill { try await get("class-sessions/\(sessionID)/refill") }

    static func k06SavePlan(sessionID: String, minSeats: Int?, deadline: Date?, materialWon: Int?) async throws {
        struct Body: Encodable {
            let minSeats: Int?
            let materialOrderDeadline: String?
            let materialWon: Int?
            enum CodingKeys: CodingKey { case minSeats, materialOrderDeadline, materialWon }
            // The server requires every key, so an unset value is sent as null.
            func encode(to encoder: any Encoder) throws {
                var container = encoder.container(keyedBy: CodingKeys.self)
                try container.encode(minSeats, forKey: .minSeats)
                try container.encode(materialOrderDeadline, forKey: .materialOrderDeadline)
                try container.encode(materialWon, forKey: .materialWon)
            }
        }
        let _: BK06SessionDetail = try await send(method: "PUT", path: "class-sessions/\(sessionID)/plan", body: Body(
            minSeats: minSeats, materialOrderDeadline: deadline?.ISO8601Format(), materialWon: materialWon))
    }

    static func k06AddWaiting(sessionID: String, name: String, phone: String, isMakeup: Bool) async throws {
        struct Body: Encodable { let customerName, phone, source: String }
        let _: BK06SessionDetail = try await post("class-sessions/\(sessionID)/waitlist", Body(
            customerName: name, phone: phone, source: isMakeup ? "makeup" : "waitlist"))
    }

    static func k06RemoveWaiting(sessionID: String, entryID: String) async throws {
        let _: BK06Removed = try await send(
            method: "DELETE", path: "class-sessions/\(sessionID)/waitlist/\(entryID)", body: Empty())
    }

    static func k06UnderMin(sessionID: String, decision: String, mergeInto: String?, revision: Int) async throws
        -> BK06UnderMinResult {
        struct Body: Encodable { let decision: String; let mergeInto: String?; let expectedRevision: Int }
        return try await post("class-sessions/\(sessionID)/under-min-decision", Body(
            decision: decision, mergeInto: mergeInto, expectedRevision: revision))
    }
}
