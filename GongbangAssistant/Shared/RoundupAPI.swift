import Foundation
import RoundupCore

struct RoundupAPIError: LocalizedError {
    let message: String
    var isConflict = false
    var errorDescription: String? { message }
}

struct GeocodeResult: Decodable, Equatable {
    let address: String
    let lat: Double
    let lng: Double
}

/// Reads connection settings; nothing here has a built-in production default.
enum RoundupConfiguration {
    private static let secrets: NSDictionary? = Bundle.main.url(forResource: "RoundupSecrets", withExtension: "plist")
        .flatMap { NSDictionary(contentsOf: $0) }

    static func baseURL() throws -> URL {
        // A launch environment value wins even when empty, so tests never fall through to bundled production settings.
        let candidates = ProcessInfo.processInfo.environment["ROUNDUP_API_URL"].map { [$0] } ?? [
            Bundle.main.object(forInfoDictionaryKey: "RoundupAPIURL") as? String,
            secrets?["APIURL"] as? String,
        ].compactMap { $0 }
        guard let value = candidates.map({ $0.trimmingCharacters(in: .whitespaces) }).first(where: { !$0.isEmpty }),
              let url = URL(string: value), let host = url.host(),
              url.scheme == "https" || (url.scheme == "http" && loopbackHosts.contains(host)) else {
            throw RoundupAPIError(message: "서버 주소가 설정되지 않았어요. ROUNDUP_API_URL 또는 RoundupAPIURL을 설정해 주세요.")
        }
        return url
    }

    /// App Transport Security must allow the pinned IP-address server, so plain HTTP is limited here.
    private static let loopbackHosts: Set<String> = ["127.0.0.1", "localhost", "::1"]

    static func apiKey() throws -> String {
        #if DEBUG
        if let key = ProcessInfo.processInfo.environment["ROUNDUP_API_KEY"], !key.isEmpty { return key }
        #endif
        guard let key = secrets?["APIKey"] as? String, !key.isEmpty else {
            throw RoundupAPIError(message: "서버 인증 키가 설정되지 않았어요. RoundupSecrets.plist를 확인해 주세요.")
        }
        return key
    }
}

enum RoundupAPI {
    private struct Revisioned: Encodable { let expectedRevision: Int }
    private struct Completion: Encodable { let done: Bool; let expectedRevision: Int }
    private struct Acknowledged: Decodable {}

    // MARK: Screens

    static func today() async throws -> TodayScreenData { try await get("today") }

    static func operations(period: OperationPeriod?) async throws -> OperationsData {
        try await get("operations", query: period?.query ?? [:])
    }

    /// The collector routes spell their keys in snake_case and send moments as ISO 8601 text. This decoder reads
    /// both into the camelCase `Date` fields the other models use.
    private static let collectorDecoder: JSONDecoder = {
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        decoder.dateDecodingStrategy = .iso8601
        return decoder
    }()

    static func collectorStatus() async throws -> CollectorStatus {
        try await get("collectors/status", decoder: collectorDecoder)
    }

    static func calendar(start: Date, end: Date) async throws -> CalendarRange {
        try await get("calendar", query: ["start": start.dayKey, "end": end.dayKey])
    }

    static func area(_ area: OperationArea, query: AreaQuery) async throws -> AreaPage {
        var parameters = ["limit": String(query.limit), "offset": String(query.offset)]
        parameters[area.filterParameter] = query.filter
        if !query.text.isEmpty { parameters["q"] = query.text }
        if let sort = query.sort { parameters["sort"] = sort }
        return try await get(area.path, query: parameters)
    }

    static func settings() async throws -> SettingsData { try await get("settings") }
    static func opportunities() async throws -> [WorkItem] { try await get("opportunities") }
    static func classSessions() async throws -> [SessionOption] { try await get("class-sessions") }
    static func booking(id: String) async throws -> BookingDetail { try await get("bookings/\(id)") }
    static func classSession(id: String) async throws -> ClassSessionDetail { try await get("class-sessions/\(id)") }
    static func bookings(sessionID: String) async throws -> AreaPage { try await get("bookings", query: ["session": sessionID]) }
    static func card(kind: CardKind, id: String) async throws -> WorkItem { try await get("cards/\(kind.rawValue)/\(id)") }
    static func assistantDraft(kind: DraftKind, id: String) async throws -> AssistantDraftDetail {
        try await get("assistant-drafts/\(kind.rawValue)/\(id)")
    }

