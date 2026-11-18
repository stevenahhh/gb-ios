// swift-tools-version: 5.9
import PackageDescription

let package = Package(
    name: "RoundupCore",
    platforms: [.iOS(.v17), .macOS(.v14)],
    products: [.library(name: "RoundupCore", targets: ["RoundupCore"])],
    targets: [
        .target(name: "RoundupCore"),
        .testTarget(name: "RoundupCoreTests", dependencies: ["RoundupCore"])
    ]
)
