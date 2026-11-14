"""A stand-in for `gemini --acp` (JSON-RPC 2.0 on stdio, one object per line) for test_gemini.py.

It writes every message it receives to $FAKE_ACP_LOG. What a prompt does depends on its text:
    "edit ..."  a tool call that asks permission first; allowed: an edit (diff) and "Done."; declined: "Skipped."
    "slow ..."  text in pieces until it is cancelled (stopReason "cancelled")
    otherwise   a thought, then "echo: <text> (<n> images)"
"""

import json
import os
import sys
import threading
import time
import uuid

out_lock = threading.Lock()
pending: dict = {}
cancelled: set = set()
modes: dict = {}
log_path = os.environ.get("FAKE_ACP_LOG")
next_id = [1000]


def send(msg):
    with out_lock:
        sys.stdout.write(json.dumps(msg) + "\n")
        sys.stdout.flush()


def log(msg):
    if log_path:
        with open(log_path, "a") as f:
            f.write(json.dumps(msg) + "\n")


def update(sid, u):
    send({"jsonrpc": "2.0", "method": "session/update", "params": {"sessionId": sid, "update": u}})


def text(sid, t, kind="agent_message_chunk"):
    update(sid, {"sessionUpdate": kind, "content": {"type": "text", "text": t}})


def ask(sid, tool):
    next_id[0] += 1
    rid = next_id[0]
    ev = threading.Event()
    pending[rid] = [ev, None]
    send({"jsonrpc": "2.0", "id": rid, "method": "session/request_permission", "params": {
        "sessionId": sid, "toolCall": tool, "options": [
            {"optionId": "proceed_once", "name": "Allow", "kind": "allow_once"},
            {"optionId": "proceed_always", "name": "Allow always", "kind": "allow_always"},
            {"optionId": "cancel", "name": "Reject", "kind": "reject_once"}]}})
    ev.wait(30)
    return pending.pop(rid)[1]


def prompt(msg):
    p = msg["params"]
    sid = p["sessionId"]
    words = "".join(b.get("text", "") for b in p["prompt"] if b["type"] == "text")
    images = sum(1 for b in p["prompt"] if b["type"] == "image")
    stop = "end_turn"
    if words.startswith("edit"):
        tool = {"toolCallId": "edit-1", "title": "Edit README.md", "kind": "edit", "status": "pending",
                "locations": [{"path": "/repo/README.md"}],
                "content": [{"type": "diff", "path": "/repo/README.md", "oldText": "a\nb\n", "newText": "a\nc\n"}]}
        update(sid, {"sessionUpdate": "tool_call", **tool})
        if modes.get(sid) == "yolo":
            outcome = {"outcome": "selected", "optionId": "proceed_once"}
        else:
            res = ask(sid, tool) or {}
            outcome = (res.get("result") or {}).get("outcome") or {}
        if outcome.get("optionId") == "proceed_always":
            modes[sid] = "autoEdit"
            text(sid, "[MODE_UPDATE] autoEdit")
        if outcome.get("optionId", "").startswith("proceed"):
            update(sid, {"sessionUpdate": "tool_call_update", "toolCallId": "edit-1", "status": "completed"})
            text(sid, "Done.")
        else:
            update(sid, {"sessionUpdate": "tool_call_update", "toolCallId": "edit-1", "status": "failed"})
            text(sid, "Skipped.")
            if outcome.get("outcome") == "cancelled":
                stop = "cancelled"
    elif words.startswith("slow"):
        for k in range(200):
            if sid in cancelled:
                cancelled.discard(sid)
                stop = "cancelled"
                break
            text(sid, f"{k} ")
            time.sleep(0.02)
    else:
        text(sid, "Thinking it over.", "agent_thought_chunk")
        text(sid, "echo: ")
        text(sid, f"{words} ({images} images)")
    send({"jsonrpc": "2.0", "id": msg["id"], "result": {
        "stopReason": stop, "usage": {"inputTokens": 1000, "cachedReadTokens": 400, "outputTokens": 100, "thoughtTokens": 50},
        "_meta": {"quota": {"model_usage": [{"model": "gemini-flash-latest"}]}}}})


def main():
    for line in sys.stdin:
        msg = json.loads(line)
        log(msg)
        m, mid = msg.get("method"), msg.get("id")
        if m is None:
            if mid in pending:
                pending[mid][1] = msg
                pending[mid][0].set()
            continue
        if m == "initialize":
            send({"jsonrpc": "2.0", "id": mid, "result": {"protocolVersion": 1, "agentCapabilities": {"loadSession": True}}})
        elif m == "session/new":
            sid = str(uuid.uuid4())
            send({"jsonrpc": "2.0", "id": mid, "result": {
                "sessionId": sid,
                "models": {"availableModels": [{"modelId": "gemini-flash-latest"}, {"modelId": "gemini-3.1-pro-preview"}],
                           "currentModelId": "gemini-flash-latest"},
                "modes": {"availableModes": [{"id": x} for x in ("default", "autoEdit", "yolo", "plan")], "currentModeId": "default"}}})
        elif m == "session/load":
            text(msg["params"]["sessionId"], "(replayed history)")
            send({"jsonrpc": "2.0", "id": mid, "result": {}})
        elif m == "session/set_mode":
            modes[msg["params"]["sessionId"]] = msg["params"]["modeId"]
            send({"jsonrpc": "2.0", "id": mid, "result": {}})
        elif m == "session/set_model":
            send({"jsonrpc": "2.0", "id": mid, "result": {}})
        elif m == "session/prompt":
            threading.Thread(target=prompt, args=(msg,), daemon=True).start()
        elif m == "session/cancel":
            cancelled.add(msg["params"]["sessionId"])
        else:
            send({"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"no {m}"}})


if __name__ == "__main__":
    main()
