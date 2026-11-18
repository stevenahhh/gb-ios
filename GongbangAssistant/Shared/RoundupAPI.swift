import Foundation
import RoundupCore

struct RoundupAPIError: LocalizedError {
    let message: String
    var errorDescription: String? { message }
}

struct GeocodeResult: Decodable, Equatable {
    let address: String
    let lat: Double
    let lng: Double
}

enum RoundupAPI {
    static func inquiries() async throws -> [Inquiry] {
        try await send(URLRequest(url: baseURL.appending(path: "inquiries")), as: [Inquiry].self)
    }

    static func saveInquiry(id: String, draft: InquiryDraft) async throws -> Inquiry {
        var request = URLRequest(url: baseURL.appending(path: "inquiries").appending(path: id).appending(path: "draft"))
        request.httpMethod = "PATCH"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONEncoder().encode(draft)
        return try await send(request, as: Inquiry.self)
    }

    static func decideInquiry(id: String, decision: InquiryDecision) async throws -> Inquiry {
        var request = URLRequest(url: baseURL.appending(path: "inquiries").appending(path: id).appending(path: "decision"))
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONEncoder().encode(decision)
        return try await send(request, as: Inquiry.self)
    }

    static var baseURL: URL {
        let configured = ProcessInfo.processInfo.environment["ROUNDUP_API_URL"]
            ?? Bundle.main.object(forInfoDictionaryKey: "RoundupAPIURL") as? String
        return URL(string: configured ?? "https://223.130.130.1:8787")!
    }

    private static let apiKey: String = {
        guard let url = Bundle.main.url(forResource: "RoundupSecrets", withExtension: "plist"),
              let values = NSDictionary(contentsOf: url),
              let key = values["APIKey"] as? String else { return "" }
        return key
    }()

    private static let session = URLSession(configuration: .ephemeral, delegate: PinnedServerTrust(), delegateQueue: nil)

    static func staticMap(for place: GeocodeResult) async throws -> Data {
        try await sendRaw(URLRequest(url: staticMapURL(for: place)))
    }

    static func draft(customer: String, subject: String, question: String, facts: [String]) async throws -> String {
        struct Body: Encodable { let customer, subject, question: String; let facts: [String] }
        struct Reply: Decodable { let draft: String }
        var request = URLRequest(url: baseURL.appending(path: "draft"))
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONEncoder().encode(Body(customer: customer, subject: subject, question: question, facts: facts))
        return try await send(request, as: Reply.self).draft
    }

    static func ask(question: String, context: [String]) async throws -> String {
        struct Body: Encodable { let question: String; let context: [String] }
        struct Reply: Decodable { let answer: String }
        var request = URLRequest(url: baseURL.appending(path: "ask"))
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONEncoder().encode(Body(question: question, context: context))
        return try await send(request, as: Reply.self).answer
    }

    static func transcribe(wav: Data) async throws -> String {
        struct Reply: Decodable { let text: String }
        var request = URLRequest(url: baseURL.appending(path: "stt"))
        request.httpMethod = "POST"
        request.setValue("application/octet-stream", forHTTPHeaderField: "Content-Type")
        request.httpBody = wav
        return try await send(request, as: Reply.self).text
    }

    static func geocode(_ query: String) async throws -> GeocodeResult {
        let url = baseURL.appending(path: "geocode").appending(queryItems: [URLQueryItem(name: "query", value: query)])
        return try await send(URLRequest(url: url), as: GeocodeResult.self)
    }

    private static func staticMapURL(for place: GeocodeResult) -> URL {
        baseURL.appending(path: "staticmap").appending(queryItems: [
            URLQueryItem(name: "lat", value: String(place.lat)),
            URLQueryItem(name: "lng", value: String(place.lng)),
        ])
    }

    private static func send<T: Decodable>(_ request: URLRequest, as type: T.Type) async throws -> T {
        try JSONDecoder().decode(T.self, from: try await sendRaw(request))
    }

    private static func sendRaw(_ request: URLRequest) async throws -> Data {
        var request = request
        request.timeoutInterval = 25
        request.setValue(apiKey, forHTTPHeaderField: "X-Roundup-Key")
        let data: Data
        let response: URLResponse
        do {
            (data, response) = try await session.data(for: request)
        } catch {
            throw RoundupAPIError(message: "서버에 연결하지 못했어요. 잠시 후 다시 시도해 주세요.")
        }
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
        case 200: break
        case 401, 403: throw RoundupAPIError(message: "서버 인증을 확인하지 못했어요. 연결 설정을 확인해 주세요.")
        default: throw RoundupAPIError(message: "서버가 요청을 처리하지 못했어요. 잠시 후 다시 시도해 주세요.")
        }
        return data
    }
}

struct APIInquiryRepository: InquiryRepository {
    func load() async throws -> [Inquiry] { try await RoundupAPI.inquiries() }
    func save(id: String, draft: InquiryDraft) async throws -> Inquiry {
        try await RoundupAPI.saveInquiry(id: id, draft: draft)
    }
    func decide(id: String, decision: InquiryDecision) async throws -> Inquiry {
        try await RoundupAPI.decideInquiry(id: id, decision: decision)
    }
}

/// The server uses a self-signed certificate for its bare IP address, so only that bundled certificate is trusted.
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
