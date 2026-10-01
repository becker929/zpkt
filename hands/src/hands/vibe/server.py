# Vibe server: bounce orchestration + self-improvement queue
"""Lightweight HTTP server for the vibe feedback loop.

Endpoints:
  POST /bounce                → trigger audio recording, return path to file
  POST /analyze               → spectral analysis of an audio file (FFT, LUFS, centroid)
  POST /feedback              → save feedback JSON to disk, return ack
  GET  /session               → return current session info
  GET  /audio/<filename>      → stream a bounced WAV/MP3 to the browser
  POST /self-improve          → start async self-improvement job, return job_id immediately
  GET  /self-improve/status   → return current job status (used by check_improvement tool)
  GET  /self-improve/stream   → SSE stream of live SDK log lines + final status
  GET  /sdk-log               → raw SDK session log file (text)
  POST /restart               → detached self-restart (responds before dying)

No FastAPI dependency — uses the stdlib http.server only.
Letta integration is optional: imported lazily; falls back to JSON-file logging.
CORS headers are included so the Next.js dev server (port 3000) can call directly.
"""
from __future__ import annotations

import json
import os
import os.path
import threading
import time
import uuid
from datetime import datetime, timezone
import hmac as _hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

_os_environ_get = os.environ.get
_ALLOWED_ORIGIN = os.environ.get("VIBE_ALLOWED_ORIGIN", "http://localhost:3000")
# Host names a request may address. Anything else is a DNS-rebinding attempt.
# host.docker.internal is how Letta (in Docker) reaches the server.
_ALLOWED_HOSTS = {"localhost", "127.0.0.1", "host.docker.internal",
                  *filter(None, os.environ.get("VIBE_ALLOWED_HOSTS", "").split(","))}
_MAX_BODY = 1_000_000


