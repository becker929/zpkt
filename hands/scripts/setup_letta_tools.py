"""Register all Ableton tools and skills with the Letta agent — idempotent.

Usage:
    uv run scripts/setup_letta_tools.py [--agent-id AGENT_ID] [--base-url URL]

What this does:
  1. Connects to the local Letta server (http://localhost:8283 by default).
  2. Creates / updates the run_bounce custom tool.
  3. Registers the ableton-live MCP server (Streamable HTTP bridge).
  4. Creates Letta tools for each MCP tool (execute, api, search_api).
  5. Creates / updates the request_improvement custom tool.
  6. Attaches all tools to agents named "Vibe" (or all agents if none match).
  7. Upserts core memory block `ableton_rules` (crash avoidance — always in context).
  8. Upserts core memory block `harness_rules` (self-improvement guide — always in context).
  9. Upserts source `ableton-guide` (full reference — semantically searchable).

Architecture:
  Letta (Vibe)
    ├── execute             (MCP)    → bridge:9010/mcp → TCP:16619 → Ableton
    ├── api                 (MCP)    → bridge:9010/mcp → TCP:16619 → Ableton
    ├── search_api          (MCP)    → bridge:9010/mcp → TCP:16619 → Ableton
    ├── run_bounce          (custom) → POST :8080/bounce → TCP:16619 → Ableton
    ├── request_improvement (custom) → POST :8080/self-improve → Claude Agent SDK
    ├── [block] ableton_rules  — crash avoidance rules, always in context
    ├── [block] harness_rules  — self-improvement guide, always in context
    └── [source] ableton-guide — full LOM guide + devices, semantically searchable

Prerequisites:
  make start-letta          # Letta server on port 8283
  make start-ableton-mcp   # Bridge server on port 9010
"""
from __future__ import annotations

import argparse
import email.generator
import email.mime.multipart
import email.mime.text
import io
import json
import os
import pathlib
import sys
import urllib.error
import urllib.request

# ── Skill file paths (relative to this script's location) ─────────────────────
_SCRIPT_DIR = pathlib.Path(__file__).parent
_SKILL_DIR = _SCRIPT_DIR.parent.parent / ".cursor" / "skills" / "ableton-guide"
_SKILL_MD = _SKILL_DIR / "SKILL.md"
_DEVICES_MD = _SKILL_DIR / "references" / "available-devices.md"

# ── run_bounce source (custom Letta tool) ─────────────────────────────────────

_RUN_BOUNCE_SOURCE = '''import json
import os
import urllib.error
import urllib.request


def run_bounce(beats: int = 64, output_path: str = "bounce.wav") -> str:
    """Bounce the current Ableton Live session to an audio file.

    Calls the local vibe server (POST /bounce) which triggers a recording via
    the Ableton MCP Remote Script and writes the result to disk.

    Args:
        beats: Number of beats to record (default: 64).
        output_path: Output filename, e.g. "bounce_v2.wav". Must be a bare filename with no directory separators.

    Returns:
        A status string with the output path and beat count, or an error message.
    """
    vibe_url = os.environ.get("VIBE_SERVER_URL", "http://host.docker.internal:8080")
    endpoint = vibe_url + "/bounce"

    payload = json.dumps({"beats": beats, "output_path": output_path}).encode()
    req = urllib.request.Request(
        endpoint,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            result = json.loads(resp.read())
    except urllib.error.URLError as exc:
        msg = "Could not reach vibe server at " + endpoint + ": " + str(exc) + ". Start it with: cd /Users/anthonybecker/Desktop/agent-sandbox/hands && make start-vibe"
        return msg
    except Exception as exc:
        return "Bounce request failed: " + str(exc)

    if "error" in result:
        return "Bounce failed: " + result["error"]
    beats_done = result.get("beats", beats)
    path_done = result.get("path", output_path)
    return "Bounced " + str(beats_done) + " beats -> " + path_done
'''

# ── request_improvement source (custom Letta tool) ────────────────────────────

_REQUEST_IMPROVEMENT_SOURCE = '''import json
import os
import urllib.error
import urllib.request


def request_improvement(description: str, prompt: str) -> str:
    """Start an async self-improvement job on the agent harness.

    This tool starts a Claude Agent SDK session in the background that modifies
    the agent\'s own code (skills, server modules, config) and restarts the
    affected services automatically.

    The job returns IMMEDIATELY — the producer can watch live progress in the
    chat via the vibe server SSE stream. Call check_improvement() later to
    confirm the result.

    IMPORTANT RULES before calling this tool:
    - Be specific: reference exact file paths and line ranges in the prompt.
    - Be conservative: only request changes you are confident about.
    - Never request changes to setup_letta_tools.py without explicit user approval.
    - Never request a Letta restart — that must be done manually.
    - After calling, narrate what you started, then call check_improvement() to
      confirm the result (wait ~30-60 seconds first for simple edits, 2-5 minutes
      for complex ones).

    Args:
        description: Short label, e.g. "add /health endpoint to vibe server".
        prompt: Full instructions for the Claude Code editing session. Include
                file paths, what to change, and why. The more specific, the better.

    Returns:
        A status string with the job_id, or an error message.
    """
    vibe_url = os.environ.get("VIBE_SERVER_URL", "http://host.docker.internal:8080")
    endpoint = vibe_url + "/self-improve"

    payload = json.dumps({"description": description, "prompt": prompt}).encode()
    req = urllib.request.Request(
        endpoint,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read())
    except urllib.error.URLError as exc:
        return (
            "Could not reach vibe server at " + endpoint + ": " + str(exc) +
            ". Start it with: cd /Users/anthonybecker/Desktop/agent-sandbox/hands && make start-vibe"
        )
    except Exception as exc:
        return "request_improvement failed: " + str(exc)

    if "error" in result:
        return "Could not start improvement: " + result["error"]

    if result.get("status") == "queued":
        queue_id = result.get("queue_id", "?")
        position = result.get("position", "?")
        return (
            "Improvement queued (queue_id: " + str(queue_id) + ", position: " + str(position) + "). "
            "It will start automatically after the current job finishes. "
            "The producer can track it in the Improvements panel."
        )

    job_id = result.get("job_id", "?")
    return (
        "Improvement job started (id: " + job_id + "). "
        "The producer can see live progress in the chat. "
        "Call check_improvement() in ~1-5 minutes to confirm the result."
    )
'''

