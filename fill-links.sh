#!/usr/bin/env bash
# Fill the two README placeholders once the hosted URL and video exist.
#   ./scripts_fill_links.sh https://clearcut-xxxx.run.app https://youtu.be/xxxx
set -euo pipefail

HOSTED="${1:?usage: $0 <hosted-url> <video-url>}"
VIDEO="${2:?usage: $0 <hosted-url> <video-url>}"

python3 - "$HOSTED" "$VIDEO" <<'PY'
import re, sys
from pathlib import Path
hosted, video = sys.argv[1], sys.argv[2]
p = Path("README.md"); t = p.read_text()
t = re.sub(r"\| \*\*Live\*\* \| .*? \|", f"| **Live** | <{hosted}> |", t, count=1)
t = re.sub(r"\| \*\*Demo\*\* \| .*? \|", f"| **Demo** | <{video}> |", t, count=1)
p.write_text(t)
print(f"  Live -> {hosted}\n  Demo -> {video}")
PY

grep -n -E "\*\*(Live|Demo)\*\*" README.md
