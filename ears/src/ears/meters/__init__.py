"""The calibrated meters: every instrument here has a known-answer check (ears/mlab/calibration).

Until 24 Nov 2026 this was its own project, mlab, and `import mlab` still reaches it (src/mlab). It was built
while mastering HW002 and keeps the book's chapter numbers: loudness (Ch. 17-19), dynamics (Ch. 5-7),
spectrum (Ch. 4), bitdepth (Ch. 15), premaster and als (Ch. 14), compare (Ch. 20-21), delivery (platforms and
codecs), target and eqfit (a mix against references), sections, dsp (reference processors), siggen, measure
(the full sheet) and hypothesis (the runner). Band tables, references and windows each live in one module
(bands, references, windows).
"""

__version__ = "0.1.0"
