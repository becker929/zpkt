#!/bin/bash
# Disconnect and remove the virtual display(s) created for testing.
set -euo pipefail

# Disconnect every virtual screen, then discard them all.
for TAG in $(betterdisplaycli get -deviceType=VirtualScreen -identifiers 2>/dev/null \
               | grep '"tagID"' | grep -oE '[0-9]+'); do
  betterdisplaycli set -tagID="$TAG" -connected=off >/dev/null 2>&1 || true
done

betterdisplaycli discard -deviceType=VirtualScreen >/dev/null 2>&1 || true
echo "Disconnected and discarded all virtual screens."