# ── check_improvement source (custom Letta tool) ──────────────────────────────

_CHECK_IMPROVEMENT_SOURCE = '''import json
import os
import urllib.error
import urllib.request


def check_improvement() -> str:
    """Check the status of the most recent self-improvement job.

    Polls the vibe server for the current improvement job status. Use this
    after calling request_improvement() to confirm whether the edit landed.

    If the job is still running, call again after waiting a bit.
    If the job completed, the result will include changed files and restarted
    services. If it failed, the error message will be returned.

    Returns:
        A human-readable status summary string.
    """
    vibe_url = os.environ.get("VIBE_SERVER_URL", "http://host.docker.internal:8080")
    endpoint = vibe_url + "/self-improve/status"

    req = urllib.request.Request(endpoint, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read())
    except urllib.error.URLError as exc:
        return (
            "Could not reach vibe server at " + endpoint + ": " + str(exc) +
            ". Start it with: cd /Users/anthonybecker/Desktop/agent-sandbox/hands && make start-vibe"
        )
    except Exception as exc:
        return "check_improvement failed: " + str(exc)

    status = result.get("status", "unknown")

    if status == "idle":
        return (
            "No active improvement job found. "
            "If you just called request_improvement and the vibe server restarted, "
            "the job likely completed successfully — verify by testing the affected tool "
            "directly (e.g. call analyze_audio or run_bounce). "
            "The server clears job state on restart; a successful restart IS the confirmation."
        )

    job_id = result.get("job_id", "?")
    description = result.get("description", "?")
    log_lines = result.get("log_line_count", 0)

    if status == "running":
        return (
            "Job " + job_id + " (" + description + ") is still running. "
            + str(log_lines) + " log lines so far. Check again in a minute."
        )

    if status == "completed":
        changed = result.get("changed_files", [])
        restarted = result.get("restarted_services", [])
        summary = result.get("agent_result", "")[:200]
        parts = ["Job " + job_id + " completed."]
        if changed:
            parts.append("Changed: " + ", ".join(changed))
        if restarted:
            parts.append("Restarted: " + ", ".join(restarted))
        if result.get("setup_tools_run"):
            parts.append("Re-registered Letta tools.")
        if summary:
            parts.append("Summary: " + summary)
        return " | ".join(parts)

    if status == "failed":
        error = result.get("error", "unknown error")
        return "Job " + job_id + " failed: " + error

    return "Unknown status: " + status
'''

# ── analyze_audio source (custom Letta tool) ─────────────────────────────────

_ANALYZE_AUDIO_SOURCE = '''import json
import os
import urllib.error
import urllib.request


def analyze_audio(file_path: str, fields: list = None) -> str:
    """Analyze spectral characteristics of a bounced audio file.

    Calls POST /analyze on the vibe server. The vibe server caches loaded audio
    by (path, mtime), so the first call for a file takes ~5s (decode + resample)
    but subsequent calls for different fields on the same file are sub-second.

    Request specific fields to get fast, targeted answers:
      - "lufs"                  — integrated loudness in LUFS (skip FFT entirely)
      - "peak_frequency_hz"     — dominant frequency in the audible range
      - "spectral_centroid_hz"  — energy-weighted center frequency
      - "energy_by_band"        — fraction of energy in 6 sub-bass→highs bands
      - "spectrum"              — 100 log-spaced [freq_hz, dB] pairs (20–20 kHz)

    Omit `fields` to compute everything (slower on first call).

    Workflow for fast iteration:
      1. analyze_audio("bounce.mp3", ["lufs"])            → instant loudness check
      2. analyze_audio("bounce.mp3", ["peak_frequency_hz"]) → cached, <0.5s
      3. analyze_audio("bounce.mp3", ["energy_by_band"])    → cached, <0.5s

    Args:
        file_path: Bare filename relative to the vibe output dir, e.g. "bounce.mp3".
        fields:    Optional list of field names. Omit for all fields.

    Returns:
        JSON string with the requested fields, or an error message.
    """
    vibe_url = os.environ.get("VIBE_SERVER_URL", "http://host.docker.internal:8080")
    endpoint = vibe_url + "/analyze"

    body = {"file_path": file_path}
    if fields is not None:
        body["fields"] = fields

    payload = json.dumps(body).encode()
    req = urllib.request.Request(
        endpoint,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read())
    except urllib.error.URLError as exc:
        return "Could not reach vibe server at " + endpoint + ": " + str(exc)
    except Exception as exc:
        return "analyze_audio failed: " + str(exc)

    if "error" in result:
        return "Analysis error: " + result["error"]

    parts = ["File: " + result.get("file", file_path)]
    if "lufs" in result:
        parts.append("LUFS: " + str(result["lufs"]))
    if "peak_frequency_hz" in result:
        parts.append("Peak: " + str(result["peak_frequency_hz"]) + " Hz")
    if "spectral_centroid_hz" in result:
        parts.append("Centroid: " + str(result["spectral_centroid_hz"]) + " Hz")
    if "energy_by_band" in result:
        bands = result["energy_by_band"]
        band_str = ", ".join(
            k.replace("_", " ") + ": " + str(round(v * 100, 1)) + "%"
            for k, v in bands.items()
        )
        parts.append("Energy bands: " + band_str)
    if "spectrum" in result:
        parts.append("Spectrum: " + str(len(result["spectrum"])) + " points (request spectrum field for raw data)")

    return " | ".join(parts)
'''

