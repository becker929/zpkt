# contrib/skrng

Publishing renders to my site. /skrng on anthonybecker.me is where I listen to batches of
renders and leave feedback from my phone.

- `publish_render.sh` uploads an approved MP3 to R2 and prints its manifest entry.
- `batch_intro.py` writes the spoken intro for a batch.

Both need a wrangler login with access to my bucket, so they are useful only as an example.
The embedding model `ears` needs is public: `ears/scripts/fetch_model.sh`.
