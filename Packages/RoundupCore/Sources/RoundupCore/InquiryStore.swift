import Foundation
import Observation

/// Server-backed inquiry state. It holds only what the repository returned.
@Observable
public final class InquiryStore {
    public private(set) var inquiries: [Inquiry] = []
    public private(set) var isLoadingInquiries = false
    public private(set) var isSavingInquiry = false
    public private(set) var hasLoadedInquiries = false
    public private(set) var inquiryLoadError: String?
    /// When inquiries last loaded successfully, shown as "마지막 확인 3:05" while offline.
    public private(set) var lastLoadedAt: Date?
    public private(set) var requiresInquiryReload = false
    @ObservationIgnored private let repository: any InquiryRepository
    public var isInquiryBusy: Bool { isLoadingInquiries || isSavingInquiry }

    public init(repository: any InquiryRepository) {
        self.repository = repository
    }

    public var pendingInquiries: [Inquiry] { inquiries.filter { $0.status == .pending } }
    public var pendingCount: Int { pendingInquiries.count }

    public func inquiry(id: String) -> Inquiry? { inquiries.first { $0.id == id } }

    @MainActor
    public func loadInquiries() async {
        guard !isInquiryBusy else { return }
        isLoadingInquiries = true
        defer { isLoadingInquiries = false }
        do {
            inquiries = try await repository.load()
            hasLoadedInquiries = true
            lastLoadedAt = Date()
            requiresInquiryReload = false
            inquiryLoadError = nil
        } catch {
            inquiryLoadError = "연결이 끊겨 문의를 불러오지 못했어요."
        }
    }

    @MainActor
    public func saveDraft(id: String, draft: InquiryDraft) async throws {
        let current = try writableInquiry(id: id)
        guard current.revision == draft.expectedRevision else { throw InquiryPersistenceError.conflict }
        if current.status == .approved, Self.isBlank(draft.draft) { throw ReplyError.emptyDraft }
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
        let current = try writableInquiry(id: id)
        guard current.revision == decision.expectedRevision else { throw InquiryPersistenceError.conflict }
        guard !Self.isBlank(decision.draft) else { throw ReplyError.emptyDraft }
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
        return current
    }

    private static func isBlank(_ text: String) -> Bool {
        text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }

    private func replace(_ saved: Inquiry) {
        if let index = inquiries.firstIndex(where: { $0.id == saved.id }) {
            inquiries[index] = saved
        }
    }
}