# ── profile_audio source (custom Letta tool) ─────────────────────────────────

_PROFILE_AUDIO_SOURCE = '''import json
import os
import urllib.error
import urllib.request


def profile_audio(
    file_path: str,
    no_embeddings: bool = False,
    rhythm: bool = False,
    pitch: bool = False,
) -> str:
    """Run the full ears AudioProfile pipeline on a bounce file.

    Returns a rich AudioProfile: spectral features (centroid, MFCCs, chroma,
    onset strength), full LUFS loudness (integrated + short-term + momentary),
    5-band energy distribution, optional 512-dim DCLAP embedding, and
    optionally beat tracking (rhythm=True) or pitch extraction (pitch=True).

    Compared to analyze_audio():
      - analyze_audio: fast (~5s first call, <0.5s cached), basic FFT stats
      - profile_audio: comprehensive (~15-30s), full AudioProfile for taste/comparison

    Use profile_audio when you need:
      - MFCC or chroma features for timbre comparison
      - DCLAP embedding for semantic similarity (cosine distance between renders)
      - Short-term / momentary LUFS for dynamic range analysis
      - Beat tracking (rhythm=True, requires madmom install)

    Args:
        file_path:     Bare filename in vibe output dir, e.g. "bounce.mp3".
        no_embeddings: Skip DCLAP embedding (faster, no onnxruntime needed).
        rhythm:        Run madmom beat tracking (needs: uv pip install madmom).
        pitch:         Run basic-pitch (needs: uv pip install basic-pitch, slow).

    Returns:
        JSON string with the full AudioProfile, or an error message.
    """
    vibe_url = os.environ.get("VIBE_SERVER_URL", "http://host.docker.internal:8080")
    endpoint = vibe_url + "/profile"

    body = {"file_path": file_path}
    if no_embeddings:
        body["no_embeddings"] = True
    if rhythm:
        body["rhythm"] = True
    if pitch:
        body["pitch"] = True

    payload = json.dumps(body).encode()
    req = urllib.request.Request(
        endpoint,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            result = json.loads(resp.read())
    except urllib.error.URLError as exc:
        return "Could not reach vibe server at " + endpoint + ": " + str(exc)
    except Exception as exc:
        return "profile_audio failed: " + str(exc)

    if "error" in result:
        return "Profile error: " + result["error"]

    # Return compact but readable summary + full JSON for programmatic use
    lines = [
        "AudioProfile: " + result.get("audio_path", file_path).split("/")[-1],
        "  duration:  " + str(round(result.get("duration_seconds", 0), 2)) + "s",
    ]
    ld = result.get("loudness") or {}
    if ld.get("lufs_integrated") is not None:
        lines.append("  LUFS:      " + str(round(ld["lufs_integrated"], 2)))
    if ld.get("lufs_short_term_peak") is not None:
        lines.append("  LUFS-ST:   " + str(round(ld["lufs_short_term_peak"], 2)))
    if ld.get("camelot_key"):
        lines.append("  Key:       " + ld["camelot_key"])
    if ld.get("band_energy"):
        be = ld["band_energy"]
        band_str = ", ".join(k + ": " + str(round(v * 100, 1)) + "%" for k, v in be.items())
        lines.append("  Bands:     " + band_str)
    sp = result.get("spectral") or {}
    if sp.get("spectral_centroid_mean"):
        lines.append("  Centroid:  " + str(round(sp["spectral_centroid_mean"], 1)) + " Hz")
    if sp.get("key"):
        lines.append("  Key (ess): " + sp["key"])
    emb = result.get("embedding") or []
    if emb:
        lines.append("  Embedding: " + str(len(emb)) + "-dim DCLAP (available for similarity)")
    errs = result.get("errors") or []
    if errs:
        lines.append("  Errors:    " + "; ".join(errs))
    lines.append("")
    lines.append("Full profile JSON:")
    lines.append(json.dumps(result, indent=2))
    return "\\n".join(lines)
'''

# ── run_shell_command source (custom Letta tool) ──────────────────────────────

_RUN_SHELL_COMMAND_SOURCE = '''import json
import os
import urllib.error
import urllib.request


def run_shell_command(command: str) -> str:
    """Execute a shell command on the host machine (cwd: hands/).

    Use for: restarting Ableton, launching MCP server, running make targets,
    checking git status, sleeping while Ableton boots, etc.

    Common examples:
      open -a "Ableton Live 12 Standard"   — restart Ableton
      make start-ableton-mcp               — restart MCP bridge
      git diff --name-only HEAD            — check changed files
      sleep 15                             — wait for Ableton to boot

    NOTE: Do NOT use this to restart the vibe server — use restart_vibe_server()
    instead. Stopping vibe via /shell kills the server before the response is sent.

    Args:
        command: Shell command to execute. Runs with cwd = hands/ and timeout = 30s.

    Returns:
        JSON string with stdout, stderr, returncode, or error message.
    """
    vibe_url = os.environ.get("VIBE_SERVER_URL", "http://host.docker.internal:8080")
    endpoint = vibe_url + "/shell"

    payload = json.dumps({"command": command}).encode()
    req = urllib.request.Request(
        endpoint,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=35) as resp:
            result = json.loads(resp.read())
    except urllib.error.URLError as exc:
        return "Could not reach vibe server at " + endpoint + ": " + str(exc)
    except Exception as exc:
        return "run_shell_command failed: " + str(exc)

    if "error" in result:
        return "Shell error: " + result["error"]
    parts = []
    if result.get("stdout"):
        parts.append("stdout: " + result["stdout"].rstrip())
    if result.get("stderr"):
        parts.append("stderr: " + result["stderr"].rstrip())
    parts.append("returncode: " + str(result.get("returncode", "?")))
    return " | ".join(parts) if parts else "ok"
'''

