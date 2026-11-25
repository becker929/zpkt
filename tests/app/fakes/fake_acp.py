"""A stand-in for `gemini --acp` (JSON-RPC 2.0 on stdio, one object per line), for the Ask tests. No model.

It logs every message it gets to $FAKE_ACP_LOG. What a prompt does depends on its text:
    "edit ..."   a tool call that asks permission first; allowed: it completes and says "Done."; declined: "Skipped."
    "slow ..."   text in pieces until cancelled (stopReason "cancelled")
    otherwise    "echo: <text>"
"""

import json
import os
import sys
import threading
import time

out_lock = threading.Lock()
answers: dict = {}
cancelled: set = set()
log_path = os.environ.get("FAKE_ACP_LOG")
sessions = [0]


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


def text(sid, t):
    update(sid, {"sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": t}})


def prompt(msg):
    sid = msg["params"]["sessionId"]
    words = "".join(b.get("text", "") for b in msg["params"]["prompt"] if b["type"] == "text")
    stop = "end_turn"
    if "edit" in words:
        tool = {"toolCallId": "e1", "title": "Edit README.md", "kind": "edit", "status": "pending", "locations": [{"path": "/r/README.md"}],
                "content": [{"type": "diff", "path": "/r/README.md", "oldText": "a", "newText": "b"}]}  # fmt: skip
        update(sid, {"sessionUpdate": "tool_call", **tool})
        ev = threading.Event()
        answers["ev"] = ev
        send({"jsonrpc": "2.0", "id": 900, "method": "session/request_permission", "params": {"sessionId": sid, "toolCall": tool,
              "options": [{"optionId": "proceed_once", "name": "Allow", "kind": "allow_once"}, {"optionId": "cancel", "name": "Reject", "kind": "reject_once"}]}})  # fmt: skip
        ev.wait(20)
        outcome = answers.get("outcome", {})
        if outcome.get("optionId") == "proceed_once":
            update(
                sid,
                {
                    "sessionUpdate": "tool_call_update",
                    "toolCallId": "e1",
                    "status": "completed",
                    "content": [{"type": "diff", "path": "/r/README.md", "oldText": "a", "newText": "b"}],
                },
            )
            text(sid, "Done.")
        else:
            update(sid, {"sessionUpdate": "tool_call_update", "toolCallId": "e1", "status": "failed"})
            text(sid, "Skipped.")
    elif "slow" in words:
        for k in range(300):
            if sid in cancelled:
                stop = "cancelled"
                break
            text(sid, f"{k} ")
            time.sleep(0.02)
    else:
        text(sid, "echo: " + words)
    send({"jsonrpc": "2.0", "id": msg["id"], "result": {"stopReason": stop,
          "usage": {"inputTokens": 1000, "cachedReadTokens": 400, "outputTokens": 100, "thoughtTokens": 50},
          "_meta": {"quota": {"model_usage": [{"model": "gemini-flash-latest"}]}}}})  # fmt: skip


def handle(msg):
    method = msg.get("method")
    if "id" in msg and method is None:  # the answer to our permission request
        answers["outcome"] = (msg.get("result") or {}).get("outcome") or {}
        answers["ev"].set()
    elif method == "initialize":
        send({"jsonrpc": "2.0", "id": msg["id"], "result": {"protocolVersion": 1}})
    elif method == "session/new":
        sessions[0] += 1
        send({"jsonrpc": "2.0", "id": msg["id"], "result": {"sessionId": f"acp-{os.getpid()}-{sessions[0]}"}})
    elif method in ("session/load", "session/set_model", "session/set_mode"):
        send({"jsonrpc": "2.0", "id": msg["id"], "result": {}})
    elif method == "session/prompt":
        threading.Thread(target=prompt, args=(msg,), daemon=True).start()
    elif method == "session/cancel":
        cancelled.add(msg["params"]["sessionId"])
        if "ev" in answers:
            answers["outcome"] = {"outcome": "cancelled"}
            answers["ev"].set()


for line in sys.stdin:
    msg = json.loads(line)
    log(msg)
    handle(msg)
