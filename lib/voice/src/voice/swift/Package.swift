// swift-tools-version: 6.0
// kokoro-fluid: Kokoro through FluidAudio, for voice.fluid. voice.fluid builds it: it fetches FluidAudio 0.17.7,
// applies fluidaudio-0.17.7.patch and passes the checkout in FLUIDAUDIO_SRC (a directory named FluidAudio).
import Foundation
import PackageDescription

let fluidAudio = ProcessInfo.processInfo.environment["FLUIDAUDIO_SRC"] ?? "FluidAudio"

let package = Package(
    name: "kokoro-fluid",
    platforms: [.macOS(.v15)],
    dependencies: [.package(path: fluidAudio)],
    targets: [
        .executableTarget(
            name: "kokoro-fluid",
            dependencies: [.product(name: "FluidAudio", package: "FluidAudio")],
            path: "Sources/kokoro-fluid"
        )
    ]
)