# ── restart_vibe_server source (custom Letta tool) ────────────────────────────

_RESTART_VIBE_SERVER_SOURCE = '''import json
import os
import urllib.error
import urllib.request


def restart_vibe_server() -> str:
    """Restart the vibe server to pick up new code.

    Use this after request_improvement lands changes to hands/src/hands/vibe/
    or any other module loaded by the vibe server. The restart is non-blocking:
    the server shuts down and a fresh process starts in ~3-5 seconds.

    Do NOT use run_shell_command("make start-vibe") for this — that command
    cannot restart a server that is already running, and stopping then starting
    via /shell kills the connection before the response is sent.

    After calling this tool, wait ~5 seconds before issuing another command
    to give the new process time to bind its port.

    Returns:
        Confirmation that the restart was scheduled.
    """
    vibe_url = os.environ.get("VIBE_SERVER_URL", "http://host.docker.internal:8080")
    endpoint = vibe_url + "/restart"

    req = urllib.request.Request(
        endpoint,
        data=b"{}",
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read())
    except urllib.error.URLError as exc:
        return (
            "Could not reach vibe server at " + endpoint + ": " + str(exc) +
            ". Is it running? Try: make -C hands start-vibe"
        )
    except Exception as exc:
        return "restart_vibe_server failed: " + str(exc)

    if result.get("status") == "restarting":
        return (
            "Vibe server is restarting. "
            "Wait 5-10 seconds, then verify it is up by calling a tool like execute() or run_bounce."
        )
    return "Unexpected response: " + json.dumps(result)
'''

# ── harness_rules block content ────────────────────────────────────────────────

_HARNESS_RULES = """## Harness Self-Improvement Rules

You have full access to modify and reload your own codebase. Default posture:
**keep going**. You are an autonomous agent. Stopping to ask permission is the
exception, not the rule. Diagnose, fix, test, iterate — report progress as you go.

### Tools available

- `request_improvement(description, prompt)` — starts a background Claude Agent SDK
  edit session, returns immediately with a job_id
- `check_improvement()` — polls the status of the most recent job
- `restart_vibe_server()` — restarts the vibe server to pick up new code (~5s)
- `analyze_audio(file_path, fields?)` — fast LUFS/spectrum/bands (cached, sub-second after first call)
- `profile_audio(file_path, ...)` — full ears AudioProfile: spectral features, DCLAP embedding, full LUFS dynamics

### How the async flow works

request_improvement returns in under a second. The SDK session runs in the background.
The producer watches live progress in the chat. No timeouts to worry about.

After calling request_improvement:
1. Narrate what you started and why.
2. Wait an appropriate amount of time, then call check_improvement():
   - Simple single-file edits: ~1-2 minutes
   - Multi-file or complex changes: ~3-5 minutes
3. If still "running", wait and poll again. Keep going.
4. IMPORTANT: When the vibe server is restarted as part of an improvement, the
   SSE stream breaks and check_improvement() may briefly return "idle" — this is
   NOT a failure. Verify by actually calling the affected tool (e.g. analyze_audio,
   run_bounce). If the tool works correctly, the improvement landed successfully.

### Default behaviour: keep working

After any tool call or check, your default is to CONTINUE toward the goal.
Only stop to ask the human if:
- You need Letta itself restarted (human-only operation)
- The change is architectural and affects multiple services in a breaking way
- You've iterated 3+ times on the same issue without progress

Otherwise: diagnose → fix → test → iterate autonomously.

### When to use request_improvement

GOOD reasons (act on these without asking):
- A tool you need doesn't exist yet
- You found a bug in one of your tools (run_bounce, analyze_audio, execute, etc.)
- An endpoint returns the wrong format
- A skill or memory block is missing information you keep needing

OK reasons (use judgment, usually fine):
- Adding new endpoints to server.py
- Adding new Letta tools (they auto-register via make setup-tools)
- Improving performance of existing code

Only escalate if the change is truly architectural (e.g. replacing Letta).

### How to write a good improvement prompt

Describe the **problem** with context. Include:
1. Exact symptom ("6.7s response time for /analyze")
2. Expected behaviour ("sub-5s, ideally sub-second for cached files")
3. Which file is affected ("hands/src/hands/vibe/server.py, handle_analyze()")
4. Any relevant observations ("librosa.load is the bottleneck; file is decoded
   twice in the original code")

Be specific. The editor will investigate and fix the root cause.

### analyze_audio vs profile_audio — when to use which

analyze_audio  — fast (~5s first call, <0.5s cached), basic FFT metrics.
                 Use for: quick iteration checks (LUFS, peak freq, energy bands).
  analyze_audio("bounce.mp3", ["lufs"])               # loudness
  analyze_audio("bounce.mp3", ["peak_frequency_hz"])  # pitch verification
  analyze_audio("bounce.mp3", ["energy_by_band"])     # sub vs bass ratio

profile_audio  — comprehensive (~15-30s), full AudioProfile from the ears package.
                 Use for: DCLAP embedding (semantic similarity), MFCCs, chroma,
                 full LUFS dynamics (short-term + momentary), Camelot key.
  profile_audio("bounce.mp3")                         # full profile
  profile_audio("bounce.mp3", no_embeddings=True)     # faster, skip embedding

The ears package lives at agent-sandbox/ears/. It is the long-term audio
perception layer — profile_audio is its current interface from inside Letta.

### Service restart behaviour

The tool auto-detects which services to restart based on changed files:
- hands/src/hands/vibe/ changes → restarts vibe server
- hands/src/hands/ changes → restarts vibe + ableton-mcp
- hands/frontend/ changes → restarts frontend
- hands/scripts/setup_letta_tools.py → re-runs make setup-tools
- .cursor/skills/ changes → no restart needed (read at runtime)

If you need to reload the vibe server without a code change, call
restart_vibe_server() directly. Wait ~5-10s after calling it.

Letta is NEVER restarted automatically. If a change requires a Letta restart,
tell the human and ask them to run: make -C hands stop-letta start-letta

### After check_improvement confirms completion

1. If services were restarted, test the change immediately with the affected tool.
2. If it didn't work as expected, diagnose with execute() first, then iterate.
3. Don't loop more than 3 attempts on the same issue — escalate with full diagnosis.

### Ableton MIDI note editing warning

When execute() modifies MIDI notes, Ableton may show a dialog asking "Should the
script proceed?" — the human must click "Proceed". Warn them before MIDI writes.
"""

