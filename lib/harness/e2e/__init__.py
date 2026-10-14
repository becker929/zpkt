"""studio, end to end, as Anthony uses it: a reproducible agentic test (.claude/skills/studio-e2e).

A run starts the real studio (server, Kokoro and Parakeet, the real Claude session, the Haiku narrator) and drives
its page in an iPhone-sized WebKit as a virtual user who talks to it: each line is spoken by Kokoro into the page's
mic once the page says the mic is listening, and the user taps the cards, switches apps and types like Anthony
does. Everything is recorded (the socket both ways, what the speakers played, when the mic was open, the chat,
the turn timings, screenshots), every run is held to the same rules (checks.py), and the run's folder keeps the
evidence and a report.

    cd lib/harness && uv run --extra dev python -m e2e                # the whole scenario, ~10 min
    uv run --extra dev python -m e2e --only slider,background         # some of its parts
"""
