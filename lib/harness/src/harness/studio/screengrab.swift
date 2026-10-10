// screengrab: studio's screen capture helper (ScreenCaptureKit). The harness compiles this file on first use
// (studio/grab.py) and keeps one process running: a capture then costs ~35 ms rather than the ~130 ms of a spawned
// `screencapture`, and an open stream hands over its latest frame in ~2 ms.
//
// One command per line on stdin, one JSON object per line on stdout:
//   shot PATH    capture the main display now and write it to PATH
//   start FPS    open a stream on the main display; it answers once the first frame is in. ScreenCaptureKit
//                delivers a frame only when something changed, so a stream costs little while the screen is still.
//   frame PATH   write the stream's latest frame to PATH. "seq" counts the stream's frames: the same seq means
//                the screen hasn't changed since.
//   stop         close the stream
//   front        the front window's bounds as they look: the topmost window that isn't the menu bar, the Dock or
//                a status item, so a modal alert or an open menu wins over the app's own window
// Frames are raw 8-bit BGRA in sRGB with "bpr" bytes per row; replies give w, h and bpr. Bounds are [x, y, w, h]
// in the display's pixels. Every reply has "ok", failures an "error". A line that isn't a reply carries "event"
// (the stream stopped). The process exits when stdin closes.
//
// On launch it prints {"ready": true, "preflight": <Screen Recording granted>, "display": {"w", "h"}}. Without the
// permission it never touches ScreenCaptureKit, which could put a permission dialog on the screen.

import CoreGraphics
import CoreMedia
import CoreVideo
import Foundation
import ScreenCaptureKit

struct HelperError: Error, CustomStringConvertible {
    let description: String
    init(_ description: String) { self.description = description }
}

let stdoutLock = NSLock()

/// One JSON line on stdout. Replies come from the main actor and events from the stream's queue, so a lock keeps
/// lines whole.
func emit(_ object: [String: Any]) {
    var object = object
    if object["ok"] == nil { object["ok"] = true }
    guard var data = try? JSONSerialization.data(withJSONObject: object, options: [.sortedKeys]) else { return }
    data.append(0x0A)
    stdoutLock.lock()
    defer { stdoutLock.unlock() }
    FileHandle.standardOutput.write(data)
}

/// Writes `count` bytes to `path`, readable by this user only: a frame is whatever was on the screen.
func writeFile(_ bytes: UnsafeRawPointer, count: Int, to path: String) throws {
    let fd = open(path, O_WRONLY | O_CREAT | O_TRUNC, 0o600)
    guard fd >= 0 else { throw HelperError("open \(path): \(String(cString: strerror(errno)))") }
    defer { close(fd) }
    var done = 0
    while done < count {
        let n = write(fd, bytes + done, count - done)
        guard n > 0 else { throw HelperError("write \(path): \(String(cString: strerror(errno)))") }
        done += n
    }
}

/// The BGRA bytes of an image: its own backing store when that is already 8-bit BGRA, else a redraw in sRGB.
func bgra(_ image: CGImage) throws -> (Data, Int) {
    let info = image.bitmapInfo.rawValue
    let alpha = CGImageAlphaInfo(rawValue: info & CGBitmapInfo.alphaInfoMask.rawValue)
    let isBGRA = image.bitsPerPixel == 32 && image.bitsPerComponent == 8
        && info & CGBitmapInfo.byteOrderMask.rawValue == CGBitmapInfo.byteOrder32Little.rawValue
        && (alpha == .premultipliedFirst || alpha == .noneSkipFirst || alpha == .first)
    if isBGRA, let data = image.dataProvider?.data {
        return (data as Data, image.bytesPerRow)
    }
    let w = image.width, h = image.height, bpr = w * 4
    var data = Data(count: bpr * h)
    try data.withUnsafeMutableBytes { buffer in
        guard let context = CGContext(
            data: buffer.baseAddress, width: w, height: h, bitsPerComponent: 8, bytesPerRow: bpr,
            space: CGColorSpace(name: CGColorSpace.sRGB)!,
            bitmapInfo: CGImageAlphaInfo.premultipliedFirst.rawValue | CGBitmapInfo.byteOrder32Little.rawValue)
        else { throw HelperError("no bitmap context") }
        context.draw(image, in: CGRect(x: 0, y: 0, width: w, height: h))
    }
    return (data, bpr)
}

