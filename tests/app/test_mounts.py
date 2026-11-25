"""Mounts: route sets under a path prefix, the seam the Song uses, and the bus's per-set guard."""

from __future__ import annotations

import pytest

from zpkt.app.bus import Bus, Command, Refused, SetGuard, Spec
from zpkt.app.mounts import MountReply, Mounts


class Echo:
    def handle(self, method, path, read_body):
        return MountReply(200, f"{method} {path}".encode(), "text/plain")


def test_a_path_under_a_prefix_goes_to_its_mount_with_the_prefix_cut_off():
    mounts = Mounts()
    mounts.add("/app/song", Echo())
    prefix, mount, rest = mounts.find("/app/song/api/arrangements")
    assert (prefix, rest) == ("/app/song", "/api/arrangements") and isinstance(mount, Echo)
    assert mounts.find("/app/song")[2] == "/"
    assert mounts.find("/app/song/")[2] == "/"


def test_a_path_that_only_starts_like_a_prefix_is_not_mounted():
    mounts = Mounts()
    mounts.add("/app/song", Echo())
    assert mounts.find("/app/songs") is None and mounts.find("/app/") is None and mounts.find("/") is None


def test_a_prefix_is_added_once_and_can_be_removed():
    mounts = Mounts()
    mounts.add("/a", Echo())
    with pytest.raises(ValueError, match="already mounted"):
        mounts.add("/a", Echo())
    for bad in ("a", "/a/", ""):
        with pytest.raises(ValueError, match="starts with /"):
            mounts.add(bad, Echo())
    mounts.remove("/a")
    assert mounts.find("/a/x") is None
    mounts.remove("/a")  # nothing to remove is fine


def test_an_unmounted_path_is_the_web_servers_own_404(rig):
    assert rig.get("/app/song/")[0] == 404 and rig.get("/app/songs")[0] == 404


def test_a_move_for_another_set_is_checked_against_that_set_not_the_pages():
    seen = {"name": "HW002_121_pp_mix"}
    guard = SetGuard("HW002_121_pp_finish", lambda: seen["name"], clock=lambda: 0.0)
    bus = Bus(guard=guard)
    bus.register("desk.move", Spec(lambda cmd: (200, {}), "move"))
    bus.register("mix.build", Spec(lambda cmd: (200, {}), "move", for_set="HW002_121_pp_mix"))
    assert bus.submit(Command("desk.move"))[0] == 409  # the page's set is not the open one
    assert bus.submit(Command("mix.build"))[0] == 200  # the open set is the one this move names
    seen["name"] = ""  # unsaved: both pass the guard; the build's handler checks for itself
    guard.forget()
    assert bus.submit(Command("mix.build"))[0] == 200
    with pytest.raises(Refused):
        seen["name"] = "other"
        guard.forget()
        guard.check("HW002_121_pp_mix")
