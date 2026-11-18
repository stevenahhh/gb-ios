import Foundation
import Observation

@Observable
public final class DemoStore {
    public private(set) var inquiries: [Inquiry]
    public private(set) var sessions: [WorkshopSession]
    public private(set) var referenceDay: Date
    public private(set) var isLoadingInquiries = false
    public private(set) var isSavingInquiry = false
    public private(set) var hasLoadedInquiries = false
    public private(set) var inquiryLoadError: String?
    public private(set) var requiresInquiryReload = false
    @ObservationIgnored private let repository: (any InquiryRepository)?
    public var isSample: Bool { repository == nil }
    public var isInquiryBusy: Bool { isLoadingInquiries || isSavingInquiry }
    public static var calendar: Calendar {
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = TimeZone(identifier: "Asia/Seoul") ?? .gmt
        calendar.locale = Locale(identifier: "ko_KR")
        return calendar
    }

    public init(now: Date = Date()) {
        repository = nil
        let day = Self.calendar.startOfDay(for: now)
        referenceDay = day
        inquiries = SampleData.inquiries
        sessions = SampleData.sessions(on: day)
        hasLoadedInquiries = true
    }

    public init(repository: any InquiryRepository, now: Date = Date()) {
        self.repository = repository
        let day = Self.calendar.startOfDay(for: now)
        referenceDay = day
        inquiries = []
        sessions = SampleData.sessions(on: day)
    }

    public var pendingInquiries: [Inquiry] { inquiries.filter { $0.status == .pending } }
    public var pendingCount: Int { pendingInquiries.count }
    public var reservationCount: Int { sessions.reduce(0) { $0 + $1.reservations.count } }

    public func sessions(on day: Date) -> [WorkshopSession] {
        sessions.filter { Self.calendar.isDate($0.startsAt, inSameDayAs: day) }
            .sorted { $0.startsAt < $1.startsAt }
    }

    public func inquiry(id: String) -> Inquiry? { inquiries.first { $0.id == id } }
    public func session(id: String) -> WorkshopSession? { sessions.first { $0.id == id } }

    public func editDraft(id: String, text: String) throws {
        guard isSample else { throw InquiryPersistenceError.sampleOnly }
        guard let index = inquiries.firstIndex(where: { $0.id == id }) else {
            throw ReplyError.missingInquiry
        }
        guard inquiries[index].status == .pending else { throw ReplyError.alreadyDecided }
        inquiries[index].draft = text
    }

    public func decide(id: String, decision: ReplyDecision) throws {
        guard isSample else { throw InquiryPersistenceError.sampleOnly }
        guard let index = inquiries.firstIndex(where: { $0.id == id }) else {
            throw ReplyError.missingInquiry
        }
        guard inquiries[index].status == .pending else { throw ReplyError.alreadyDecided }
        let text = inquiries[index].draft.trimmingCharacters(in: .whitespacesAndNewlines)
        switch decision {
        case .approve:
            // An empty reply must never go out; an empty draft can still be rejected.
            guard !text.isEmpty else { throw ReplyError.emptyDraft }
            inquiries[index].draft = text
            inquiries[index].status = .approved
        case .reject:
            inquiries[index].draft = text
            inquiries[index].status = .rejected
        }
    }

    public func reset(now: Date = Date()) {
        // This legacy demo action must never imply that server decisions were reset.
        guard isSample else { return }
        referenceDay = Self.calendar.startOfDay(for: now)
        inquiries = SampleData.inquiries
        sessions = SampleData.sessions(on: referenceDay)
    }

    @MainActor
    public func loadInquiries() async {
        guard let repository, !isInquiryBusy else { return }
        isLoadingInquiries = true
        defer { isLoadingInquiries = false }
        do {
            inquiries = try await repository.load()
            hasLoadedInquiries = true
            requiresInquiryReload = false
            inquiryLoadError = nil
        } catch {
            inquiryLoadError = "문의를 불러오지 못했어요. " + error.localizedDescription
        }
    }

    @MainActor
    public func saveDraft(id: String, draft: InquiryDraft) async throws {
        guard let repository else {
            try editDraft(id: id, text: draft.draft)
            return
        }
        let current = try writableInquiry(id: id)
        guard current.revision == draft.expectedRevision else { throw InquiryPersistenceError.conflict }
        isSavingInquiry = true
        defer { isSavingInquiry = false }
        do {
            let saved = try await repository.save(id: id, draft: draft)
            replace(saved)
        } catch {
            requiresInquiryReload = true
            throw error
        }
    }

    @MainActor
    public func decide(id: String, decision: InquiryDecision) async throws {
        guard let repository else {
            try editDraft(id: id, text: decision.draft)
            try decide(id: id, decision: decision.decision)
            return
        }
        let current = try writableInquiry(id: id)
        guard current.revision == decision.expectedRevision else { throw InquiryPersistenceError.conflict }
        if case .approve = decision.decision {
            guard !decision.draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
                throw ReplyError.emptyDraft
            }
        }
        isSavingInquiry = true
        defer { isSavingInquiry = false }
        do {
            replace(try await repository.decide(id: id, decision: decision))
        } catch {
            // A lost response can follow a committed write. Reconcile before retrying.
            requiresInquiryReload = true
            throw error
        }
    }

    @MainActor
    private func writableInquiry(id: String) throws -> Inquiry {
        guard !isInquiryBusy else { throw InquiryPersistenceError.busy }
        guard !requiresInquiryReload else { throw InquiryPersistenceError.conflict }
        guard let current = inquiry(id: id) else { throw ReplyError.missingInquiry }
        guard current.status == .pending else { throw ReplyError.alreadyDecided }
        return current
    }

    private func replace(_ saved: Inquiry) {
        if let index = inquiries.firstIndex(where: { $0.id == saved.id }) {
            inquiries[index] = saved
        }
    }
}
