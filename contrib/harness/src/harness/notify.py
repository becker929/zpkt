"""Phone notifications through ntfy.sh. The topic is a secret (Keychain)."""

from __future__ import annotations

import logging
import urllib.request

from .config import secret

log = logging.getLogger(__name__)


def notify(title: str, body: str, click: str | None = None, topic: str | None = None) -> bool:
    topic = topic or secret("ntfy_topic")
    if not topic:
        log.warning("no ntfy topic; skipped %r", title)
        return False
    headers = {"Title": title.encode("ascii", "replace").decode()}
    if click:
        headers["Click"] = click
    req = urllib.request.Request(f"https://ntfy.sh/{topic}", data=body.encode(), headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status == 200
    except OSError as exc:
        log.warning("ntfy failed: %s", exc)
        return False
