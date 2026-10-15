"""The map checklist's check sounds, as Live settings (make.py builds the set and renders them).

Three layers: a low body (Operator, a sine with a pitch drop, through a Saturator), a click transient (Operator, white
noise, high-passed) and a splashy mid-high (Operator, a sine frequency-modulated by noise, filtered, with an Echo).
A ping-pong Delay return takes the click and the splash. On Main: Drum Buss (distortion, transients, boom), Glue
Compressor and a Limiter. Each variant renders three times: hit, strong (the commit finishes a step) and land (the
box settling back into its row: body and click only, 12 dB softer).

Values are the devices' own display units where they have one ('300 ms', '1.42 kHz', '-12 dB', '25 %'), else raw:
Operator's Volume is 0..1 (0.85 is about -1 dB, 0.66 about -8 dB), Echo's L Synced is -6..0 (1/64 to 1, so -4 is a
16th), Glue's Ratio 0..2 (2, 4, 10), Attack 0..6 (.01 to 30 ms) and Release 0..6 (.1 s to Auto) are indices.
"""

BASE = {
    'body': {'note': 45, 'vol': 0.85, 'decay': '300 ms', 'pe': 24, 'pe_decay': '60 ms', 'feedb': 35, 'sat': '12 dB', 'sat_type': 'Medium Curve'},
    'click': {'vol': 0.62, 'decay': '9 ms', 'hp': '1.42 kHz', 'res': 0.5},
    'splash': {'note': 84, 'vol': 0.66, 'decay': '200 ms', 'b_level': 0.55, 'b_wave': 'Noise White', 'b_coarse': 1, 'b_decay': '110 ms',
               'ftype': 'Highpass', 'freq': '1.42 kHz', 'res': 0.3},
    'echo': {'sync': -4, 'mode': 'Synced', 'fb': '25 %', 'wet': '22 %', 'hp': '600 Hz', 'lp': '9 kHz'},
    'delay': {'16th': '1', 'fb': '20 %', 'click': 0.15, 'splash': 0.12, 'freq': '3 kHz'},
    'buss': {'drive': '40 %', 'type': 'Medium', 'crunch': '30 %', 'trans': 0.5, 'boom': '25 %', 'boom_f': '70 Hz', 'boom_d': '40 %'},
    'glue': {'thr': '-12 dB', 'ratio': 1, 'attack': 4, 'release': 0, 'out': '2 dB', 'lim': '0 dB'},
}

def merge(a, b):
    out = {k: dict(v) for k, v in a.items()}
    for k, v in b.items():
        out[k].update(v)
    return out