# ── HTTP helpers ───────────────────────────────────────────────────────────────

def _request(method: str, url: str, body: dict | None = None, timeout: int = 30) -> object:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"} if data else {},
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        try:
            detail = json.loads(exc.read())
        except Exception:
            detail = str(exc)
        raise RuntimeError(f"HTTP {exc.code} from {url}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Could not reach {url}: {exc}") from exc


# ── Step 1: run_bounce custom tool ────────────────────────────────────────────

def upsert_run_bounce(base_url: str) -> str:
    tools = _request("GET", f"{base_url}/v1/tools/")
    existing = [t for t in tools if t.get("name") == "run_bounce"]
    if existing:
        _request("PATCH", f"{base_url}/v1/tools/{existing[0]['id']}", {
            "source_code": _RUN_BOUNCE_SOURCE,
            "description": "Bounce the current Ableton Live session to audio via the vibe server",
        })
        print(f"  ✓  run_bounce updated ({existing[0]['id']})")
        return existing[0]["id"]
    tool = _request("POST", f"{base_url}/v1/tools/", {
        "source_code": _RUN_BOUNCE_SOURCE,
        "source_type": "python",
        "description": "Bounce the current Ableton Live session to audio via the vibe server",
    })
    print(f"  ✓  run_bounce created ({tool['id']})")
    return tool["id"]


# ── Step 1b: request_improvement custom tool ──────────────────────────────────

def upsert_request_improvement(base_url: str) -> str:
    tools = _request("GET", f"{base_url}/v1/tools/")
    existing = [t for t in tools if t.get("name") == "request_improvement"]
    payload = {
        "source_code": _REQUEST_IMPROVEMENT_SOURCE,
        "description": "Request a self-improvement to the agent harness via the Claude Agent SDK",
    }
    if existing:
        _request("PATCH", f"{base_url}/v1/tools/{existing[0]['id']}", payload)
        print(f"  ✓  request_improvement updated ({existing[0]['id']})")
        return existing[0]["id"]
    payload["source_type"] = "python"
    tool = _request("POST", f"{base_url}/v1/tools/", payload)
    print(f"  ✓  request_improvement created ({tool['id']})")
    return tool["id"]


# ── Step 1b-alt: analyze_audio custom tool ───────────────────────────────────

def upsert_analyze_audio(base_url: str) -> str:
    tools = _request("GET", f"{base_url}/v1/tools/")
    existing = [t for t in tools if t.get("name") == "analyze_audio"]
    payload = {
        "source_code": _ANALYZE_AUDIO_SOURCE,
        "description": (
            "Analyze spectral characteristics of a bounced audio file "
            "(LUFS, peak frequency, energy bands, spectrum). "
            "Supports per-field requests — cached audio makes repeated calls sub-second."
        ),
    }
    if existing:
        _request("PATCH", f"{base_url}/v1/tools/{existing[0]['id']}", payload)
        print(f"  ✓  analyze_audio updated ({existing[0]['id']})")
        return existing[0]["id"]
    payload["source_type"] = "python"
    tool = _request("POST", f"{base_url}/v1/tools/", payload)
    print(f"  ✓  analyze_audio created ({tool['id']})")
    return tool["id"]


# ── Step 1c: profile_audio custom tool ───────────────────────────────────────

def upsert_profile_audio(base_url: str) -> str:
    tools = _request("GET", f"{base_url}/v1/tools/")
    existing = [t for t in tools if t.get("name") == "profile_audio"]
    payload = {
        "source_code": _PROFILE_AUDIO_SOURCE,
        "description": (
            "Run the full ears AudioProfile pipeline on a bounce file: "
            "spectral features, full LUFS, 5-band energy, DCLAP embedding. "
            "Heavier than analyze_audio (~15-30s) but returns the complete profile."
        ),
    }
    if existing:
        _request("PATCH", f"{base_url}/v1/tools/{existing[0]['id']}", payload)
        print(f"  ✓  profile_audio updated ({existing[0]['id']})")
        return existing[0]["id"]
    payload["source_type"] = "python"
    tool = _request("POST", f"{base_url}/v1/tools/", payload)
    print(f"  ✓  profile_audio created ({tool['id']})")
    return tool["id"]


# ── Step 1d: run_shell_command custom tool ────────────────────────────────────

def upsert_run_shell_command(base_url: str) -> str:
    tools = _request("GET", f"{base_url}/v1/tools/")
    existing = [t for t in tools if t.get("name") == "run_shell_command"]
    payload = {
        "source_code": _RUN_SHELL_COMMAND_SOURCE,
        "description": "Execute a shell command on the host machine via the vibe server (cwd: hands/)",
    }
    if existing:
        _request("PATCH", f"{base_url}/v1/tools/{existing[0]['id']}", payload)
        print(f"  ✓  run_shell_command updated ({existing[0]['id']})")
        return existing[0]["id"]
    payload["source_type"] = "python"
    tool = _request("POST", f"{base_url}/v1/tools/", payload)
    print(f"  ✓  run_shell_command created ({tool['id']})")
    return tool["id"]


# ── Step 1d: check_improvement custom tool ────────────────────────────────────

