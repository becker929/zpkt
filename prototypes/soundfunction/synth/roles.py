"""One clean hit per structural role, at the engine's defaults, for the
per-role feature table: python3 -m synth.roles  -> out/roles/<role>.wav"""
import os, soundfile as sf
from synth import engine as E

def main(out="out/roles"):
    os.makedirs(out, exist_ok=True)
    k = E.kick()
    roles = {
        "kick": k,
        "rumble": E.rumble(k),
        "hat_closed": E.hat(closed=True),
        "hat_open": E.hat(closed=False),
        "clap": E.clap(),
        "perc": E.ride_or_perc(),
        "stab": E.stab(),
        "pad": E.pad(),
        "riser": E.riser(),
        "impact": E.impact(),
    }
    for name, y in roles.items():
        sf.write(f"{out}/{name}.wav", E.normalize(y), E.SR if hasattr(E, "SR") else 44100)
    print(f"wrote {len(roles)} role hits to {out}")

if __name__ == "__main__":
    main()
