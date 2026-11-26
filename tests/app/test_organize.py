"""Organizing the desk's pages: rename, reorder, move, archive and restore, through organize.py, the bus and Ask."""

from __future__ import annotations

import pytest

from zpkt.app import organize
from zpkt.app.bus import Command

RAW = [
    {"name": "Mix", "pad": 1, "controls": {"k1": {}, "f1": {}}},
    {"name": "Kick", "pad": 2, "controls": {"k1": {}, "k2": {}}},
    {"name": "EQ 1", "page_id": "eq", "pad": 3, "controls": {"k1": {}}},
    {"name": "EQ 2", "page_id": "eq", "pad": 0, "controls": {"k2": {}}},
    {"name": "Old", "surface": "old.json", "pad": 0, "controls": {"f1": {}}},
]

SPEC = {
    "title": "Kick: level",
    "groups": [{"name": "Level", "controls": [{"target": "Kick bus/volume", "role": "level"}]}],
}


# ---- pure rules (organize.py) ---------------------------------------------------------------------------------------


def test_rename_reorder_move_archive_restore_and_pads(tmp_path):
    org = organize.empty()
    org = organize.rename(RAW, org, "eq", "Kick EQ")  # bare saved page_id resolves to page:eq
    arranged = organize.arrange(RAW, org)
    assert [p["name"] for p in arranged] == ["Mix", "Kick", "Kick EQ 1", "Kick EQ 2", "Old"]

    org = organize.move(RAW, org, "page:eq", by=-2)
    assert [u["id"] for u in organize.units(RAW, org) if not u["archived"]] == [
        "page:eq",
        "desk:Mix",
        "desk:Kick",
        "surface:old.json",
    ]
    listed = organize.listing(RAW, org)
    assert [(u["id"], u["pad"], u["name"]) for u in listed] == [
        ("page:eq", 1, "Kick EQ"),
        ("desk:Mix", 2, "Mix"),
        ("desk:Kick", 3, "Kick"),
        ("surface:old.json", 4, "Old"),
    ]

    org = organize.archive(RAW, org, "desk:Kick", True)
    assert [u["id"] for u in organize.units(RAW, org) if not u["archived"]] == [
        "page:eq",
        "desk:Mix",
        "surface:old.json",
    ]
    assert [u["id"] for u in organize.units(RAW, org) if u["archived"]] == ["desk:Kick"]

    org = organize.archive(RAW, org, "desk:Kick", False)
    assert all(not u["archived"] for u in organize.units(RAW, org))

    organize.write(tmp_path, org)
    assert organize.read(tmp_path) == org


def test_cannot_archive_the_last_active_page_or_use_bad_ids():
    org = organize.empty()
    for uid in ("desk:Mix", "desk:Kick", "page:eq"):
        org = organize.archive(RAW, org, uid, True)
    with pytest.raises(ValueError, match="at least one page"):
        organize.archive(RAW, org, "surface:old.json", True)
    with pytest.raises(ValueError, match="no page with id"):
        organize.rename(RAW, org, "desk:Nope", "X")
    with pytest.raises(ValueError, match="1 to 40"):
        organize.rename(RAW, org, "surface:old.json", "   ")
    with pytest.raises(ValueError, match="archived pages cannot be reordered"):
        organize.move(RAW, org, "desk:Mix", by=1)
    with pytest.raises(ValueError, match="duplicate"):
        organize.reorder(RAW, org, ["desk:Mix", "desk:Mix"])


# ---- bus, HTTP and Ask integration ----------------------------------------------------------------------------------


def test_page_organize_commands_and_http_listing(rig):
    code, before = rig.get("/api/organize")
    assert code == 200 and len(before["units"]) >= 2
    first, second = before["units"][0], before["units"][1]

    # Rename the first page and confirm the desk keeps it armed with its new name.
    code, reply = rig.command("page.organize", {"action": "rename", "id": first["id"], "name": "Renamed First"})
    assert code == 200 and reply["ok"] is True and reply["units"][0]["name"] == "Renamed First"
    assert rig.get("/api/desk")[1]["pages"][0]["name"] == "Renamed First"

    # Move the second page up to slot 0: the first unit stays armed at its new index.
    code, reply = rig.command("page.organize", {"action": "move", "id": second["id"], "by": -1})
    assert code == 200 and reply["units"][0]["id"] == second["id"] and reply["open"] == 1

    # Archive and restore.
    code, reply = rig.command("page.organize", {"action": "archive", "id": first["id"]})
    assert code == 200 and any(u["id"] == first["id"] and u["archived"] for u in reply["units"])
    code, reply = rig.command("page.organize", {"action": "restore", "id": first["id"]})
    assert code == 200 and all(not u["archived"] for u in reply["units"])

    # Invalid action is 400.
    assert rig.command("page.organize", {"action": "bogus"})[0] == 400
    assert rig.command("page.list", {})[0] == 200


def test_renaming_a_saved_page_updates_pages_listing_and_layout(rig):
    code, made = rig.desk.bus.submit(Command("page.make", "agent", {"spec": SPEC}))
    assert code == 200
    pid = made["id"]
    code, _ = rig.command("page.organize", {"action": "rename", "id": pid, "name": "Kick Main"})
    assert code == 200
    listed = rig.get("/api/pages")[1]["pages"]
    assert next(p["title"] for p in listed if p["id"] == pid) == "Kick Main"
    code, lay = rig.command("page.layout", {"id": pid})
    assert code == 200 and lay["layout"]["title"] == "Kick Main"


def test_ask_agent_can_read_units_and_organize_pages(asked):
    gate = asked.ask.gate
    tok = gate.token("s1")
    code, state = gate.call("s1", tok, "read_state", {})
    assert code == 200 and "units" in state and len(state["units"]) >= 2
    target = state["units"][0]["id"]
    code, reply = gate.call("s1", tok, "organize_pages", {"action": "rename", "id": target, "name": "Agent Named"})
    assert code == 200 and reply["ok"] is True
    assert asked.rig.get("/api/desk")[1]["pages"][0]["name"] == "Agent Named"
    assert asked.rig.desk.history.entries == []  # organizing moves nothing in the mix