    // MARK: Actions

    /// Performs a card action that needs no further input and returns the changed row, which carries its undo.
    /// An order card's parcel steps write the parcel the action targets.
    static func perform(_ code: ActionCode, on item: WorkItem) async throws -> WorkItem {
        let target = item.actionTarget
        let revision = Revisioned(expectedRevision: target.revision)
        switch code {
        case .confirmDeposit: return try await post("bookings/\(target.id)/confirm-deposit", revision)
        case .confirmOrder: return try await post("orders/\(target.id)/confirm", revision)
        case .pack: return try await post("shipments/\(target.id)/pack", revision)
        case .markDelivered: return try await post("shipments/\(target.id)/deliver", revision)
        case .acknowledgeRecommendation: return try await post("recommendations/\(target.id)/acknowledge", revision)
        case .completeTask:
            return try await post("tasks/\(target.id)/completion", Completion(done: true, expectedRevision: target.revision))
        case .registerInvoice, .reviewContent:
            preconditionFailure("\(code) is completed on its own screen")
        }
    }

    private struct BatchItem: Encodable { let id: String; let expectedRevision: Int }
    private struct Batch: Encodable { let items: [BatchItem] }

    /// Takes one fulfilment step on several rows in one transaction; one refused row changes none.
    static func perform(_ code: ActionCode, on items: [WorkItem]) async throws -> [WorkItem] {
        let path = switch code {
        case .confirmOrder: "orders/confirm"
        case .pack: "shipments/pack"
        case .markDelivered: "shipments/deliver"
        case .registerInvoice, .confirmDeposit, .reviewContent, .completeTask, .acknowledgeRecommendation:
            preconditionFailure("\(code) has no batch without further input")
        }
        let batch = Batch(items: items.map { BatchItem(id: $0.actionTarget.id, expectedRevision: $0.actionTarget.revision) })
        let changed: CardList = try await post(path, batch)
        return changed.items
    }

    static func registerInvoice(item: WorkItem, carrier: String, trackingNumber: String) async throws -> WorkItem {
        struct Body: Encodable { let carrier, trackingNumber: String; let expectedRevision: Int }
        let target = item.actionTarget
        return try await post("shipments/\(target.id)/invoice", Body(
            carrier: carrier, trackingNumber: trackingNumber, expectedRevision: target.revision))
    }

    /// Registers one carrier's tracking numbers for several packed parcels at once.
    static func registerInvoices(_ numbers: [(item: WorkItem, trackingNumber: String)], carrier: String) async throws
        -> [WorkItem] {
        struct Item: Encodable { let id, trackingNumber: String; let expectedRevision: Int }
        struct Body: Encodable { let carrier: String; let items: [Item] }
        let items = numbers.map {
            Item(id: $0.item.actionTarget.id, trackingNumber: $0.trackingNumber, expectedRevision: $0.item.actionTarget.revision)
        }
        let changed: CardList = try await post("shipments/invoice", Body(carrier: carrier, items: items))
        return changed.items
    }

    /// Takes one step back and returns the changed row, which carries the step that can be taken again.
    @discardableResult
    static func undo(_ undo: UndoAction, revision: Int) async throws -> WorkItem {
        try await post(undo.path, Revisioned(expectedRevision: revision))
    }

    /// Moves rows a batch changed back one step each; every row is an order or every row is a parcel.
    static func undo(_ changed: [WorkItem]) async throws {
        let path = changed.first?.kind == .order ? "orders/undo-confirm" : "shipments/undo"
        let _: CardList = try await post(path, Batch(items: changed.map { BatchItem(id: $0.id, expectedRevision: $0.revision) }))
    }

