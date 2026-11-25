"""A stand-in for `claude -p --output-format stream-json`, for the Ask tests. It calls no model.

It logs its arguments, its stdin and the variables it was given to $FAKE_CLAUDE_LOG, then acts on the prompt:
    "tool ..."      a tool call and its result, then an answer
    "mcp ..."       starts the MCP server it was given (--mcp-config) and calls read_state on it, for real
    "auth ..."      says what the real CLI says when it is not signed in
    "slow ..."      text in pieces until it is stopped
    otherwise       the prompt echoed
"""

import json
import os
import subprocess
import sys
import time


def out(obj):
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


def delta(text):
    out(
        {
            "type": "stream_event",
            "event": {"type": "content_block_delta", "delta": {"type": "text_delta", "text": text}},
        }
    )


def mcp_call(config):
    server = json.loads(config)["mcpServers"]["zpkt"]
    proc = subprocess.Popen(
        [server["command"], *server["args"]], env={**os.environ, **server["env"]},
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True,
    )  # fmt: skip

    def ask(msg):
        proc.stdin.write(json.dumps(msg) + "\n")
        proc.stdin.flush()
        return json.loads(proc.stdout.readline())

    ask({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
    names = [t["name"] for t in ask({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})["result"]["tools"]]
    reply = ask({"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "read_state", "arguments": {}}})
    proc.stdin.close()
    proc.wait(timeout=10)
    return names, reply["result"]


args = sys.argv[1:]
prompt = sys.stdin.read()
log = os.environ.get("FAKE_CLAUDE_LOG")
if log:
    with open(log, "a") as f:
        f.write(
            json.dumps(
                {
                    "args": args,
                    "prompt": prompt,
                    "env": {k: v for k, v in os.environ.items() if k.startswith(("CLAUDE", "ZPKT"))},
                }
            )
            + "\n"
        )

out({"type": "system", "subtype": "init", "session_id": "x", "model": "fake"})
if prompt.startswith("auth"):
    out(
        {
            "type": "assistant",
            "message": {"id": "m", "content": [{"type": "text", "text": "Failed to authenticate. Please run /login"}]},
        }
    )
    sys.exit(1)
if prompt.startswith("slow"):
    for i in range(500):
        delta(f"{i} ")
        time.sleep(0.02)
elif prompt.startswith("tool"):
    out(
        {
            "type": "assistant",
            "message": {
                "id": "m1",
                "content": [{"type": "tool_use", "id": "t1", "name": "Read", "input": {"file_path": "a.txt"}}],
            },
        }
    )
    out(
        {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "t1", "content": "file text"}]}}
    )
    delta("read it")
elif prompt.startswith("mcp"):
    names, result = mcp_call(args[args.index("--mcp-config") + 1])
    out(
        {
            "type": "assistant",
            "message": {
                "id": "m1",
                "content": [{"type": "tool_use", "id": "t1", "name": "mcp__zpkt__read_state", "input": {}}],
            },
        }
    )
    out(
        {
            "type": "user",
            "message": {
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "t1",
                        "content": json.dumps(result),
                        "is_error": result["isError"],
                    }
                ]
            },
        }
    )
    delta("tools: " + ",".join(names))
else:
    delta("echo: " + prompt)
out(
    {
        "type": "result",
        "is_error": False,
        "duration_ms": 3,
        "usage": {"input_tokens": 3, "output_tokens": 2},
        "total_cost_usd": 0.01,
    }
)