/// The main display: where it is among the displays (points) and how many pixels it has.
struct Display {
    let id: CGDirectDisplayID
    let points: CGRect
    let width: Int
    let height: Int

    static func main() -> Display {
        let id = CGMainDisplayID()
        let points = CGDisplayBounds(id)
        let mode = CGDisplayCopyDisplayMode(id)
        return Display(id: id, points: points, width: mode?.pixelWidth ?? Int(points.width),
                       height: mode?.pixelHeight ?? Int(points.height))
    }

    /// A rectangle in global points as [x, y, w, h] in this display's pixels.
    func pixels(_ rect: CGRect) -> [Int] {
        let scale = Double(width) / points.width
        return [Int(((rect.minX - points.minX) * scale).rounded()), Int(((rect.minY - points.minY) * scale).rounded()),
                Int((rect.width * scale).rounded()), Int((rect.height * scale).rounded())]
    }
}

/// The stream's latest frame. ScreenCaptureKit hands frames over on its own queue; commands read them on the main
/// actor. `seq` never restarts, so a frame from an earlier stream can't pass for a new one.
final class Frames: @unchecked Sendable {
    private let lock = NSLock()
    private var buffer: CVPixelBuffer?
    private var seq = 0

    func put(_ buffer: CVPixelBuffer) {
        lock.lock()
        defer { lock.unlock() }
        self.buffer = buffer
        seq += 1
    }

    func latest() -> (CVPixelBuffer?, Int) {
        lock.lock()
        defer { lock.unlock() }
        return (buffer, seq)
    }

    func clear() {
        lock.lock()
        defer { lock.unlock() }
        buffer = nil
    }
}

final class StreamOutput: NSObject, SCStreamOutput, SCStreamDelegate, @unchecked Sendable {
    let frames: Frames
    init(frames: Frames) { self.frames = frames }

    func stream(_ stream: SCStream, didOutputSampleBuffer sample: CMSampleBuffer, of type: SCStreamOutputType) {
        // Only complete frames carry pixels; the others say nothing changed.
        guard type == .screen, sample.isValid,
              let attachments = CMSampleBufferGetSampleAttachmentsArray(sample, createIfNecessary: false)
                  as? [[SCStreamFrameInfo: Any]],
              let raw = attachments.first?[.status] as? Int, SCFrameStatus(rawValue: raw) == .complete,
              let buffer = CMSampleBufferGetImageBuffer(sample)
        else { return }
        frames.put(buffer)
    }

    func stream(_ stream: SCStream, didStopWithError error: Error) {
        emit(["ok": false, "event": "stream_stopped", "error": "\(error)"])
    }
}

@MainActor
final class Grabber {
    let display = Display.main()
    private var filter: SCContentFilter?
    private var stream: SCStream?
    private let frames = Frames()
    private lazy var output = StreamOutput(frames: frames)
    private let queue = DispatchQueue(label: "screengrab.frames", qos: .userInitiated)

    /// The main display as ScreenCaptureKit knows it, looked up once.
    func prepare() async throws -> SCContentFilter {
        if let filter { return filter }
        guard CGPreflightScreenCaptureAccess() else { throw HelperError("no Screen Recording permission") }
        let content = try await SCShareableContent.excludingDesktopWindows(false, onScreenWindowsOnly: true)
        guard let main = content.displays.first(where: { $0.displayID == display.id })
        else { throw HelperError("the main display is not shareable") }
        let made = SCContentFilter(display: main, excludingWindows: [])
        filter = made
        return made
    }

    func configuration(fps: Int? = nil) -> SCStreamConfiguration {
        let config = SCStreamConfiguration()
        config.width = display.width
        config.height = display.height
        config.pixelFormat = kCVPixelFormatType_32BGRA
        config.colorSpaceName = CGColorSpace.sRGB
        config.showsCursor = false
        if let fps {
            config.minimumFrameInterval = CMTime(value: 1, timescale: CMTimeScale(max(1, fps)))
            config.queueDepth = 4
        }
        return config
    }

    func shot(_ path: String) async throws -> [String: Any] {
        let image = try await SCScreenshotManager.captureImage(contentFilter: try await prepare(),
                                                               configuration: configuration())
        let (data, bpr) = try bgra(image)
        try data.withUnsafeBytes { try writeFile($0.baseAddress!, count: bpr * image.height, to: path) }
        return ["w": image.width, "h": image.height, "bpr": bpr]
    }

