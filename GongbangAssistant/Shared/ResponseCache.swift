import CryptoKit
import Foundation
import Synchronization

/// The last successful response of each main screen, kept on disk so a cold launch shows it at once
/// while the fresh request runs. Entries from an earlier day are ignored, because the server phrases dates
/// relative to the day it answered (오늘, 내일).
nonisolated enum ResponseCache {
    /// Set while a screen asks for its cached value: GETs answer from disk and nothing goes to the network.
    @TaskLocal static var probe: Probe?

    final class Probe: Sendable {
        private let oldest = Mutex<Date?>(nil)
        var savedAt: Date? { oldest.withLock { $0 } }

        func record(_ date: Date) {
            oldest.withLock { $0 = min($0 ?? date, date) }
        }
    }

    struct Miss: Error {}

    private static let cachedPaths: Set<String> = ["today", "operations", "calendar", "inquiries", "settings"]

    private static let directory = URL.cachesDirectory.appending(path: "responses", directoryHint: .isDirectory)

    /// Runs `fetch` against the disk cache only; nil when any request it makes has no entry from today.
    @MainActor
    static func cachedValue<Value>(_ fetch: () async throws -> Value) async -> (value: Value, savedAt: Date)? {
        let probe = Probe()
        guard let value = try? await $probe.withValue(probe, operation: fetch), let savedAt = probe.savedAt else {
            return nil
        }
        return (value, savedAt)
    }

    @MainActor
    static func read(_ request: URLRequest) throws -> Data {
        guard let file = file(for: request),
              let saved = try? file.resourceValues(forKeys: [.contentModificationDateKey]).contentModificationDate,
              Calendar.workshop.isDateInToday(saved),
              let data = try? Data(contentsOf: file) else {
            throw Miss()
        }
        probe?.record(saved)
        return data
    }

    static func store(_ data: Data, for request: URLRequest) {
        guard let file = file(for: request) else { return }
        Task.detached(priority: .utility) {
            try? FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
            try? data.write(to: file, options: [.atomic, .completeFileProtectionUntilFirstUserAuthentication])
        }
    }

    private static func file(for request: URLRequest) -> URL? {
        guard let url = request.url, let first = url.pathComponents.dropFirst().first,
              cachedPaths.contains(first) else { return nil }
        let name = SHA256.hash(data: Data(url.absoluteString.utf8)).map { String(format: "%02x", $0) }.joined()
        return directory.appending(path: name + ".json")
    }
}
