"""Property tests of the Host and Origin checks: whatever text arrives, they answer yes or no and never raise."""

from __future__ import annotations

from hypothesis import given
from hypothesis import strategies as st

from zpkt.app.web import LOOPBACK_NAMES, TAILNET_SUFFIX, cross_site, host_allowed, split_host

labels = st.from_regex(r"[a-z][a-z0-9-]{0,10}", fullmatch=True)
ports = st.one_of(st.none(), st.integers(1, 65535))
text = st.one_of(st.none(), st.text(max_size=40))


@given(
    host=text, origin=text, fwd=text, proto=st.one_of(st.none(), st.sampled_from(["http", "https", "https,http", ""]))
)
def test_the_checks_answer_for_any_text(host, origin, fwd, proto):
    assert isinstance(host_allowed(host), bool)
    assert isinstance(cross_site(origin, host, fwd, proto), bool)


@given(name=st.sampled_from(LOOPBACK_NAMES), port=ports)
def test_loopback_names_are_allowed_with_any_port(name, port):
    shown = f"[{name}]" if ":" in name else name
    assert host_allowed(shown if port is None else f"{shown}:{port}")


@given(label=labels, port=ports)
def test_tailnet_names_are_allowed_in_any_case(label, port):
    host = f"{label}.tail1234{TAILNET_SUFFIX}".upper()
    assert host_allowed(host if port is None else f"{host}:{port}")


@given(label=labels, port=ports)
def test_a_stranger_is_turned_away_unless_added(label, port):
    host = f"{label}.example" if port is None else f"{label}.example:{port}"
    assert not host_allowed(host)
    assert host_allowed(host, extra=[f"{label}.EXAMPLE"])


@given(label=labels)
def test_a_name_with_a_path_or_login_is_no_host(label):
    assert split_host(f"{label}/path") is None
    assert split_host(f"{label}@localhost") is None


@given(host=st.sampled_from(["localhost", "127.0.0.1"]), port=st.integers(1, 65535))
def test_the_desks_own_origin_is_same_site(host, port):
    asked = f"{host}:{port}"
    assert cross_site(f"http://{asked}", asked) is False


@given(label=labels, port=st.integers(1, 65535))
def test_another_name_or_port_is_cross_site(label, port):
    assert cross_site(f"http://{label}.example:{port}", f"localhost:{port}") is True
    assert cross_site(f"http://localhost:{port}", f"localhost:{port % 65535 + 1}") is True


@given(host=text)
def test_no_origin_passes_and_a_null_origin_does_not(host):
    assert cross_site(None, host) is False and cross_site("", host) is False
    assert cross_site("null", host) is True


@given(label=labels)
def test_a_proxys_default_port_is_the_same_site(label):
    name = f"{label}.tail1234{TAILNET_SUFFIX}"
    assert cross_site(f"https://{name}", f"{name}:443", name, "https") is False
    assert cross_site(f"https://{name}", f"{name}:8985", None, "https") is True
