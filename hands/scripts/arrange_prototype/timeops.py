"""Edit-menu time operations driven over LOM + System Events, each verified by
song.last_event_time. Positions are beats on the current (edited) timeline."""
import time

import arrange as A

r = A.r


def select(start, length):
    r("song.stop_playing()")
    r('Live.Application.get_application().view.show_view("Arranger")')
    r('Live.Application.get_application().view.focus_view("Arranger")')
    r(f"song.loop_start = {float(start)}")
    r(f"song.loop_length = {float(length)}")
    for _ in range(4):
        A.menu("Edit", "Select Loop")
        time.sleep(0.3)
        return True


def op(item, start, length, expect_delta):
    before = r("song.last_event_time")
    for _ in range(4):
        select(start, length)
        if A.menu("Edit", item, tries=3):
            time.sleep(0.8)
            after = r("song.last_event_time")
            if expect_delta is None or abs((after - before) - expect_delta) < 1e-6:
                return after - before
            raise RuntimeError(f"{item} at {start}+{length}: last event moved {after - before}, expected {expect_delta}")
    raise RuntimeError(f"{item} stayed disabled at {start}+{length}")


def delete(start, length):
    return op("Delete Time", start, length, -length)


def duplicate(start, length):
    """Insert a copy of [start, start+length) right after it."""
    return op("Duplicate Time", start, length, length)


def copy(start, length):
    return op("Copy Time", start, length, 0)


def paste(at, length):
    """Insert the copied time at `at` (the copied length must equal `length`)."""
    return op("Paste Time", at, length, length)
