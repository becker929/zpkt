"""Ask: the chat with an agent, inside the app.

Zpkt web (Node, :8789) was a chat page over Claude Code and Gemini CLI. This is its port: the sessions and their
events (store.py), the engines (claude.py, gemini.py), the work view's page, notes, the failure budget and the
tools an agent may call. The tools are app commands (tools.py) and nothing else: an agent never reaches zpkt.live.

How it fits: `zpkt.app.adapters.agents` makes an `Ask`, registers the agent commands on the bus and mounts the
routes (routes.py) on the web server under /app/ask/. Zpkt web on :8789 is untouched and keeps working.
"""