def upsert_check_improvement(base_url: str) -> str:
    tools = _request("GET", f"{base_url}/v1/tools/")
    existing = [t for t in tools if t.get("name") == "check_improvement"]
    payload = {
        "source_code": _CHECK_IMPROVEMENT_SOURCE,
        "description": "Check the status of the most recent self-improvement job",
    }
    if existing:
        _request("PATCH", f"{base_url}/v1/tools/{existing[0]['id']}", payload)
        print(f"  ✓  check_improvement updated ({existing[0]['id']})")
        return existing[0]["id"]
    payload["source_type"] = "python"
    tool = _request("POST", f"{base_url}/v1/tools/", payload)
    print(f"  ✓  check_improvement created ({tool['id']})")
    return tool["id"]


def upsert_restart_vibe_server(base_url: str) -> str:
    tools = _request("GET", f"{base_url}/v1/tools/")
    existing = [t for t in tools if t.get("name") == "restart_vibe_server"]
    payload = {
        "source_code": _RESTART_VIBE_SERVER_SOURCE,
        "description": "Restart the vibe server to load updated code (~5s downtime)",
    }
    if existing:
        _request("PATCH", f"{base_url}/v1/tools/{existing[0]['id']}", payload)
        print(f"  ✓  restart_vibe_server updated ({existing[0]['id']})")
        return existing[0]["id"]
    payload["source_type"] = "python"
    tool = _request("POST", f"{base_url}/v1/tools/", payload)
    print(f"  ✓  restart_vibe_server created ({tool['id']})")
    return tool["id"]


# ── Step 2: MCP server registration ──────────────────────────────────────────

def register_mcp_server(base_url: str, bridge_port: int) -> None:
    """Register (or update) the ableton-live MCP server config."""
    server_url = f"http://host.docker.internal:{bridge_port}/mcp"
    # GET returns a dict keyed by server_name
    existing = _request("GET", f"{base_url}/v1/tools/mcp/servers")
    registered = isinstance(existing, dict) and "ableton-live" in existing

    if registered:
        _request("PATCH", f"{base_url}/v1/tools/mcp/servers/ableton-live", {
            "server_url": server_url,
        })
        print(f"  ✓  ableton-live MCP server updated → {server_url}")
    else:
        _request("PUT", f"{base_url}/v1/tools/mcp/servers", {
            "server_name": "ableton-live",
            "type": "streamable_http",
            "server_url": server_url,
        })
        print(f"  ✓  ableton-live MCP server registered → {server_url}")


# ── Step 3: Create Letta tools from MCP tools ─────────────────────────────────

def upsert_mcp_tools(base_url: str) -> list[str]:
    """Create or verify the 3 MCP tools (execute, api, search_api). Returns tool IDs."""
    try:
        mcp_tools = _request("GET", f"{base_url}/v1/tools/mcp/servers/ableton-live/tools")
    except RuntimeError as exc:
        print(f"  ✗  Could not list MCP tools: {exc}")
        print("     Is the bridge server running? make start-ableton-mcp")
        return []

    all_letta_tools = _request("GET", f"{base_url}/v1/tools/")
    existing_by_name = {t["name"]: t["id"] for t in all_letta_tools}

    tool_ids = []
    for mcp_tool in mcp_tools:
        name = mcp_tool["name"]
        if name in existing_by_name:
            print(f"  ·  {name} already exists ({existing_by_name[name]})")
            tool_ids.append(existing_by_name[name])
        else:
            tool = _request("POST", f"{base_url}/v1/tools/mcp/servers/ableton-live/{name}")
            print(f"  ✓  {name} created ({tool['id']})")
            tool_ids.append(tool["id"])

    return tool_ids


# ── Step 4: Attach all tools to agents ───────────────────────────────────────

def attach_tools_to_agents(base_url: str, tool_ids: list[str], agent_id: str | None) -> None:
    if agent_id:
        agents = [_request("GET", f"{base_url}/v1/agents/{agent_id}")]
    else:
        all_agents = _request("GET", f"{base_url}/v1/agents/")
        vibe = [a for a in all_agents if a.get("name", "").lower() in ("tms", "vibe")]
        agents = vibe or all_agents

    if not agents:
        print("  ✗  No agents found.")
        return

    for agent in agents:
        aid = agent["id"]
        aname = agent.get("name", aid)
        current_tool_ids = {t["id"] for t in agent.get("tools", [])}
        current_names = {t["name"] for t in agent.get("tools", [])}
        print(f"\n  Agent '{aname}' ({aid})")

        for tid in tool_ids:
            if tid in current_tool_ids:
                tname = next((t["name"] for t in agent.get("tools", []) if t["id"] == tid), tid)
                print(f"    ·  already attached: {tname}")
                continue
            try:
                updated = _request("PATCH", f"{base_url}/v1/agents/{aid}/tools/attach/{tid}")
                # Find the name of the newly attached tool
                name = next(
                    (t["name"] for t in updated.get("tools", []) if t["id"] == tid), tid
                )
                print(f"    ✓  attached: {name}")
            except RuntimeError as exc:
                if "already" in str(exc).lower():
                    print(f"    ·  already attached: {tid}")
                else:
                    print(f"    ✗  failed {tid}: {exc}")


# ── Step 5: ableton_rules core memory block ───────────────────────────────────

_WORKFLOW_RULES = """
---

## Auto-Bounce Rule (Non-Negotiable)

After ANY set of execute() calls that modify the Ableton session — adding/removing
tracks, changing parameters, loading devices, writing MIDI notes, adjusting tempo,
setting clips, etc. — ALWAYS call run_bounce() as the final step.

Do NOT auto-bounce for:
- Read-only queries (getting track names, tempo, clip contents, etc.)
- api() or search_api() calls
- A bounce that just failed (don't loop)

The producer needs to hear the result of every change immediately. Never leave a
modification unheard.

---

## Starting the Stack

If run_bounce() or execute() reports a connection error, the relevant server is not
running. Start them from the hands repo:

  # Full stack (recommended):
  cd /Users/anthonybecker/Desktop/agent-sandbox/hands && make start

  # Individual services:
  make start-letta         # Letta server (port 8283)
  make start-vibe          # Vibe bounce server (port 8080) — required for run_bounce
  make start-ableton-mcp   # MCP bridge (port 9010)  — required for execute/api/search_api

  # Register tools after starting (idempotent):
  make setup-tools

Ableton Live itself must also be open with the AbletonLiveMCP Remote Script loaded.
"""


