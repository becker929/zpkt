"""Live's GUI steps without keystrokes: browser loads, parameters in display units, the mixer, Save As and the
export. They are hands.live.ops (SH001's liveops.py, moved into hands), pointed at the booth's client and folders.

hands stops with Guard (and older steps with sys.exit("STOP: ...")); here that becomes Stop, so the runner can hold
the job instead of exiting.
"""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

# Exports are staged in SH001's folder (~/_agent_scratch/rummage): the Save panel's Where popup reaches it, and it
# could not reach BOOTH_HOME (first watched run, 2026-11-01). Each file then moves on to the job.
STAGING = Path("~/_agent_scratch/rummage").expanduser()


class Stop(RuntimeError):
    """Something in Live was not as expected. The job is held and the booth closes (runner.py)."""


_ops = None


def ops(client=None):
    """hands' LiveOps, using `client` for its LOM calls."""
    global _ops
    if _ops is None:
        from hands.live.ops import LiveOps
        from hands.live.transport import LiveClient

        _ops = LiveOps(LiveClient(), staging=STAGING)
    if client is not None:
        _ops.client = client
    return _ops


@contextmanager
def stops(where: str):
    """Turn hands' stops into Stop, naming the step."""
    from hands.live.session import Guard
    from hands.live.transport import LiveError
    try:
        yield
    except SystemExit as exc:
        raise Stop(f"{where}: {exc}") from None
    except (Guard, LiveError) as exc:
        raise Stop(f"{where}: {exc}") from None