    func start(fps: Int) async throws -> [String: Any] {
        let filter = try await prepare()
        _ = await stop()
        let (_, before) = frames.latest()
        let made = SCStream(filter: filter, configuration: configuration(fps: fps), delegate: output)
        try made.addStreamOutput(output, type: .screen, sampleHandlerQueue: queue)
        try await made.startCapture()
        stream = made
        let deadline = Date().addingTimeInterval(3)
        while frames.latest().1 == before && Date() < deadline {
            try await Task.sleep(nanoseconds: 5_000_000)
        }
        return ["fps": fps]
    }

    func stop() async -> [String: Any] {
        if let stream { try? await stream.stopCapture() }
        stream = nil
        frames.clear()
        return [:]
    }

    func frame(_ path: String) throws -> [String: Any] {
        guard stream != nil else { throw HelperError("no stream (send: start FPS)") }
        let (latest, seq) = frames.latest()
        guard let buffer = latest else { throw HelperError("no frame yet") }
        CVPixelBufferLockBaseAddress(buffer, .readOnly)
        defer { CVPixelBufferUnlockBaseAddress(buffer, .readOnly) }
        guard let base = CVPixelBufferGetBaseAddress(buffer) else { throw HelperError("the frame has no pixels") }
        let bpr = CVPixelBufferGetBytesPerRow(buffer), height = CVPixelBufferGetHeight(buffer)
        try writeFile(base, count: bpr * height, to: path)
        return ["w": CVPixelBufferGetWidth(buffer), "h": height, "bpr": bpr, "seq": seq]
    }

    /// The window list runs front to back. The first window below the assistive-technology level that isn't the
    /// Dock, the menu bar or a status item, and shows on the main display, is what is in front.
    func front() -> [String: Any] {
        let windows = CGWindowListCopyWindowInfo([.optionOnScreenOnly, .excludeDesktopElements], kCGNullWindowID)
            as? [[String: Any]] ?? []
        let chrome = Set([CGWindowLevelKey.dockWindow, .mainMenuWindow, .statusWindow].map {
            Int(CGWindowLevelForKey($0))
        })
        let ceiling = Int(CGWindowLevelForKey(.assistiveTechHighWindow))
        for window in windows {
            let layer = window[kCGWindowLayer as String] as? Int ?? -1
            let alpha = window[kCGWindowAlpha as String] as? Double ?? 1
            let owner = window[kCGWindowOwnerName as String] as? String ?? ""
            guard layer >= 0, layer < ceiling, !chrome.contains(layer), alpha > 0.01,
                  owner != "Window Server", owner != "Dock",
                  let dict = window[kCGWindowBounds as String] as? NSDictionary,
                  let bounds = CGRect(dictionaryRepresentation: dict as CFDictionary)
            else { continue }
            let shown = bounds.intersection(display.points)
            guard !shown.isNull, shown.width >= 64, shown.height >= 64 else { continue }
            return ["bounds": display.pixels(shown)]
        }
        return ["bounds": NSNull()]
    }
}

@main
struct ScreenGrab {
    @MainActor
    static func main() async {
        let grabber = Grabber()
        let preflight = CGPreflightScreenCaptureAccess()
        var ready: [String: Any] = ["ready": true, "preflight": preflight,
                                    "display": ["w": grabber.display.width, "h": grabber.display.height]]
        if preflight {
            do {
                _ = try await grabber.prepare()
            } catch {
                ready["ok"] = false
                ready["error"] = "\(error)"
            }
        }
        emit(ready)

        do {
            for try await raw in FileHandle.standardInput.bytes.lines {
                let line = raw.trimmingCharacters(in: .whitespaces)
                if line.isEmpty { continue }
                let command = String(line.prefix { $0 != " " })
                let argument = String(line.dropFirst(command.count)).trimmingCharacters(in: .whitespaces)
                do {
                    var reply: [String: Any]
                    switch command {
                    case "shot": reply = try await grabber.shot(argument)
                    case "start": reply = try await grabber.start(fps: Int(argument) ?? 2)
                    case "frame": reply = try grabber.frame(argument)
                    case "stop": reply = await grabber.stop()
                    case "front": reply = grabber.front()
                    default: throw HelperError("unknown command: \(command)")
                    }
                    reply["cmd"] = command
                    emit(reply)
                } catch {
                    emit(["ok": false, "cmd": command, "error": "\(error)"])
                }
            }
        } catch {
            emit(["ok": false, "event": "stdin", "error": "\(error)"])
        }
        _ = await grabber.stop()
    }
}