def _build_rules_block_value() -> str:
    """Extract Sections 0 and 1 from SKILL.md, then append workflow rules."""
    if not _SKILL_MD.exists():
        return "(ableton-guide SKILL.md not found — run from the hands repo root)" + _WORKFLOW_RULES
    text = _SKILL_MD.read_text()
    # Keep everything from the first heading up to (but not including) Section 2
    start = text.find("## 0. Connection")
    end = text.find("\n## 2.")
    if start == -1:
        base = text[:4000]
    else:
        base = text[start:end] if end != -1 else text[start:]
    return base.strip() + _WORKFLOW_RULES


def upsert_ableton_rules_block(base_url: str, agent_id: str) -> str | None:
    """Create or update the ableton_rules core memory block and attach it."""
    value = _build_rules_block_value()

    # Check if the block already exists on this agent
    blocks = _request("GET", f"{base_url}/v1/agents/{agent_id}/core-memory/blocks")
    existing = next((b for b in blocks if b.get("label") == "ableton_rules"), None)

    if existing:
        _request(
            "PATCH",
            f"{base_url}/v1/agents/{agent_id}/core-memory/blocks/ableton_rules",
            {"value": value},
        )
        print(f"  ✓  ableton_rules block updated ({len(value)} chars)")
        return existing["id"]

    # Create a new block and attach it
    block = _request("POST", f"{base_url}/v1/blocks/", {
        "label": "ableton_rules",
        "value": value,
        "description": (
            "Ableton Live MCP crash avoidance rules and connection guide. "
            "Consult this before every execute() call."
        ),
    })
    block_id = block["id"]
    _request("PATCH", f"{base_url}/v1/agents/{agent_id}/core-memory/blocks/attach/{block_id}")
    print(f"  ✓  ableton_rules block created and attached ({len(value)} chars)")
    return block_id


# ── Step 5b: harness_rules core memory block ──────────────────────────────────

def upsert_harness_rules_block(base_url: str, agent_id: str) -> str | None:
    """Create or update the harness_rules core memory block and attach it."""
    blocks = _request("GET", f"{base_url}/v1/agents/{agent_id}/core-memory/blocks")
    existing = next((b for b in blocks if b.get("label") == "harness_rules"), None)

    if existing:
        _request(
            "PATCH",
            f"{base_url}/v1/agents/{agent_id}/core-memory/blocks/harness_rules",
            {"value": _HARNESS_RULES},
        )
        print(f"  ✓  harness_rules block updated ({len(_HARNESS_RULES)} chars)")
        return existing["id"]

    block = _request("POST", f"{base_url}/v1/blocks/", {
        "label": "harness_rules",
        "value": _HARNESS_RULES,
        "description": (
            "Self-improvement guide: when and how to use request_improvement, "
            "service restart behaviour, and safety constraints."
        ),
    })
    block_id = block["id"]
    _request("PATCH", f"{base_url}/v1/agents/{agent_id}/core-memory/blocks/attach/{block_id}")
    print(f"  ✓  harness_rules block created and attached ({len(_HARNESS_RULES)} chars)")
    return block_id


# ── Step 6: ableton-guide knowledge source ────────────────────────────────────

def _multipart_upload(url: str, files: list[tuple[str, str, str]]) -> dict:
    """POST a multipart/form-data request with multiple files.

    files: list of (field_name, filename, content) tuples.
    """
    boundary = "----LettaUploadBoundary7x9k"
    body_parts = []
    for field, fname, content in files:
        body_parts.append(
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="{field}"; filename="{fname}"\r\n'
            f"Content-Type: text/markdown\r\n\r\n"
            f"{content}\r\n"
        )
    body_parts.append(f"--{boundary}--\r\n")
    body = "".join(body_parts).encode("utf-8")

    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        try:
            detail = json.loads(exc.read())
        except Exception:
            detail = str(exc)
        raise RuntimeError(f"HTTP {exc.code}: {detail}") from exc


def upsert_ableton_guide_source(base_url: str, agent_id: str) -> str | None:
    """Create (or verify) the ableton-guide source and attach it to the agent."""
    if not _SKILL_MD.exists():
        print(f"  ✗  SKILL.md not found at {_SKILL_MD} — skipping source upload")
        return None

    # Check if source already exists
    all_sources = _request("GET", f"{base_url}/v1/sources/")
    existing = next((s for s in all_sources if s.get("name") == "ableton-guide"), None)

    if existing:
        source_id = existing["id"]
        print(f"  ·  source ableton-guide already exists ({source_id})")
    else:
        source = _request("POST", f"{base_url}/v1/sources/", {
            "name": "ableton-guide",
            "description": (
                "Full Ableton Live MCP agent guide: crash avoidance, LOM idioms, "
                "browser paths, automation, arrangement view, drum rack operations, "
                "sandbox limits, and available built-in devices."
            ),
            "instructions": (
                "Search this source when writing execute() code, troubleshooting LOM "
                "errors, navigating the browser, working with devices/parameters, or "
                "writing automation envelopes."
            ),
            "embedding": "google_ai/gemini-embedding-001",
        })
        source_id = source["id"]
        print(f"  ✓  source ableton-guide created ({source_id})")

        # Upload files into the source
        files_to_upload = [(_SKILL_MD, "ableton-guide.md")]
        if _DEVICES_MD.exists():
            files_to_upload.append((_DEVICES_MD, "available-devices.md"))

        for fpath, fname in files_to_upload:
            content = fpath.read_text()
            try:
                _multipart_upload(
                    f"{base_url}/v1/sources/{source_id}/upload",
                    [("file", fname, content)],
                )
                print(f"  ✓  uploaded {fname} ({len(content)} chars)")
            except RuntimeError as exc:
                print(f"  ✗  upload failed for {fname}: {exc}")

    # Attach source to agent (idempotent — 409 or 4xx means already attached)
    agent_sources = _request("GET", f"{base_url}/v1/agents/{agent_id}/sources")
    attached_ids = {s["id"] for s in agent_sources}
    if source_id in attached_ids:
        print(f"  ·  source already attached to agent")
    else:
        try:
            _request("PATCH", f"{base_url}/v1/agents/{agent_id}/sources/attach/{source_id}")
            print(f"  ✓  source attached to agent")
        except RuntimeError as exc:
            if "already" in str(exc).lower() or "409" in str(exc):
                print(f"  ·  source already attached to agent")
            else:
                print(f"  ✗  attach failed: {exc}")

    return source_id