    static func confirmDeposit(bookingID: String, revision: Int) async throws {
        let _: Acknowledged = try await post("bookings/\(bookingID)/confirm-deposit", Revisioned(expectedRevision: revision))
    }

    /// Checks off a task or owner event, or clears the mark, and returns its new revision for undo.
    static func setDone(_ item: OwnerItem, done: Bool) async throws -> Int {
        struct Saved: Decodable { let revision: Int }
        let saved: Saved = switch item {
        case .task(let id, let revision): try await post("tasks/\(id)/completion", Completion(done: done, expectedRevision: revision))
        case .event(let id, let revision):
            try await post("calendar/events/\(id)/completion", Completion(done: done, expectedRevision: revision))
        }
        return saved.revision
    }

    /// Reschedules a task or owner event and returns its new revision for undo.
    static func move(_ target: OwnerItem, to moment: Date) async throws -> Int {
        struct Moved: Decodable { let revision: Int }
        struct TaskMove: Encodable { let dueAt: String; let expectedRevision: Int }
        struct EventMove: Encodable { let startsAt: String; let expectedRevision: Int }
        let at = moment.ISO8601Format()
        let moved: Moved = switch target {
        case .task(let id, let revision): try await post("tasks/\(id)/move", TaskMove(dueAt: at, expectedRevision: revision))
        case .event(let id, let revision):
            try await post("calendar/events/\(id)/move", EventMove(startsAt: at, expectedRevision: revision))
        }
        return moved.revision
    }

    static func setSessionDone(id: String, done: Bool, revision: Int) async throws {
        let _: Acknowledged = try await post("class-sessions/\(id)/completion", Completion(done: done, expectedRevision: revision))
    }

    static func saveAssistantDraft(kind: DraftKind, id: String, text: String, revision: Int) async throws {
        let _: Acknowledged = try await send(
            method: "PATCH", path: "assistant-drafts/\(kind.rawValue)/\(id)/draft",
            body: InquiryDraft(draft: text, expectedRevision: revision))
    }

    static func decideAssistantDraft(kind: DraftKind, id: String, decision: InquiryDecision) async throws {
        let _: Acknowledged = try await post("assistant-drafts/\(kind.rawValue)/\(id)/decision", decision)
    }

    static func reopenAssistantDraft(kind: DraftKind, id: String, revision: Int) async throws {
        let _: Acknowledged = try await post(
            "assistant-drafts/\(kind.rawValue)/\(id)/reopen", Revisioned(expectedRevision: revision))
    }

    /// Returns the saved revision, so an undo can follow without guessing it.
    static func setDone(_ item: TaskItem, done: Bool, revision: Int? = nil) async throws -> Int {
        struct Saved: Decodable { let revision: Int }
        let body = Completion(done: done, expectedRevision: revision ?? item.revision)
        let saved: Saved
        switch item.target {
        case .session: saved = try await post("class-sessions/\(item.id)/completion", body)
        case .task: saved = try await post("tasks/\(item.id)/completion", body)
        case .shipment: preconditionFailure("shipments use their own actions")
        }
        return saved.revision
    }

    private struct CarryOverBatch: Encodable { let items: [CarryOverTarget] }

    /// Puts overdue work into today's list; its deadline stays as it is.
    static func carryOver(_ items: [CarryOverTarget]) async throws {
        _ = try await write(method: "POST", path: "today/carry-overs", body: CarryOverBatch(items: items))
    }

    static func undoCarryOver(_ items: [CarryOverTarget]) async throws {
        _ = try await write(method: "POST", path: "today/carry-overs/undo", body: CarryOverBatch(items: items))
    }

    static func createBooking(sessionID: String, customerName: String, phone: String, partySize: Int) async throws {
        struct Body: Encodable { let sessionId, customerName, phone: String; let partySize: Int }
        let _: WorkItem = try await post("bookings", Body(
            sessionId: sessionID, customerName: customerName, phone: phone, partySize: partySize))
    }

