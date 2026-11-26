// zpkt-listen-capture: Live's own sound, as raw PCM on standard output.
//
// It records what one application plays (by default Ableton Live) with ScreenCaptureKit and writes it as
// 16-bit little-endian stereo at 48 kHz. Nothing is changed on the way: no gain, no filter. It never touches Live.
// It needs the Screen Recording permission for the app that started it (System Settings, Privacy & Security,
// Screen & System Audio Recording). Without it, it prints "permission needed" and exits 77.
//
//   zpkt-listen-capture [--bundle com.ableton.live] [--all] [--stats] [--check] [--request]
//
// --all      everything the Mac plays, not one application (for testing the tool without Live)
// --stats    every five seconds, print how late the sound is when it is handed over (for measuring)
// --check    say whether capture can start ("ok", "permission needed", "app not running") and exit. It does not
//            open a capture: macOS allows one at a time here, and a second one cuts the first off.
// --request  ask macOS to show its permission dialog once (it also lists the app in System Settings)
//
// Exit codes: 0 ended, 77 permission needed, 78 the application is not running, 70 any other failure.

import AVFoundation
import AppKit
import CoreGraphics
import CoreMedia
import Foundation
import ScreenCaptureKit

let RATE = 48_000
let CHANNELS = 2
let EXIT_PERMISSION: Int32 = 77
let EXIT_NO_APP: Int32 = 78
let EXIT_FAILED: Int32 = 70

func say(_ text: String) {
    FileHandle.standardError.write((text + "\n").data(using: .utf8)!)
}

final class Output: NSObject, SCStreamOutput, SCStreamDelegate {
    private var scratch = [Int16]()
    var stats = false
    private var lateSum = 0.0
    private var lateMax = 0.0
    private var count = 0

    /// How long after its first sample was played a buffer reaches us (the capture's own delay).
    private func measure(_ buffer: CMSampleBuffer) {
        let now = CMClockGetTime(CMClockGetHostTimeClock())
        let late = CMTimeGetSeconds(CMTimeSubtract(now, buffer.presentationTimeStamp)) * 1000
        lateSum += late
        lateMax = max(lateMax, late)
        count += 1
        if count == 250 {
            say(String(format: "stats: handed over %.1f ms late on average, %.1f ms at worst", lateSum / 250, lateMax))
            lateSum = 0
            lateMax = 0
            count = 0
        }
    }

    func stream(_ stream: SCStream, didOutputSampleBuffer buffer: CMSampleBuffer, of type: SCStreamOutputType) {
        guard type == .audio, buffer.isValid, CMSampleBufferGetNumSamples(buffer) > 0 else { return }
        if stats { measure(buffer) }
        try? buffer.withAudioBufferList { list, _ in
            guard let format = buffer.formatDescription?.audioStreamBasicDescription else { return }
            let frames = CMSampleBufferGetNumSamples(buffer)
            let float = format.mFormatFlags & kAudioFormatFlagIsFloat != 0
            let planar = format.mFormatFlags & kAudioFormatFlagIsNonInterleaved != 0
            guard float, format.mBitsPerChannel == 32 else { return }
            if scratch.count < frames * CHANNELS { scratch = [Int16](repeating: 0, count: frames * CHANNELS) }
            let sources = Int(format.mChannelsPerFrame)
            for ch in 0..<CHANNELS {
                let from = min(ch, sources - 1)  // a mono source goes to both sides
                let data: UnsafePointer<Float32>
                let step: Int
                if planar {
                    guard from < list.count, let p = list[from].mData else { continue }
                    data = UnsafePointer(p.assumingMemoryBound(to: Float32.self))
                    step = 1
                } else {
                    guard let p = list[0].mData else { continue }
                    data = UnsafePointer(p.assumingMemoryBound(to: Float32.self)) + from
                    step = sources
                }
                for i in 0..<frames {
                    let v = max(-1.0, min(1.0, data[i * step]))
                    scratch[i * CHANNELS + ch] = Int16(v * 32767.0)
                }
            }
            scratch.withUnsafeBufferPointer { p in
                var left = frames * CHANNELS * 2
                var at = UnsafeRawPointer(p.baseAddress!)
                while left > 0 {
                    let n = write(STDOUT_FILENO, at, left)
                    if n <= 0 { exit(0) }  // the reader went away
                    left -= n
                    at += n
                }
            }
        }
    }

