// kokoro-fluid: Kokoro 82M through FluidAudio's v3 pipeline (Core ML on the Neural Engine and GPU), behind a pipe.
//
// Frames as in voice.protocol: [4-byte big-endian header length][JSON header][4-byte length][payload].
//   in:  {"op": "say", "id", "text", "voice", "speed"}      one piece of text (voice.tts cuts the sentences)
//   out: {"op": "ready", "rate", "load_ms", "warmup_ms"}     once, when loaded and warm
//        {"op": "audio", "id", "rate", "ms", "mb"} + mono int16 little-endian PCM, one per say (maybe empty)
//        {"op": "error", "id", "msg"}
// Models are kept under FLUIDAUDIO_CACHE (a patch to FluidAudio). Anything else printed goes to stderr.
import Darwin
import FluidAudio
import Foundation

let rate = 24_000
let out = dup(1)
dup2(2, 1)

func log(_ s: String) { FileHandle.standardError.write(Data("kokoro-fluid: \(s)\n".utf8)) }
func nowMs() -> Double { Double(DispatchTime.now().uptimeNanoseconds) / 1e6 }

func writeAll(_ data: Data) {
    data.withUnsafeBytes { buf in
        var off = 0
        while off < buf.count {
            let n = write(out, buf.baseAddress! + off, buf.count - off)
            if n <= 0 { exit(1) }
            off += n
        }
    }
}

func readExactly(_ count: Int) -> Data? {
    var data = Data(count: count)
    var off = 0
    let ok = data.withUnsafeMutableBytes { buf -> Bool in
        while off < count {
            let n = read(0, buf.baseAddress! + off, count - off)
            if n <= 0 { return false }
            off += n
        }
        return true
    }
    return ok ? data : nil
}

func length(_ n: Int) -> Data { withUnsafeBytes(of: UInt32(n).bigEndian) { Data($0) } }

func send(_ header: [String: Any], _ payload: Data = Data()) {
    guard let h = try? JSONSerialization.data(withJSONObject: header) else { return }
    writeAll(length(h.count) + h + length(payload.count) + payload)
}

/// The next frame's header (the payload is read and dropped: requests carry none), or nil at the end of input.
func nextRequest() -> [String: Any]? {
    func size() -> Int? { readExactly(4).map { Int($0.reduce(0) { $0 << 8 | UInt32($1) }) } }
    guard let n = size(), let h = readExactly(n), let m = size(), m == 0 || readExactly(m) != nil else { return nil }
    return (try? JSONSerialization.jsonObject(with: h)) as? [String: Any] ?? [:]
}

/// What Activity Monitor calls the process's memory, in MB.
func footprintMB() -> Double {
    var info = rusage_info_v4()
    let rc = withUnsafeMutablePointer(to: &info) {
        $0.withMemoryRebound(to: rusage_info_t?.self, capacity: 1) { proc_pid_rusage(getpid(), RUSAGE_INFO_V4, $0) }
    }
    return rc == 0 ? (Double(info.ri_phys_footprint) / 1_048_576).rounded() : -1
}

func pcm(_ samples: [Float]) -> Data {
    let ints = samples.map { Int16((max(-1, min(1, $0)) * 32767).rounded()) }
    return ints.withUnsafeBufferPointer { Data(buffer: $0) }
}

let voices = Set(KokoroAneConstants.englishVoices)
let manager = KokoroAneManager(variant: .english, defaultVoice: "af_heart", version: .v3)
let t0 = nowMs()
do {
    try await manager.initialize(preloadVoices: ["af_heart"])
} catch {
    log("cannot load: \(error)")
    exit(2)
}
let loaded = nowMs()
// v3 plans each Core ML shape bucket on first use (text 32/64 tokens, decoder 120/200 frames, and the path for
// pieces over 5 s); touch them all, then the common ones again, so the first reply does not pay for it.
let warm = [
    "Okay.",
    "Warming up the voice engine now.",
    "This sentence is a little longer, so it lands in the larger decoder bucket.",
    "And this one is longer still, so that the path for long pieces is planned and ready before the first reply.",
]
for text in warm + warm.prefix(3) {
    _ = try? await manager.synthesizeDetailed(text: text, voice: "af_heart")
}
send(["op": "ready", "rate": rate, "load_ms": (loaded - t0).rounded(), "warmup_ms": (nowMs() - loaded).rounded()])

while let request = nextRequest() {
    let id = request["id"] as? String ?? ""
    guard request["op"] as? String == "say" else {
        send(["op": "error", "id": id, "msg": "unknown op \(request["op"] ?? "")"])
        continue
    }
    let text = request["text"] as? String ?? ""
    let voice = voices.contains(request["voice"] as? String ?? "") ? request["voice"] as! String : "af_heart"
    let speed = Float(request["speed"] as? Double ?? 1.0)
    let start = nowMs()
    do {
        let result: KokoroAneSynthesisResult
        do {
            result = try await manager.synthesizeDetailed(text: text, voice: voice, speed: speed)
        } catch {
            // v3 now and then rejects a run as non-finite (about 1 in 300-1000 pieces); the same piece again works.
            log("retrying after: \(error)")
            result = try await manager.synthesizeDetailed(text: text, voice: voice, speed: speed)
        }
        send(["op": "audio", "id": id, "rate": result.sampleRate, "ms": (nowMs() - start).rounded(),
              "mb": footprintMB()], pcm(result.samples))
    } catch {
        send(["op": "error", "id": id, "msg": "\(error)"])
    }
}
