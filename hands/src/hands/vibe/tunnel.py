"""ngrok tunnel management for exposing the vibe server to the phone."""
from __future__ import annotations


def open_tunnel(port: int = 8080) -> str:
    """Open an ngrok tunnel to the local port. Returns the public URL.

    Requires hands[vibe] extras (pyngrok).
    """
    try:
        from pyngrok import ngrok  # type: ignore[import]
    except ImportError as exc:
        raise ImportError(
            "pyngrok is required for tunnel support. "
            "Install with: pip install hands[vibe]"
        ) from exc

    tunnel = ngrok.connect(port, "http")
    url = tunnel.public_url
    print(f"  ngrok tunnel: {url}")
    return url


def close_all_tunnels() -> None:
    """Close all open ngrok tunnels."""
    try:
        from pyngrok import ngrok  # type: ignore[import]
        ngrok.kill()
    except ImportError:
        pass