VARIANTS = {
    'anvil': ('Anvil', 'A hammer on steel: tight low thump, a bright metal ring, a slap of echo', {
        'body': {'note': 47, 'decay': '220 ms', 'pe': 28, 'pe_decay': '40 ms'},
        'click': {'vol': 0.72, 'decay': '6 ms', 'hp': '2.69 kHz'},
        'splash': {'note': 88, 'vol': 0.76, 'b_wave': 'Sine', 'b_coarse': 7, 'b_level': 0.7, 'b_decay': '160 ms', 'decay': '320 ms', 'freq': '2 kHz', 'res': 0.5},
        'echo': {'sync': -5, 'fb': '30 %', 'wet': '25 %'},
        'buss': {'crunch': '45 %', 'trans': 0.7},
    }),
    'vault': ('Vault', 'Deep and heavy: a big low body, a dark hiss, a slow dotted echo', {
        'body': {'note': 43, 'decay': '420 ms', 'pe': 20, 'pe_decay': '80 ms', 'sat': '15 dB'},
        'click': {'vol': 0.52, 'decay': '12 ms', 'hp': '800 Hz'},
        'splash': {'note': 76, 'vol': 0.76, 'decay': '260 ms', 'freq': '1.2 kHz', 'res': 0.4},
        'echo': {'sync': -3, 'mode': 'Dotted', 'fb': '30 %', 'wet': '20 %', 'lp': '4 kHz'},
        'buss': {'boom': '45 %', 'boom_f': '60 Hz', 'boom_d': '60 %', 'crunch': '15 %'},
        'glue': {'thr': '-16 dB', 'lim': '1.5 dB'},
    }),
    'crack': ('Crack', 'Snappy: a sharp crack on top, a short punch under it, a quick ping-pong', {
        'body': {'note': 48, 'decay': '160 ms', 'pe': 30, 'pe_decay': '30 ms'},
        'click': {'vol': 0.82, 'decay': '5 ms', 'hp': '3 kHz', 'res': 0.8},
        'splash': {'note': 90, 'vol': 0.56, 'decay': '140 ms', 'b_decay': '60 ms', 'b_level': 0.6, 'freq': '3.5 kHz'},
        'echo': {'sync': -5, 'fb': '35 %', 'wet': '28 %'},
        'buss': {'drive': '55 %', 'type': 'Hard', 'crunch': '50 %', 'trans': 0.9, 'boom': '10 %'},
    }),
    'slam': ('Slam', 'Squashed hard: compressed and saturated, a long splash that blooms after the hit', {
        'body': {'note': 45, 'decay': '320 ms', 'sat': '18 dB', 'sat_type': 'Analog Clip'},
        'splash': {'vol': 0.74, 'decay': '380 ms', 'b_decay': '200 ms', 'freq': '1.8 kHz'},
        'echo': {'sync': -4, 'mode': 'Triplet', 'fb': '35 %', 'wet': '24 %'},
        'buss': {'drive': '60 %', 'crunch': '35 %', 'trans': 0.2},
        'glue': {'thr': '-26 dB', 'ratio': 2, 'attack': 3, 'release': 1, 'out': '6 dB', 'lim': '11 dB'},
    }),
    'block': ('Block', 'Woody: a knock on a heavy block, a boxy mid splash, a short tail', {
        'body': {'note': 50, 'decay': '140 ms', 'pe': 18, 'pe_decay': '25 ms', 'feedb': 55},
        'click': {'vol': 0.67, 'decay': '7 ms', 'hp': '1.2 kHz'},
        'splash': {'note': 72, 'vol': 0.64, 'decay': '120 ms', 'b_decay': '50 ms', 'ftype': 'Bandpass', 'freq': '2.2 kHz', 'res': 0.9},
        'glue': {'lim': '2 dB'},
        'echo': {'sync': -5, 'fb': '20 %', 'wet': '18 %', 'lp': '5 kHz'},
        'buss': {'crunch': '25 %', 'trans': 0.6, 'boom': '15 %'},
    }),
    'thunder': ('Thunder', 'Wide and rolling: a boomy body, a crashing splash, echoes that roll away', {
        'body': {'note': 44, 'decay': '500 ms', 'pe': 26, 'pe_decay': '90 ms', 'sat': '14 dB'},
        'splash': {'note': 80, 'vol': 0.8, 'decay': '450 ms', 'b_decay': '260 ms', 'b_level': 0.65, 'freq': '1.2 kHz'},
        'echo': {'sync': -3, 'fb': '40 %', 'wet': '24 %', 'lp': '6 kHz'},
        'delay': {'16th': '3', 'fb': '30 %', 'splash': 0.3},
        'buss': {'boom': '40 %', 'boom_d': '70 %', 'crunch': '30 %'},
        'glue': {'lim': '-2.5 dB'},
    }),
}

def ms(v, k):
    return f"{float(v.split()[0]) * k:.0f} ms"


def strong(s):
    """The commit that finishes a step: longer and heavier."""
    return merge(s, {
        'body': {'decay': ms(s['body']['decay'], 1.6), 'pe': s['body']['pe'] + 4},
        'splash': {'decay': ms(s['splash']['decay'], 1.5), 'vol': min(0.86, s['splash']['vol'] + 0.1)},
        'echo': {'fb': f"{min(55, int(s['echo']['fb'].split()[0]) + 15)} %"},
        'buss': {'boom': f"{min(70, int(s['buss']['boom'].split()[0]) + 20)} %"},
    })
