"""AudioSet class names grouped into the three span labels.

Generated once from the AudioSet ontology (github.com/audioset/ontology,
``ontology.json``) and checked in, so nothing is downloaded at import time.
The sets are display names, not machine ids, because YAMNet's class map and the
AST classifier's ``id2label`` both use the same display-name strings.

How the groups were derived:

* ``SPEECH_NAMES`` is every descendant of ``Speech`` (``/m/09x0r``), plus
  ``Whispering``. The ontology files whispering under ``Human voice`` rather
  than under ``Speech``; a whisper is still speech, so it is added by hand.
* ``MUSIC_NAMES`` is every descendant of ``Music`` (``/m/04rlf``) together with
  every descendant of ``Singing`` (``/m/015lz1``). The ontology files singing
  under ``Human voice``, so the ``Music`` branch alone would send a sung take to
  ``other``. That would be wrong for this collection.
* ``Humming`` and ``Whistling`` are deliberately left in ``other``. They are
  usually incidental noise in a recording rather than the musical content.
* Everything else is ``other``, including laughter, shouting, crying, applause,
  and ``Silence``.
"""

from __future__ import annotations

SPEECH = "speech"
MUSIC = "music"
OTHER = "other"

LABELS: tuple[str, str, str] = (SPEECH, MUSIC, OTHER)

SPEECH_NAMES: frozenset[str] = frozenset(
    (
        "Babbling",
        "Child speech, kid speaking",
        "Conversation",
        "Female speech, woman speaking",
        "Male speech, man speaking",
        "Narration, monologue",
        "Speech",
        "Speech synthesizer",
        "Whispering",
    )
)

MUSIC_NAMES: frozenset[str] = frozenset(
    (
        "A capella",
        "Accordion",
        "Acoustic guitar",
        "Afrobeat",
        "Alto saxophone",
        "Ambient music",
        "Angry music",
        "Background music",
        "Bagpipes",
        "Banjo",
        "Bass (instrument role)",
        "Bass drum",
        "Bass guitar",
        "Bassline",
        "Bassoon",
        "Beat",
        "Beatboxing",
        "Bell",
        "Bicycle bell",
        "Birthday music",
        "Bluegrass",
        "Blues",
        "Bowed string instrument",
        "Brass instrument",
        "Bugle",
        "Carnatic music",
        "Cello",
        "Change ringing (campanology)",
        "Chant",
        "Child singing",
        "Chime",
        "Choir",
        "Chord",
        "Christian music",
        "Christmas music",
        "Church bell",
        "Clarinet",
        "Classical music",
        "Clavinet",
        "Cornet",
        "Country",
        "Cowbell",
        "Crash cymbal",
        "Cumbia",
        "Cymbal",
        "Dance music",
        "Didgeridoo",
        "Disco",
        "Double bass",
        "Drone",
        "Drone music",
        "Drum",
        "Drum and bass",
        "Drum beat",
        "Drum kit",
        "Drum machine",
        "Drum roll",
        "Dub",
        "Dubstep",
        "Electric guitar",
        "Electric piano",
        "Electro",
        "Electronic dance music",
        "Electronic music",
        "Electronic organ",
        "Electronica",
        "Exciting music",
        "Female singing",
        "Flamenco",
        "Flute",
        "Folk music",
        "French horn",
        "Funk",
        "Funk carioca",
        "Funny music",
        "Glockenspiel",
        "Gong",
        "Gospel music",
        "Grime music",
        "Grunge",
        "Guitar",
        "Hammond organ",
        "Happy music",
        "Harmonica",
        "Harmony",
        "Harp",
        "Harpsichord",
        "Heavy metal",
        "Hi-hat",
        "Hip hop music",
        "House music",
        "Independent music",
        "Jazz",
        "Jingle (music)",
        "Jingle bell",
        "Keyboard (musical)",
        "Kuduro",
        "Kwaito",
        "Loop",
        "Lullaby",
        "Male singing",
        "Mallet percussion",
        "Mandolin",
        "Mantra",
        "Maraca",
        "Marimba, xylophone",
        "Mellotron",
        "Melody",
        "Middle Eastern music",
        "Music",
        "Music for children",
        "Music genre",
        "Music mood",
        "Music of Africa",
        "Music of Asia",
        "Music of Bollywood",
        "Music of Latin America",
        "Music role",
        "Musical concepts",
        "Musical ensemble",
        "Musical instrument",
        "Musical note",
        "New-age music",
        "Noise music",
        "Oboe",
        "Oldschool jungle",
        "Opera",
        "Orchestra",
        "Organ",
        "Percussion",
        "Piano",
        "Pizzicato",
        "Plucked string instrument",
        "Pop music",
        "Progressive rock",
        "Psychedelic rock",
        "Punk rock",
        "Rapping",
        "Rattle (instrument)",
        "Reggae",
        "Rhodes piano",
        "Rhythm and blues",
        "Rimshot",
        "Rock and roll",
        "Rock music",
        "Sad music",
        "Salsa music",
        "Sampler",
        "Saxophone",
        "Scary music",
        "Scratching (performance technique)",
        "Shofar",
        "Singing",
        "Singing bowl",
        "Sitar",
        "Ska",
        "Snare drum",
        "Soca music",
        "Song",
        "Soprano saxophone",
        "Soul music",
        "Soundtrack music",
        "Steel guitar, slide guitar",
        "Steelpan",
        "String section",
        "Strum",
        "Swing music",
        "Synthesizer",
        "Synthetic singing",
        "Tabla",
        "Tambourine",
        "Tapping (guitar technique)",
        "Techno",
        "Tender music",
        "Theme music",
        "Theremin",
        "Timpani",
        "Traditional music",
        "Trance music",
        "Trap music",
        "Trombone",
        "Trumpet",
        "Tubular bells",
        "Tuning fork",
        "UK garage",
        "Ukulele",
        "Vibraphone",
        "Video game music",
        "Violin, fiddle",
        "Vocal music",
        "Wedding music",
        "Wind chime",
        "Wind instrument, woodwind instrument",
        "Wood block",
        "Yodeling",
        "Zither",
    )
)


def label_for(class_name: str) -> str:
    """Map one AudioSet display name onto ``speech``, ``music`` or ``other``.

    An unknown name is ``other``. That is the honest answer for a class this
    module has never heard of, and it keeps a newer label set from crashing the
    classifier.
    """
    if class_name in SPEECH_NAMES:
        return SPEECH
    if class_name in MUSIC_NAMES:
        return MUSIC
    return OTHER