    static func createEvent(title: String, kind: EventKind, detail: String, startsAt: Date) async throws {
        struct Body: Encodable { let title, kind, detail, startsAt: String }
        // The default format is UTC with a "Z" offset, which the server requires.
        let _: AgendaItem.Created = try await post("calendar/events", Body(
            title: title, kind: kind.rawValue, detail: detail, startsAt: startsAt.ISO8601Format()))
    }

    static func saveWorkshop(_ draft: WorkshopDraft) async throws -> WorkshopProfile {
        try await send(method: "PUT", path: "workshop", body: draft)
    }

    static func saveSetting(key: String, body: String, revision: Int) async throws -> SettingItem {
        struct Body: Encodable { let body: String; let expectedRevision: Int }
        return try await send(method: "PATCH", path: "settings/\(key)", body: Body(body: body, expectedRevision: revision))
    }

    // MARK: Inquiries

    static func inquiries() async throws -> [Inquiry] { try await get("inquiries") }

    static func saveInquiry(id: String, draft: InquiryDraft) async throws -> Inquiry {
        try await send(method: "PATCH", path: "inquiries/\(id)/draft", body: draft)
    }

    static func decideInquiry(id: String, decision: InquiryDecision) async throws -> Inquiry {
        try await post("inquiries/\(id)/decision", decision)
    }

    static func undoInquiryCompletion(id: String, revision: Int) async throws -> Inquiry {
        try await post("inquiries/\(id)/undo-completion", Revisioned(expectedRevision: revision))
    }

    // MARK: Provider proxies

    static func staticMap(for place: GeocodeResult) async throws -> Data {
        try await sendRaw(try request("staticmap", query: [
            URLQueryItem(name: "lat", value: String(place.lat)),
            URLQueryItem(name: "lng", value: String(place.lng)),
        ]))
    }

    struct ChatTurn: Encodable {
        enum Role: String, Encodable { case owner, assistant }
        let role: Role
        let text: String
    }

    struct AskReply: Decodable {
        let answer: String
        let items: [WorkItem]?
    }

    static func assistantActivities() async throws -> [AssistantActivity] {
        try await get("assistant/activities")
    }

    /// The server builds the workshop context from its own database; earlier turns let follow-ups work.
    static func ask(question: String, history: [ChatTurn] = []) async throws -> (answer: String, items: [WorkItem]) {
        struct Body: Encodable { let question: String; let history: [ChatTurn] }
        let reply: AskReply = try await post("ask", Body(question: question, history: Array(history.suffix(6))))
        return (reply.answer, reply.items ?? [])
    }

    enum RewriteKind: String, Encodable {
        case content
        case recommendation
        case inquiry
    }

    static func rewrite(kind: RewriteKind, title: String, text: String, instruction: String = "") async throws -> String {
        struct Body: Encodable { let kind: RewriteKind; let title, text, instruction: String }
        struct Reply: Decodable { let draft: String }
        let reply: Reply = try await post("rewrite", Body(kind: kind, title: title, text: text, instruction: instruction))
        return reply.draft
    }

    static func transcribe(wav: Data) async throws -> String {
        struct Reply: Decodable { let text: String }
        var request = try request("stt")
        request.httpMethod = "POST"
        request.setValue("application/octet-stream", forHTTPHeaderField: "Content-Type")
        request.httpBody = wav
        return try JSONDecoder().decode(Reply.self, from: try await sendRaw(request)).text
    }

    /// The server reads `text` aloud with CLOVA Voice and returns MP3 audio.
    static func speech(text: String) async throws -> Data {
        struct Body: Encodable { let text: String }
        var request = try request("tts")
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONEncoder().encode(Body(text: text))
        return try await sendRaw(request)
    }

    static func geocode(_ query: String) async throws -> GeocodeResult {
        try await get("geocode", query: ["query": query])
    }

    // MARK: Transport

    private static let session = URLSession(configuration: .ephemeral, delegate: PinnedServerTrust(), delegateQueue: nil)

    private static func request(_ path: String, query: [URLQueryItem] = []) throws -> URLRequest {
        var url = try RoundupConfiguration.baseURL()
        for component in path.split(separator: "/") { url.append(path: String(component)) }
        if !query.isEmpty { url.append(queryItems: query) }
        return URLRequest(url: url)
    }

