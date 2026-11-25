"""Property tests of live.page: any JSON either parses to a page or is a ValueError that names the problem, and lint
answers for every page it is given."""

from __future__ import annotations

from hypothesis import given
from hypothesis import strategies as st

from zpkt.live import page as P

json_values = st.recursive(
    st.none() | st.booleans() | st.integers() | st.floats(allow_nan=False) | st.text(max_size=12),
    lambda inner: st.lists(inner, max_size=4) | st.dictionaries(st.text(max_size=8), inner, max_size=4),
    max_leaves=12,
)

names = st.text("abcdefghij /", min_size=1, max_size=12)
targets = st.builds("{}/{}".format, names, names)
controls = st.builds(lambda t: {"target": t}, targets)
groups = st.builds(lambda n, c: {"name": n, "controls": c}, names, st.lists(controls, max_size=5))
specs = st.builds(lambda t, g: {"title": t, "groups": g}, st.text(max_size=60), st.lists(groups, max_size=4))


@given(data=json_values)
def test_any_json_parses_or_is_a_plain_value_error(data):
    try:
        got = P.parse(data)
    except ValueError as exc:
        assert str(exc).startswith("not a page:")
    else:
        assert isinstance(got, P.Page)


@given(spec=specs)
def test_a_well_formed_spec_parses_and_its_targets_are_listed_once(spec):
    page = P.parse(spec)
    targets_ = page.targets()
    assert len(targets_) == len(set(targets_))
    assert set(targets_) == {c["target"] for g in spec["groups"] for c in g["controls"]}


@given(spec=specs)
def test_lint_answers_with_errors_first_and_the_known_rules(spec):
    problems = P.lint(P.parse(spec), {})
    levels = [p["level"] for p in problems]
    assert levels == sorted(levels, key=lambda v: v != "error")  # every error before every note
    if not any(g["controls"] for g in spec["groups"]):
        assert any(p["where"] == "page" and "no controls" in p["text"] for p in problems)
    if len(spec["title"]) > 40:
        assert any("title is over 40" in p["text"] for p in problems)
    for g in spec["groups"]:
        if not g["controls"]:
            assert any(p["where"] == g["name"] and p["level"] == "error" for p in problems)