class VibeServer:
    """Vibe feedback server backed by stdlib HTTP.

    Args:
        output_dir: Directory for bounce files and feedback JSON.
        transport:  Any object with ``execute(code: str) -> dict``.
                    If None, bounce calls are no-ops (useful for testing).
    """

    def __init__(
        self,
        output_dir: str = ".",
        transport: Any = None,
    ) -> None:
        self._output_dir = Path(output_dir)
        self._output_dir.mkdir(parents=True, exist_ok=True)
        self._transport = transport
        self._session_id = str(uuid.uuid4())
        self._started_at = datetime.now(timezone.utc).isoformat()
        self._bounces: list[dict] = []
        self._bounce_lock = threading.Lock()
        self._letta_client = self._init_letta()

        # Async improvement job state — only one job may run at a time.
        self._job_lock = threading.Lock()
        self._improvement_job: dict[str, Any] | None = self._load_persisted_job()
        # Pending queue of improvement requests waiting to run sequentially.
        self._pending_queue: list[dict[str, Any]] = []

        # In-memory audio cache: (resolved_path_str, mtime) → (y_mono, sr, lufs_data)
        # Avoids re-decoding the same file across successive /analyze calls.
        self._audio_cache: dict[tuple[str, float], tuple[Any, int, Any]] = {}

    # ------------------------------------------------------------------
    # Persisted job state (survives vibe server restart)
    # ------------------------------------------------------------------

    def _load_persisted_job(self) -> "dict[str, Any] | None":
        """Load the last improvement job result from disk (written before restart)."""
        try:
            from hands.self_modify import IMPROVEMENT_PERSIST
            if not IMPROVEMENT_PERSIST.exists():
                return None
            data = json.loads(IMPROVEMENT_PERSIST.read_text())
            status = data.get("status", "completed")
            return {
                "id": "persisted",
                "status": status,
                "description": data.get("description", ""),
                "log_lines": [],
                "result": {
                    "agent_result": data.get("agent_result", ""),
                    "changed_files": data.get("changed_files", []),
                    "restarted_services": data.get("restarted_services", []),
                    "setup_tools_run": data.get("setup_tools_run", False),
                },
                "error": data.get("error"),
                "started_at": "",
            }
        except Exception:
            return None

    # ------------------------------------------------------------------
    # Letta (optional)
    # ------------------------------------------------------------------

    def _init_letta(self) -> Any:
        try:
            from letta import create_client  # type: ignore[import]
            client = create_client()
            return client
        except ImportError:
            return None
        except Exception:
            return None

    def _convert_to_mp3(self, wav_path: Path) -> Path | None:
        """Convert wav to mp3 using ffmpeg. Returns mp3 path on success, None if unavailable."""
        import shutil
        import subprocess

        if shutil.which("ffmpeg") is None:
            print("  [vibe] ffmpeg not found — keeping .wav")
            return None
        mp3_path = wav_path.with_suffix(".mp3")
        try:
            result = subprocess.run(
                ["ffmpeg", "-y", "-i", str(wav_path), "-codec:a", "libmp3lame", "-qscale:a", "2", str(mp3_path)],
                capture_output=True,
                timeout=120,
            )
            if result.returncode == 0 and mp3_path.exists():
                wav_path.unlink(missing_ok=True)
                return mp3_path
            print(f"  [vibe] ffmpeg error: {result.stderr.decode(errors='replace')[:200]}")
        except Exception as exc:
            print(f"  [vibe] ffmpeg conversion failed: {exc}")
        return None

    def _store_feedback_letta(self, submission: dict) -> None:
        if self._letta_client is None:
            return
        try:
            self._letta_client.send_message(
                role="user",
                message=json.dumps(submission),
            )
        except Exception as exc:
            print(f"  [vibe] letta store failed: {exc}")

    # ------------------------------------------------------------------
    # Business logic
    # ------------------------------------------------------------------

    def handle_bounce(self, body: dict) -> dict:
        """Export audio offline via Ableton's Export dialog and return the path."""
        if not self._bounce_lock.acquire(blocking=False):
            return {"error": "A bounce is already in progress — wait for it to finish"}
        try:
            return self._do_bounce(body)
        finally:
            self._bounce_lock.release()

    def _do_bounce(self, body: dict) -> dict:
        try:
            beats = int(body.get("beats", 64))
        except (ValueError, TypeError):
            beats = 64
        raw_name = body.get("output_path", f"bounce_{len(self._bounces):03d}.mp3")
        # Reject names with path separators to prevent directory traversal.
        filename = Path(raw_name).name
        if not filename or filename != raw_name:
            return {"error": "invalid output_path: must be a bare filename"}

        if self._transport is None:
            return {"error": "No Ableton transport — vibe server started without --mcp-host"}

        try:
            import sys, importlib
            vm_dir = str(Path(__file__).parents[4] / "ableton-live-vm")
            if vm_dir not in sys.path:
                sys.path.insert(0, vm_dir)
            export_offline = importlib.import_module("export_offline")
            out_path = export_offline.export_offline(
                filename=filename,
                duration_beats=float(beats),
                output_dir=str(self._output_dir),
            )
        except Exception as exc:
            return {"error": f"Offline export failed: {exc}"}

        if out_path is None:
            return {"error": "Offline export produced no output — check Ableton is running and has clips"}

        wav_path = Path(out_path)
        mp3_path = self._convert_to_mp3(wav_path)
        final_path = mp3_path if mp3_path is not None else wav_path
        final_name = final_path.name

        self._bounces.append({
            "filename": final_name,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "beats": beats,
        })
        return {"path": final_name, "beats": beats}

    # ------------------------------------------------------------------
    # Async self-improvement job management
    # ------------------------------------------------------------------

    def _run_improvement(
        self,
        job_id: str,
        description: str,
        prompt: str,
        restart: list[str] | None,
    ) -> None:
        """Background thread: run apply_improvement and update job state."""
        import asyncio

        def _progress(line: str) -> None:
            with self._job_lock:
                if self._improvement_job and self._improvement_job["id"] == job_id:
                    self._improvement_job["log_lines"].append(line)

        try:
            from hands.self_modify import apply_improvement
        except ImportError as exc:
            with self._job_lock:
                if self._improvement_job and self._improvement_job["id"] == job_id:
                    self._improvement_job["status"] = "failed"
                    self._improvement_job["error"] = (
                        f"claude-agent-sdk not installed: {exc}. "
                        "Run: uv pip install 'hands[self-improve]'"
                    )
            return

        try:
            result = asyncio.run(
                apply_improvement(description, prompt, restart, progress_callback=_progress)
            )
            with self._job_lock:
                if self._improvement_job and self._improvement_job["id"] == job_id:
                    self._improvement_job["status"] = "completed"
                    self._improvement_job["result"] = result
        except Exception as exc:
            with self._job_lock:
                if self._improvement_job and self._improvement_job["id"] == job_id:
                    self._improvement_job["status"] = "failed"
                    self._improvement_job["error"] = str(exc)
        finally:
            self._start_next_queued()

    def handle_self_improve(self, body: dict) -> dict:
        """Start an async self-improvement job. Returns job_id immediately.

        Body fields:
          description  — short label for the improvement (required)
          prompt       — full instructions for the Claude Code session (required)
          restart      — optional list of service names to restart instead of auto-detecting
        """
        description = str(body.get("description") or "").strip()
        prompt = str(body.get("prompt") or "").strip()
        if not description or not prompt:
            return {"error": "both 'description' and 'prompt' are required"}

        restart = body.get("restart")
        if restart is not None and not isinstance(restart, list):
            return {"error": "'restart' must be a list of service names or omitted"}

        with self._job_lock:
            if (
                self._improvement_job is not None
                and self._improvement_job["status"] == "running"
            ):
                # Job already running — add to pending queue.
                queue_id = str(uuid.uuid4())[:8]
                item: dict[str, Any] = {
                    "queue_id": queue_id,
                    "description": description,
                    "prompt": prompt,
                    "restart": restart,
                    "added_at": datetime.now(timezone.utc).isoformat(),
                }
                self._pending_queue.append(item)
                position = len(self._pending_queue)
                print(f"  [vibe] improvement queued (position {position}): {description!r}")
                return {"status": "queued", "queue_id": queue_id, "position": position}

            job_id = str(uuid.uuid4())[:8]
            self._improvement_job = {
                "id": job_id,
                "status": "running",
                "description": description,
                "log_lines": [],
                "result": None,
                "error": None,
                "started_at": datetime.now(timezone.utc).isoformat(),
            }

        thread = threading.Thread(
            target=self._run_improvement,
            args=(job_id, description, prompt, restart),
            daemon=True,
        )
        thread.start()

        print(f"  [vibe] improvement job {job_id} started: {description!r}")
        return {"job_id": job_id, "status": "started"}

    def _start_next_queued(self) -> None:
        """Pop the next pending improvement from the queue and start it."""
        with self._job_lock:
            if not self._pending_queue:
                return
            next_item = self._pending_queue.pop(0)
            job_id = str(uuid.uuid4())[:8]
            self._improvement_job = {
                "id": job_id,
                "status": "running",
                "description": next_item["description"],
                "log_lines": [],
                "result": None,
                "error": None,
                "started_at": datetime.now(timezone.utc).isoformat(),
            }

        thread = threading.Thread(
            target=self._run_improvement,
            args=(job_id, next_item["description"], next_item["prompt"], next_item.get("restart")),
            daemon=True,
        )
        thread.start()
        print(f"  [vibe] auto-started queued improvement {job_id}: {next_item['description']!r}")

    def get_improvement_queue(self) -> dict:
        """Return pending (not yet started) improvement queue items."""
        with self._job_lock:
            items = [
                {
                    "queue_id": item["queue_id"],
                    "description": item["description"],
                    "prompt_preview": item["prompt"][:120],
                    "added_at": item["added_at"],
                }
                for item in self._pending_queue
            ]
        return {"items": items}

    def remove_from_queue(self, queue_id: str) -> dict:
        """Remove a pending improvement from the queue by queue_id."""
        with self._job_lock:
            before = len(self._pending_queue)
            self._pending_queue = [i for i in self._pending_queue if i["queue_id"] != queue_id]
            removed = before - len(self._pending_queue)
        if removed:
            print(f"  [vibe] removed queued improvement {queue_id!r}")
            return {"removed": True}
        return {"error": "not found"}

    def get_improvement_status(self) -> dict:
        """Return current improvement job status (JSON endpoint)."""
        with self._job_lock:
            if self._improvement_job is None:
                return {"status": "idle"}
            job = dict(self._improvement_job)

        result: dict[str, Any] = {
            "job_id": job["id"],
            "status": job["status"],
            "description": job["description"],
            "started_at": job["started_at"],
            "log_line_count": len(job["log_lines"]),
        }
        if job["status"] == "completed" and job["result"]:
            result["changed_files"] = job["result"].get("changed_files", [])
            result["restarted_services"] = job["result"].get("restarted_services", [])
            result["agent_result"] = (job["result"].get("agent_result") or "")[:300]
            result["setup_tools_run"] = job["result"].get("setup_tools_run", False)
        if job["status"] == "failed":
            result["error"] = job["error"]
        return result

    def stream_improvement(self, handler: "BaseHTTPRequestHandler") -> None:
        """SSE stream of SDK log lines + final status event.

        Sends one SSE event per log line as they arrive, then sends a final
        'status' event when the job completes or fails, and closes the stream.
        Polls every 0.2 s so latency is acceptable without busy-waiting.
        """
        encoder = lambda s: s.encode()

        def send(data: dict) -> bool:
            """Write one SSE data frame. Returns False if the connection is closed."""
            try:
                handler.wfile.write(f"data: {json.dumps(data)}\n\n".encode())
                handler.wfile.flush()
                return True
            except (BrokenPipeError, ConnectionResetError, OSError):
                return False

        def heartbeat() -> bool:
            try:
                handler.wfile.write(b": heartbeat\n\n")
                handler.wfile.flush()
                return True
            except (BrokenPipeError, ConnectionResetError, OSError):
                return False

        sent_index = 0
        last_heartbeat = time.monotonic()

        while True:
            with self._job_lock:
                job = self._improvement_job
                if job is None:
                    send({"status": "idle", "message": "No improvement job has been started."})
                    return

                new_lines = job["log_lines"][sent_index:]
                status = job["status"]
                final_result = job.get("result")
                final_error = job.get("error")

            for line in new_lines:
                if not send({"line": line, "index": sent_index}):
                    return
                sent_index += 1

            now = time.monotonic()
            if now - last_heartbeat >= 3.0:
                if not heartbeat():
                    return
                last_heartbeat = now

            if status in ("completed", "failed"):
                payload: dict[str, Any] = {"status": status}
                if status == "completed" and final_result:
                    payload["changed_files"] = final_result.get("changed_files", [])
                    payload["restarted_services"] = final_result.get("restarted_services", [])
                    payload["agent_result"] = (final_result.get("agent_result") or "")[:300]
                    payload["setup_tools_run"] = final_result.get("setup_tools_run", False)
                if status == "failed":
                    payload["error"] = final_error
                send(payload)
                return

            time.sleep(0.2)

    def handle_restart(self) -> dict:
        """Schedule a self-restart and return immediately.

        Spawns a detached subprocess (new session) that runs
        ``make stop-vibe start-vibe`` after a short delay so the HTTP
        response has time to flush before the server process is killed.
        """
        import subprocess

        hands_dir = str(Path(__file__).parents[3])

        def _restart() -> None:
            time.sleep(0.5)
            subprocess.Popen(
                ["make", "-C", hands_dir, "stop-vibe", "start-vibe"],
                start_new_session=True,  # detach from vibe's process group
                stdout=open("/tmp/vibe-restart.log", "w"),
                stderr=subprocess.STDOUT,
            )

        threading.Thread(target=_restart, daemon=False).start()
        return {
            "status": "restarting",
            "message": "Vibe server restarting. Wait ~5s then verify with a command.",
        }

    _ALL_FIELDS = frozenset(
        ["lufs", "spectral_centroid_hz", "peak_frequency_hz", "energy_by_band", "spectrum"]
    )
    _FFT_FIELDS = frozenset(
        ["spectral_centroid_hz", "peak_frequency_hz", "energy_by_band", "spectrum"]
    )

    def _load_audio_cached(self, resolved: Path) -> "tuple[Any, int, Any] | dict":
        """Load audio data, using the in-memory cache keyed by (path, mtime).

        Returns (y_mono, sr, lufs_data) on success, or an error dict on failure.
        Evicts stale entries when the file's mtime changes.
        """
        try:
            import librosa  # type: ignore[import]
            import numpy as np  # type: ignore[import]
        except ImportError as exc:
            return {"error": f"missing dependency: {exc} — run: uv pip install 'hands[vibe]'"}

        mtime = resolved.stat().st_mtime
        cache_key = (str(resolved), mtime)

        if cache_key in self._audio_cache:
            return self._audio_cache[cache_key]

        # Evict any stale entry for this path (different mtime)
        stale = [k for k in self._audio_cache if k[0] == str(resolved)]
        for k in stale:
            del self._audio_cache[k]

        try:
            y_raw, sr = librosa.load(str(resolved), sr=22050, mono=False)
        except Exception as exc:
            return {"error": f"failed to load audio: {exc}"}

        if y_raw.ndim == 1:
            y_mono = y_raw
            lufs_data = y_raw
        else:
            y_mono = y_raw.mean(axis=0)
            lufs_data = y_raw.T  # (channels, samples) → (samples, channels)

        result = (y_mono, int(sr), lufs_data)
        self._audio_cache[cache_key] = result
        return result

    def handle_analyze(self, body: dict) -> dict:
        """Fast spectral snapshot of an audio file.

        Body fields:
          file_path — path to audio file, relative to the vibe server output_dir (required)
          fields    — optional list of datapoints to compute (default: all).
                      Valid values: "lufs", "spectral_centroid_hz", "peak_frequency_hz",
                      "energy_by_band", "spectrum".
                      Requesting only "lufs" skips the FFT entirely (~10x faster on a
                      cached file). Audio is cached by (path, mtime) across calls.

        Returns only the requested fields plus "file".

        ── EARS INTEGRATION NOTE ────────────────────────────────────────────
        For a complete AudioProfile (MFCCs, chroma, short-term/momentary LUFS,
        Camelot key, 512-dim DCLAP embedding for semantic similarity), use the
        ``/profile`` endpoint instead. It calls the ``ears`` package at
        agent-sandbox/ears/ via subprocess and returns the full AudioProfile JSON.

        When to use which:
          /analyze  → fast iteration checks during kick design (LUFS, peak, bands)
          /profile  → full characterisation before comparing renders, or when
                      you need DCLAP cosine similarity between two bounces

        The ears package is the long-term home for all audio perception.
        Planned additions: Gemini audio descriptions, learned similarity fusion,
        stem separation, batch analysis. See agent-notes/20260326/plan-09-ears-repo.md.
        ─────────────────────────────────────────────────────────────────────
        """
        raw_path = str(body.get("file_path") or "").strip()
        if not raw_path:
            return {"error": "file_path is required"}

        file_path_input = Path(raw_path)
        if file_path_input.is_absolute():
            return {"error": "file_path must be relative"}

        resolved = (self._output_dir / file_path_input).resolve()
        try:
            resolved.relative_to(self._output_dir.resolve())
        except ValueError:
            return {"error": "invalid file_path: path traversal not allowed"}

        if not resolved.exists():
            return {"error": f"file not found: {raw_path}"}

        requested_fields = body.get("fields")
        if requested_fields is None:
            fields = self._ALL_FIELDS
        elif not isinstance(requested_fields, list):
            return {"error": "'fields' must be a list of field names or omitted"}
        else:
            unknown = set(requested_fields) - self._ALL_FIELDS
            if unknown:
                return {"error": f"unknown fields: {sorted(unknown)}. Valid: {sorted(self._ALL_FIELDS)}"}
            fields = frozenset(requested_fields)

        try:
            import numpy as np  # type: ignore[import]
            import pyloudnorm as pyln  # type: ignore[import]
        except ImportError as exc:
            return {"error": f"missing dependency: {exc} — run: uv pip install 'hands[vibe]'"}

        audio = self._load_audio_cached(resolved)
        if isinstance(audio, dict):
            return audio
        y_mono, sr, lufs_data = audio

        result: dict = {"file": resolved.name}

        if "lufs" in fields:
            try:
                meter = pyln.Meter(sr)
                lufs_raw = meter.integrated_loudness(lufs_data)
                result["lufs"] = round(float(lufs_raw), 2) if np.isfinite(lufs_raw) else -70.0
            except Exception:
                result["lufs"] = None

        need_fft = bool(fields & self._FFT_FIELDS)
        if need_fft:
            n_fft = 4096
            fft_mag = np.abs(np.fft.rfft(y_mono, n=n_fft))
            freqs = np.fft.rfftfreq(n_fft, d=1.0 / sr)
            power = fft_mag ** 2
            total_power = float(np.sum(power))

            if "energy_by_band" in fields:
                bands = {
                    "sub_bass_20_60hz":      (20,   60),
                    "bass_60_250hz":         (60,   250),
                    "low_mids_250_500hz":    (250,  500),
                    "mids_500_2000hz":       (500,  2000),
                    "high_mids_2000_6000hz": (2000, 6000),
                    "highs_6000_20000hz":    (6000, 20000),
                }
                energy_by_band: dict[str, float] = {}
                for name, (lo, hi) in bands.items():
                    mask = (freqs >= lo) & (freqs < hi)
                    band_power = float(np.sum(power[mask]))
                    energy_by_band[name] = (
                        round(band_power / total_power, 4) if total_power > 0 else 0.0
                    )
                result["energy_by_band"] = energy_by_band

            if "spectral_centroid_hz" in fields or "peak_frequency_hz" in fields:
                audible = (freqs >= 20) & (freqs <= 20000)
                audible_power = power[audible]
                audible_freqs = freqs[audible]

                if "spectral_centroid_hz" in fields:
                    centroid_denom = float(np.sum(audible_power))
                    result["spectral_centroid_hz"] = (
                        round(float(np.sum(audible_freqs * audible_power) / centroid_denom), 1)
                        if centroid_denom > 0 else 0.0
                    )

                if "peak_frequency_hz" in fields:
                    result["peak_frequency_hz"] = round(
                        float(audible_freqs[np.argmax(audible_power)]), 1
                    )

            if "spectrum" in fields:
                log_freqs = np.logspace(np.log10(20), np.log10(20000), 100)
                spectrum: list[list[float]] = []
                for f in log_freqs:
                    idx = int(np.argmin(np.abs(freqs - f)))
                    db = float(20.0 * np.log10(fft_mag[idx] + 1e-10))
                    spectrum.append([round(float(f), 1), round(db, 1)])
                result["spectrum"] = spectrum

        return result

    def handle_feedback(self, body: dict) -> dict:
        """Save feedback JSON to disk (and optionally to Letta memory)."""
        submission = {
            "session_id": body.get("session_id", self._session_id),
            "text": body.get("text", ""),
            "rating": body.get("rating"),
            "bounce_path": body.get("bounce_path"),
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        }
        feedback_path = self._output_dir / f"feedback_{uuid.uuid4().hex[:8]}.json"
        feedback_path.write_text(json.dumps(submission, indent=2))
        self._store_feedback_letta(submission)
        return {"ack": True, "saved": str(feedback_path)}

    def handle_profile(self, body: dict) -> dict:
        """Run the full ears AudioProfile pipeline on a bounce file.

        Calls ``uv run ears analyze --json`` in a subprocess, keeping ears'
        heavy dependencies (onnxruntime, etc.) isolated from the vibe server's
        environment.

        Body fields:
          file_path      — bare filename relative to the vibe output_dir (required)
          no_embeddings  — skip 512-dim DCLAP embedding (faster, default False)
          rhythm         — run madmom beat tracking (needs ears[rhythm], default False)
          pitch          — run basic-pitch (needs ears[pitch], default False)

        Returns the full AudioProfile as a JSON object, or an error dict.

        NOTE: This endpoint uses the `ears` package at
        /Users/anthonybecker/Desktop/agent-sandbox/ears.
        See that directory for the full AudioProfile schema, CLI, and planned
        extensions (similarity scoring, Gemini descriptions, learned fusion model).
        The `ears` project is the long-term home for audio perception —
        `/analyze` provides a fast subset; `/profile` is the complete pipeline.
        """
        import subprocess

        raw_path = str(body.get("file_path") or "").strip()
        if not raw_path:
            return {"error": "file_path is required"}

        file_path_input = Path(raw_path)
        if file_path_input.is_absolute():
            return {"error": "file_path must be relative"}

        resolved = (self._output_dir / file_path_input).resolve()
        try:
            resolved.relative_to(self._output_dir.resolve())
        except ValueError:
            return {"error": "invalid file_path: path traversal not allowed"}

        if not resolved.exists():
            return {"error": f"file not found: {raw_path}"}

        ears_dir = str(Path(__file__).parents[4] / "ears")
        cmd = ["uv", "run", "--project", ears_dir, "ears", "analyze", str(resolved), "--json"]
        if body.get("no_embeddings"):
            cmd.append("--no-embeddings")
        if body.get("rhythm"):
            cmd.append("--rhythm")
        if body.get("pitch"):
            cmd.append("--pitch")

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=120,
                cwd=ears_dir,
            )
        except subprocess.TimeoutExpired:
            return {"error": "ears analysis timed out after 120s"}
        except Exception as exc:
            return {"error": f"failed to launch ears: {exc}"}

        if result.returncode != 0:
            stderr_snippet = (result.stderr or "").strip()[-400:]
            return {"error": f"ears exited {result.returncode}: {stderr_snippet}"}

        try:
            import json as _json
            return _json.loads(result.stdout)
        except Exception as exc:
            return {"error": f"could not parse ears output: {exc}", "raw": result.stdout[:500]}

    def get_session(self) -> dict:
        return {
            "session_id": self._session_id,
            "started_at": self._started_at,
            "bounces": [b["filename"] for b in self._bounces],
        }

    # ------------------------------------------------------------------
    # HTTP handler
    # ------------------------------------------------------------------

    def _make_handler(self) -> type[BaseHTTPRequestHandler]:
        server = self

        class _Handler(BaseHTTPRequestHandler):
            _AUDIO_MIME = {".wav": "audio/wav", ".mp3": "audio/mpeg"}

            def log_message(self, fmt: str, *args: Any) -> None:  # silence access log
                pass

            # ── CORS helpers ────────────────────────────────────────────────

            def _add_cors(self) -> None:
                # Only the local chat UI may call from a browser. "*" let any
                # web page the user visited drive this server.
                self.send_header("Access-Control-Allow-Origin", _ALLOWED_ORIGIN)
                self.send_header("Vary", "Origin")
                self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
                self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")

            def _guard(self) -> bool:
                """Reject rebinding, cross-site and (when tunnelled) anonymous requests.

                Returns True when the request may proceed; otherwise it has
                already been answered.
                """
                host = (self.headers.get("Host") or "").rsplit(":", 1)[0].strip("[]").lower()
                if host not in _ALLOWED_HOSTS:
                    self._send_json({"error": "forbidden host"}, 403)
                    return False
                origin = self.headers.get("Origin")
                if origin and origin != _ALLOWED_ORIGIN:
                    self._send_json({"error": "forbidden origin"}, 403)
                    return False
                if self.command == "POST" and not (self.headers.get("Content-Type") or "").startswith("application/json"):
                    # Cross-site "simple" requests (text/plain) skip CORS preflight.
                    self._send_json({"error": "Content-Type must be application/json"}, 415)
                    return False
                if _os_environ_get("VIBE_TUNNEL") and not self._authorized():
                    # Tunnelled means public: every endpoint needs the token.
                    self._refuse()
                    return False
                return True

            def _authorized(self) -> bool:
                """True only when VIBE_TOKEN is set and the request carries it."""
                token = _os_environ_get("VIBE_TOKEN")
                sent = self.headers.get("Authorization", "")
                return bool(token) and _hmac.compare_digest(sent, "Bearer " + token)

            def _refuse(self) -> None:
                self._send_json(
                    {"error": "forbidden: set VIBE_TOKEN and send 'Authorization: Bearer <token>'"},
                    403,
                )

            def do_OPTIONS(self) -> None:  # noqa: N802
                self.send_response(204)
                self._add_cors()
                self.end_headers()

            # ── Request helpers ─────────────────────────────────────────────

            def _read_body(self) -> dict:
                length = min(int(self.headers.get("Content-Length", 0) or 0), _MAX_BODY)
                raw = self.rfile.read(length) if length else b"{}"
                try:
                    return json.loads(raw)
                except json.JSONDecodeError:
                    return {}

            def _send_json(self, data: dict, status: int = 200) -> None:
                payload = json.dumps(data).encode()
                self.send_response(status)
                self._add_cors()
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def _send_audio(self, file_path: Path, mime: str) -> None:
                import shutil
                size = file_path.stat().st_size
                self.send_response(200)
                self._add_cors()
                self.send_header("Content-Type", mime)
                self.send_header("Content-Length", str(size))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                with file_path.open("rb") as fh:
                    shutil.copyfileobj(fh, self.wfile)

            def _start_sse(self) -> None:
                """Send SSE response headers (no Content-Length — chunked/streaming)."""
                self.send_response(200)
                self._add_cors()
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Connection", "keep-alive")
                self.send_header("X-Accel-Buffering", "no")
                self.end_headers()

            # ── Route handlers ──────────────────────────────────────────────

            def do_GET(self) -> None:  # noqa: N802
                if not self._guard():
                    return
                if self.path == "/session":
                    self._send_json(server.get_session())
                    return

                if self.path.startswith("/audio/"):
                    filename = self.path[len("/audio/"):]
                    # Reject path traversal
                    if "/" in filename or ".." in filename or not filename:
                        self._send_json({"error": "invalid filename"}, 400)
                        return
                    ext = os.path.splitext(filename)[1].lower()
                    mime = self._AUDIO_MIME.get(ext)
                    if not mime:
                        self._send_json({"error": "unsupported type"}, 415)
                        return
                    file_path = server._output_dir / filename
                    if not file_path.exists():
                        self._send_json({"error": "not found"}, 404)
                        return
                    self._send_audio(file_path, mime)
                    return

                if self.path == "/history":
                    self._send_json({"bounces": server._bounces})
                    return

                if self.path == "/sdk-log":
                    from hands.self_modify import SDK_LOG
                    if SDK_LOG.exists():
                        text = SDK_LOG.read_text(errors="replace")
                    else:
                        text = "(no SDK session log yet)"
                    payload = text.encode()
                    self.send_response(200)
                    self._add_cors()
                    self.send_header("Content-Type", "text/plain; charset=utf-8")
                    self.send_header("Content-Length", str(len(payload)))
                    self.end_headers()
                    self.wfile.write(payload)
                    return

                if self.path == "/self-improve/status":
                    self._send_json(server.get_improvement_status())
                    return

                if self.path == "/self-improve/queue":
                    self._send_json(server.get_improvement_queue())
                    return

                if self.path == "/self-improve/stream":
                    self._start_sse()
                    server.stream_improvement(self)
                    return

                self._send_json({"error": "not found"}, 404)

            def do_DELETE(self) -> None:  # noqa: N802
                if not self._guard():
                    return
                if not self._authorized():
                    self._refuse()
                    return
                if self.path.startswith("/self-improve/queue/"):
                    queue_id = self.path[len("/self-improve/queue/"):]
                    if not queue_id or "/" in queue_id:
                        self._send_json({"error": "invalid queue_id"}, 400)
                        return
                    self._send_json(server.remove_from_queue(queue_id))
                    return
                self._send_json({"error": "not found"}, 404)

            def do_POST(self) -> None:  # noqa: N802
                if not self._guard():
                    return
                body = self._read_body()
                if self.path == "/bounce":
                    self._send_json(server.handle_bounce(body))
                elif self.path == "/feedback":
                    self._send_json(server.handle_feedback(body))
                elif self.path in ("/self-improve", "/restart") and not self._authorized():
                    # Both change or restart the running code.
                    self._refuse()
                elif self.path == "/self-improve":
                    self._send_json(server.handle_self_improve(body))
                elif self.path == "/restart":
                    self._send_json(server.handle_restart())
                elif self.path == "/analyze":
                    self._send_json(server.handle_analyze(body))
                elif self.path == "/profile":
                    self._send_json(server.handle_profile(body))
                else:
                    self._send_json({"error": "not found"}, 404)

        return _Handler

    # ------------------------------------------------------------------
    # Serve
    # ------------------------------------------------------------------

    def serve(self, port: int = 8080, host: str = "127.0.0.1") -> None:
        """Start the HTTP server (blocks until interrupted).

        Binds to loopback by default. Docker Desktop still reaches it via
        host.docker.internal; pass host="0.0.0.0" only on a trusted network.
        """
        httpd = ThreadingHTTPServer((host, port), self._make_handler())
        print(f"  [vibe] listening on http://{host}:{port}")
        print(f"  [vibe] session: {self._session_id}")
        print(f"  [vibe] output:  {self._output_dir}")
        print("  [vibe] POST /self-improve          — start async improvement job (returns immediately)")
        print("  [vibe] GET  /self-improve/status   — poll job status")
        print("  [vibe] GET  /self-improve/stream   — SSE live progress stream")
        print("  [vibe] POST /restart               — detached self-restart")
        print("  [vibe] POST /analyze               — spectral analysis: LUFS, FFT, energy bands (cached, supports ?fields)")
        print("  [vibe] POST /profile               — full ears AudioProfile: spectral + loudness + DCLAP embedding (subprocess)")
        if self._letta_client is None:
            print("  [vibe] letta unavailable — feedback stored as JSON files only")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\n  [vibe] shutting down")
            httpd.server_close()