    static func get<T: Decodable>(_ path: String, query: [String: String] = [:],
                                  decoder: JSONDecoder = JSONDecoder()) async throws -> T {
        let items = query.sorted { $0.key < $1.key }.map { URLQueryItem(name: $0.key, value: $0.value) }
        let request = try request(path, query: items)
        if ResponseCache.probe != nil { return try decode(try ResponseCache.read(request), with: decoder) }
        let data = try await sendRaw(request, idempotent: true)
        let value: T = try decode(data, with: decoder)
        ResponseCache.store(data, for: request)
        return value
    }

    static func post<T: Decodable, Body: Encodable>(_ path: String, _ body: Body) async throws -> T {
        try await send(method: "POST", path: path, body: body)
    }

    static func send<T: Decodable, Body: Encodable>(method: String, path: String, body: Body) async throws -> T {
        try decode(try await write(method: method, path: path, body: body))
    }

    private static func write<Body: Encodable>(method: String, path: String, body: Body) async throws -> Data {
        var request = try request(path)
        request.httpMethod = method
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONEncoder().encode(body)
        return try await sendRaw(request)
    }

    private static func decode<T: Decodable>(_ data: Data, with decoder: JSONDecoder = JSONDecoder()) throws -> T {
        do {
            return try decoder.decode(T.self, from: data)
        } catch {
            throw RoundupAPIError(message: "서버 응답을 읽지 못했어요. 앱을 최신 버전으로 업데이트해 주세요.")
        }
    }

    /// A dropped keep-alive connection or a stalled request usually succeeds on a second try right away.
    private static let quickRetryCodes: Set<URLError.Code> = [.networkConnectionLost, .timedOut]

    /// `idempotent` requests (GETs) get one quick retry; writes never repeat, since a lost response can follow a
    /// committed change.
    private static func sendRaw(_ request: URLRequest, idempotent: Bool = false) async throws -> Data {
        guard ResponseCache.probe == nil else { throw ResponseCache.Miss() }
        var request = request
        request.timeoutInterval = idempotent ? 12 : 25
        request.setValue(try RoundupConfiguration.apiKey(), forHTTPHeaderField: "X-Roundup-Key")
        let started = Date.now
        let route = request.url?.path() ?? ""
        var attempt = 1
        let data: Data
        let response: URLResponse
        while true {
            do {
                (data, response) = try await session.data(for: request)
                break
            } catch let error as URLError where error.code == .cancelled {
                throw CancellationError()
            } catch let error as URLError where idempotent && attempt == 1 && quickRetryCodes.contains(error.code) {
                attempt += 1
                ServerConnection.log("request.retry \(route) code=\(error.code.rawValue)")
                try await Task.sleep(for: .milliseconds(Int.random(in: 300...600)))
            } catch {
                ServerConnection.log("request.unreachable \(route) code=\((error as? URLError)?.code.rawValue ?? 0)")
                ServerConnection.shared.requestFailedToReachServer()
                throw ConnectionError()
            }
        }
        let status = (response as? HTTPURLResponse)?.statusCode ?? 0
        ServerConnection.log("request \(request.httpMethod ?? "GET") \(route) status=\(status) ms=\(Int(Date.now.timeIntervalSince(started) * 1000))")
        if [502, 503, 504].contains(status) {
            ServerConnection.shared.requestFailedToReachServer()
            throw ConnectionError()
        }
        ServerConnection.shared.requestReachedServer()
        guard let http = response as? HTTPURLResponse else {
            throw RoundupAPIError(message: "서버가 요청을 처리하지 못했어요. 잠시 후 다시 시도해 주세요.")
        }
        if request.url?.pathComponents.contains("inquiries") == true {
            switch http.statusCode {
            case 404: throw ReplyError.missingInquiry
            case 409: throw InquiryPersistenceError.conflict
            case 422: throw ReplyError.emptyDraft
            default: break
            }
        }
        switch http.statusCode {
        case 200, 201, 204: return data
        case 401, 403: throw RoundupAPIError(message: "서버 인증을 확인하지 못했어요. 연결 설정을 확인해 주세요.")
        case 404: throw RoundupAPIError(message: "찾을 수 없는 항목이에요. 목록을 새로 불러와 주세요.", isConflict: true)
        case 409: throw RoundupAPIError(message: "다른 곳에서 먼저 바뀌었거나 지금은 할 수 없는 작업이에요. 최신 내용을 불러왔어요.", isConflict: true)
        case 413, 422: throw RoundupAPIError(message: "입력한 내용을 다시 확인해 주세요.")
        default: throw RoundupAPIError(message: "서버가 요청을 처리하지 못했어요. 잠시 후 다시 시도해 주세요.")
        }
    }
}