    func stream(_ stream: SCStream, didStopWithError error: Error) {
        say("stopped: \(error.localizedDescription)")
        exit(EXIT_FAILED)
    }
}

var bundle = "com.ableton.live"
var everything = false
var stats = false
var check = false
var request = false
var args = Array(CommandLine.arguments.dropFirst())
while !args.isEmpty {
    let a = args.removeFirst()
    switch a {
    case "--bundle": if !args.isEmpty { bundle = args.removeFirst() }
    case "--all": everything = true
    case "--stats": stats = true
    case "--check": check = true
    case "--request": request = true
    default:
        say("unknown argument \(a)")
        exit(64)
    }
}

signal(SIGPIPE, SIG_IGN)
if request { _ = CGRequestScreenCaptureAccess() }
if !CGPreflightScreenCaptureAccess() {
    say("permission needed: Screen & System Audio Recording, for the app that started zpkt")
    exit(EXIT_PERMISSION)
}

if check {
    if !everything && NSRunningApplication.runningApplications(withBundleIdentifier: bundle).isEmpty {
        say("app not running: \(bundle)")
        exit(EXIT_NO_APP)
    }
    say("ok")
    exit(0)
}

let output = Output()
output.stats = stats
var stream: SCStream?
var started = false
let queue = DispatchQueue(label: "zpkt.listen.audio")

Task {
    do {
        let content = try await SCShareableContent.excludingDesktopWindows(false, onScreenWindowsOnly: false)
        let app = content.applications.first(where: { $0.bundleIdentifier == bundle })
        if app == nil && !everything {
            say("app not running: \(bundle)")
            exit(EXIT_NO_APP)
        }
        guard let display = content.displays.first else {
            say("no display to attach the capture to")
            exit(EXIT_FAILED)
        }
        let filter =
            everything
            ? SCContentFilter(display: display, excludingApplications: [], exceptingWindows: [])
            : SCContentFilter(display: display, including: [app!], exceptingWindows: [])
        let config = SCStreamConfiguration()
        config.capturesAudio = true
        config.sampleRate = RATE
        config.channelCount = CHANNELS
        config.excludesCurrentProcessAudio = true
        config.width = 2  // the picture is not wanted: as small and as slow as allowed
        config.height = 2
        config.minimumFrameInterval = CMTime(value: 1, timescale: 1)
        config.queueDepth = 3
        let s = SCStream(filter: filter, configuration: config, delegate: output)
        try s.addStreamOutput(output, type: .audio, sampleHandlerQueue: queue)
        try await s.startCapture()
        stream = s
        started = true
        say("capturing \(everything ? "everything" : bundle) at \(RATE) Hz")
    } catch {
        let text = error.localizedDescription
        let code = (error as NSError).code
        if code == -3801 || text.lowercased().contains("declined") {  // SCStreamError.userDeclined
            say("permission needed: Screen & System Audio Recording, for the app that started zpkt")
            exit(EXIT_PERMISSION)
        }
        say("failed: \(text)")
        exit(EXIT_FAILED)
    }
}

// macOS sometimes never answers the request to start. Say so and leave, so the app can try again.
DispatchQueue.main.asyncAfter(deadline: .now() + 6) {
    if !started {
        say("failed: macOS did not start the capture in 6 seconds")
        exit(EXIT_FAILED)
    }
}

var sources = [DispatchSourceSignal]()
for sig in [SIGTERM, SIGINT] {
    signal(sig, SIG_IGN)
    let source = DispatchSource.makeSignalSource(signal: sig, queue: .main)
    source.setEventHandler { exit(0) }
    source.resume()
    sources.append(source)
}
dispatchMain()
