"""The mix desk recipe's "desk": the contract hands reads it by, so core never imports the desk's own code.

contrib/mixdesk/recipe.py writes it into the arrangement recipe (the HW002 finishing chain): the returns with their
devices, the desk's device chains ("desk EQ", "desk Sat", ...) on each track, every track's mixer, the switches it
owns on devices it did not add, and the monitor tracks. `hands live state diff|put` take a recipe file because
hands.live.state.from_desk reads this shape as a partial state. lib/contracts/desk.schema.json is generated from these
models (tools/gen_schemas.py); a test fails when the two drift. Unknown keys are kept, so the desk may grow.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

ShownRawPair = tuple[str, float | bool]  # [what Live shows, the raw value], a two-item list in JSON


class _Open(BaseModel):
    model_config = ConfigDict(extra="allow")


class DeskDevice(_Open):
    name: str
    class_: str | None = Field(default=None, alias="class", description="The device's LOM class_name.")
    values: dict[str, ShownRawPair] = Field(description="Every parameter by LOM name.")


class DeskReturn(_Open):
    name: str = Field(description="The return's name without Live's letter.")
    devices: list[DeskDevice]


class DeskMixer(_Open):
    volume: ShownRawPair
    pan: ShownRawPair
    sends: dict[str, ShownRawPair] = Field(default_factory=dict, description="By the return's short name.")
    mute: bool | None = Field(default=None, description="Tracks only; Main has none.")


class DeskOwned(_Open):
    track: str
    device: str
    values: dict[str, ShownRawPair] = Field(description="Only the parameters the desk owns (switches).")


class DeskMonitor(_Open):
    track: str
    file: str
    beat: float
    warping: bool


class Desk(_Open):
    """The desk as recipe.py writes it."""

    made: float | None = Field(default=None, description="When it was read from Live (Unix seconds).")
    set: str | None = None
    note: str | None = None
    returns: list[DeskReturn] = Field(default_factory=list)
    chains: dict[str, list[DeskDevice]] = Field(default_factory=dict, description="Desk devices by track short name.")
    mixer: dict[str, DeskMixer] = Field(description="Every track, return and Main by short name.")
    owned: list[DeskOwned] = Field(default_factory=list)
    monitor: list[DeskMonitor] = Field(default_factory=list)


def parse(data: Any) -> Desk:
    """Check a desk against the contract; ValueError naming the first thing wrong."""
    try:
        return Desk.model_validate(data)
    except ValidationError as exc:
        first = exc.errors()[0]
        where = "/".join(str(p) for p in first["loc"]) or "the desk"
        raise ValueError(f"not a mix desk recipe: {where}: {first['msg']}") from None
