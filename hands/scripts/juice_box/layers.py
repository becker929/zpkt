"""The score's building blocks, shared by every kit: a sample layer S on a role's lane, a note N for the Sine track."""

SCALE = (0, 2, 4, 7, 9, 12, 14, 16)        # combos climb this


def S(role, name, t=0.0, db=0.0, st=0):
    """A sample: its role, its Core Library file name, start (s), clip gain (dB), transpose (semitones)."""
    return ("s", role, name, t, db, st)


def N(pitch, t=0.0, length=0.1, vel=100):
    """A Sine note: pitch, start (s), length (s; the sustain makes a longer note a longer boom), velocity."""
    return ("n", pitch, t, length, vel)