/// A task or parcel that can be put into today's list; a class cannot.
struct CarryOverTarget: Encodable, Hashable {
    enum Kind: String, Encodable { case task, shipment }
    let target: Kind
    let id: String

    init?(_ item: TaskItem) {
        switch item.target {
        case .task: target = .task
        case .shipment: target = .shipment
        case .session: return nil
        }
        id = item.id
    }
}

extension AgendaItem {
    /// Created events are confirmed by reloading the calendar.
    struct Created: Decodable {}
}

struct AreaQuery: Hashable {
    var filter: String
    var text: String
    var sort: String?
    var limit = 30
    var offset = 0
}

struct WorkshopDraft: Encodable {
    var name: String
    var ownerTitle: String
    var phone: String
    var address: String
    var description: String
    var latitude: Double?
    var longitude: Double?
    var expectedRevision: Int

    enum CodingKeys: String, CodingKey {
        case name, ownerTitle, phone, address, description, latitude, longitude, expectedRevision
    }

    func encode(to encoder: any Encoder) throws {
        var container = encoder.container(keyedBy: CodingKeys.self)
        try container.encode(name, forKey: .name)
        try container.encode(ownerTitle, forKey: .ownerTitle)
        try container.encode(phone, forKey: .phone)
        try container.encode(address, forKey: .address)
        try container.encode(description, forKey: .description)
        try container.encode(latitude, forKey: .latitude)
        try container.encode(longitude, forKey: .longitude)
        try container.encode(expectedRevision, forKey: .expectedRevision)
    }
}

struct APIInquiryRepository: InquiryRepository {
    func load() async throws -> [Inquiry] { try await RoundupAPI.inquiries() }
    func cached() async -> (inquiries: [Inquiry], savedAt: Date)? {
        await ResponseCache.cachedValue { try await RoundupAPI.inquiries() }.map { ($0.value, $0.savedAt) }
    }
    func save(id: String, draft: InquiryDraft) async throws -> Inquiry {
        try await RoundupAPI.saveInquiry(id: id, draft: draft)
    }
    func decide(id: String, decision: InquiryDecision) async throws -> Inquiry {
        try await RoundupAPI.decideInquiry(id: id, decision: decision)
    }
    func undoCompletion(id: String, expectedRevision: Int) async throws -> Inquiry {
        try await RoundupAPI.undoInquiryCompletion(id: id, revision: expectedRevision)
    }
}

/// HTTPS connections trust only the certificate bundled with the app.
private final class PinnedServerTrust: NSObject, URLSessionDelegate {
    private let pinned: Data? = Bundle.main.url(forResource: "roundup-server", withExtension: "cer")
        .flatMap { try? Data(contentsOf: $0) }

    func urlSession(_ session: URLSession, didReceive challenge: URLAuthenticationChallenge) async
        -> (URLSession.AuthChallengeDisposition, URLCredential?) {
        guard challenge.protectionSpace.authenticationMethod == NSURLAuthenticationMethodServerTrust,
              let trust = challenge.protectionSpace.serverTrust,
              let pinned,
              let chain = SecTrustCopyCertificateChain(trust) as? [SecCertificate],
              let leaf = chain.first,
              SecCertificateCopyData(leaf) as Data == pinned else {
            return (.cancelAuthenticationChallenge, nil)
        }
        return (.useCredential, URLCredential(trust: trust))
    }
}
