"""Download HumTrans into datasets/humtrans/ (about 17 GB on disk, ~6 minutes).

    pip install stream-unzip
    python3 -m humtrans.fetch
    git clone https://github.com/shansongliu/HumTrans ../HumTrans   # the paper's model outputs, for official.py

The 14.7 GB WAV archive is unzipped while it downloads, so the zip is never
stored; downloading it first and unzipping after needs twice the space.
The dataset is CC BY-NC 4.0 and is gitignored here.
"""
import urllib.request
import zipfile
from io import BytesIO

from .common import DATA

BASE = "https://huggingface.co/datasets/dadinghh2/HumTrans/resolve/main/"


def get(name):
    with urllib.request.urlopen(BASE + name) as r:
        return r.read()


def stream(name):
    from stream_unzip import stream_unzip

    def chunks():
        with urllib.request.urlopen(BASE + name) as r:
            while b := r.read(1 << 20):
                yield b
    n = 0
    for fname, _, data in stream_unzip(chunks()):
        fname = fname.decode()
        if fname.endswith("/"):
            for _ in data:
                pass
            continue
        path = DATA / fname
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "wb") as f:
            for c in data:
                f.write(c)
        n += 1
        if n % 1000 == 0:
            print(n, fname, flush=True)
    return n


def main():
    DATA.mkdir(parents=True, exist_ok=True)
    for name in ("README.md", "train_valid_test_keys.json"):
        (DATA / name).write_bytes(get(name))
    zipfile.ZipFile(BytesIO(get("all_midi.zip"))).extractall(DATA)
    print("wav files:", stream("all_wav.zip"))


if __name__ == "__main__":
    main()
