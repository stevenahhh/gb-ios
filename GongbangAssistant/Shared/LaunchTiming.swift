import Darwin
import Foundation
import os

/// Logs how long a cold launch takes to put the first server-backed content on screen.
/// Read it with `log stream --predicate 'category == "launch"'`.
enum LaunchTiming {
    private static let logger = Logger(subsystem: "GongbangAssistant", category: "launch")
    private static var reportedFirstContent = false

    /// The kernel's process start time, so the number includes dyld and runtime setup before `main`.
    private static let processStart: Date = {
        var info = kinfo_proc()
        var size = MemoryLayout<kinfo_proc>.stride
        var name: [Int32] = [CTL_KERN, KERN_PROC, KERN_PROC_PID, getpid()]
        guard sysctl(&name, 4, &info, &size, nil, 0) == 0 else { return .now }
        let start = info.kp_proc.p_un.__p_starttime
        return Date(timeIntervalSince1970: TimeInterval(start.tv_sec) + TimeInterval(start.tv_usec) / 1_000_000)
    }()

    private static var elapsed: Int { Int(Date.now.timeIntervalSince(processStart) * 1000) }

    static func appDidInit() {
        logger.info("launch.appInit ms=\(elapsed, privacy: .public)")
    }

    static func firstContent(_ type: Any.Type, source: String) {
        guard !reportedFirstContent else { return }
        reportedFirstContent = true
        logger.info("launch.firstContent ms=\(elapsed, privacy: .public) type=\(String(describing: type), privacy: .public) source=\(source, privacy: .public)")
    }
}
