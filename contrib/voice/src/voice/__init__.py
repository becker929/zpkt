"""voice: the speech models of studio (docs/design/studio.md), in their own process. `voice serve` reads requests on stdin
and writes replies on stdout (voice.protocol); the engines are Kokoro for speech and a local speech-to-text with
the stop word."""
