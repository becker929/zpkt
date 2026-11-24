"""protocol.py: what the server accepts from the pager."""

from __future__ import annotations

import protocol as P
import pytest

GOOD = [
    {"t": "v", "page": 0, "slot": "f1", "n": 0.5, "s": "-6.0 dB", "r": 0.5, "key": "Kick bus/volume", "sys": False},
    {"t": "v", "page": 1, "slot": "b1", "n": 1.0, "s": "on", "r": True, "key": "Kick bus/mute"},
    {"t": "v", "page": 1, "slot": "k2", "n": 0.3, "s": "30 %", "r": 0.3, "key": None},
    {"t": "pos", "b": 0, "p": False},
    {"t": "mon", "slot": "A", "ref": "C1"},
    {"t": "mon", "slot": "W", "ref": "C1", "err": "monitor tracks missing"},
    {"t": "loop", "loop": "off"},
    {"t": "page", "page": 2, "picked": {}},
    {"t": "hw", "page": 0, "slot": "b3", "hw": None, "picked": True},
]


@pytest.mark.parametrize("msg", GOOD)
def test_every_message_the_pager_sends_is_accepted(msg):
    import json

    assert P.parse_datagram(json.dumps(msg).encode()) == msg


@pytest.mark.parametrize(
    "data",
    [b"", b"nope", b"[]", b"3", b"{}", b'{"t": "x"}', b'{"t": 1}', b'{"t": "pos", "b": 1}',
     b'{"t": "pos", "b": "1", "p": true}', b'{"t": "pos", "b": true, "p": true}', b'{"t": "page", "page": 1.5}',
     b'{"t": "v", "page": 0}'],
)
def test_anything_else_is_a_bad_message_that_says_why(data):
    with pytest.raises(P.BadMessage) as exc:
        P.parse_datagram(data)
    assert str(exc.value)