# ── Main ───────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--agent-id", default=None, help="Specific Letta agent ID.")
    parser.add_argument(
        "--base-url",
        default=os.environ.get("LETTA_BASE_URL", "http://localhost:8283"),
        help="Letta server URL (default: http://localhost:8283).",
    )
    parser.add_argument(
        "--bridge-port",
        type=int,
        default=int(os.environ.get("ABLETON_MCP_BRIDGE_PORT", "9010")),
        help="Port the Ableton MCP bridge is running on (default: 9010).",
    )
    args = parser.parse_args()

    print(f"\nConnecting to Letta at {args.base_url} …")
    try:
        health = _request("GET", f"{args.base_url}/v1/health/")
        print(f"  ✓  Letta {health.get('version', '?')} — {health.get('status', '?')}\n")
    except RuntimeError as exc:
        print(f"  ✗  {exc}")
        print("     Is Letta running? make start-letta")
        sys.exit(1)

    print("── Step 1: run_bounce custom tool ──────────────────────")
    bounce_id = upsert_run_bounce(args.base_url)

    print("\n── Step 1b: request_improvement custom tool ─────────────")
    improve_id = upsert_request_improvement(args.base_url)

    print("\n── Step 1b-alt: analyze_audio custom tool ───────────────")
    analyze_id = upsert_analyze_audio(args.base_url)

    print("\n── Step 1b-alt2: profile_audio custom tool ──────────────")
    profile_id = upsert_profile_audio(args.base_url)

    print("\n── Step 1c: run_shell_command custom tool ───────────────")
    shell_id = upsert_run_shell_command(args.base_url)

    print("\n── Step 1d: check_improvement custom tool ───────────────")
    check_id = upsert_check_improvement(args.base_url)

    print("\n── Step 1e: restart_vibe_server custom tool ─────────────")
    restart_id = upsert_restart_vibe_server(args.base_url)

    print("\n── Step 2: Ableton MCP server registration ─────────────")
    register_mcp_server(args.base_url, args.bridge_port)

    print("\n── Step 3: MCP tools (execute / api / search_api) ──────")
    mcp_ids = upsert_mcp_tools(args.base_url)

    all_ids = (
        ([bounce_id] if bounce_id else [])
        + ([improve_id] if improve_id else [])
        + ([analyze_id] if analyze_id else [])
        + ([profile_id] if profile_id else [])
        + ([shell_id] if shell_id else [])
        + ([check_id] if check_id else [])
        + ([restart_id] if restart_id else [])
        + mcp_ids
    )

    print("\n── Step 4: Attach all tools to agent(s) ────────────────")
    attach_tools_to_agents(args.base_url, all_ids, args.agent_id)

    # Resolve the target agent ID for knowledge injection (first Vibe agent or first agent)
    if args.agent_id:
        target_agent_id = args.agent_id
    else:
        all_agents = _request("GET", f"{args.base_url}/v1/agents/")
        vibe = [a for a in all_agents if a.get("name", "").lower() in ("tms", "vibe")]
        target = (vibe or all_agents)[0] if (vibe or all_agents) else None
        target_agent_id = target["id"] if target else None

    if target_agent_id:
        print("\n── Step 5: ableton_rules core memory block ─────────────")
        upsert_ableton_rules_block(args.base_url, target_agent_id)

        print("\n── Step 5b: harness_rules core memory block ─────────────")
        upsert_harness_rules_block(args.base_url, target_agent_id)

        print("\n── Step 6: ableton-guide knowledge source ───────────────")
        upsert_ableton_guide_source(args.base_url, target_agent_id)
    else:
        print("\n  ✗  No agent found — skipping knowledge injection")

    print(
        "\n✓  Done. The Vibe agent now has:\n"
        "   execute             — run Python code against the Ableton LOM\n"
        "   api                 — browse the Live API reference\n"
        "   search_api          — search the Live API reference\n"
        "   run_bounce          — bounce Ableton audio to a file\n"
        "   analyze_audio       — analyze LUFS/spectrum of a bounce (cached, per-field)\n"
        "   profile_audio       — full ears AudioProfile: spectral + DCLAP embedding\n"
        "   request_improvement — start async harness improvement (returns immediately)\n"
        "   check_improvement   — poll status of the most recent improvement job\n"
        "   run_shell_command   — execute shell commands on the host (cwd: hands/)\n"
        "   [block] ableton_rules  — crash rules always in context\n"
        "   [block] harness_rules  — self-improvement guide always in context\n"
        "   [source] ableton-guide — full LOM guide, semantically searchable\n\n"
        "Make sure both servers are running before use:\n"
        "   make start-vibe          (bounce + self-improve + analyze, port 8080)\n"
        "   make start-ableton-mcp   (execute/api/search_api, port 9010)\n"
    )


if __name__ == "__main__":
    main()
