"""Console I/O compatibility helpers.

Windows terminals often default to a legacy codepage (e.g. cp1252) that
cannot encode the ✅/❌/₹ characters this codebase prints for readability.
Call `ensure_utf8_stdio()` at the top of any script entrypoint, before the
first print, to make stdout/stderr UTF-8 regardless of the host console's
default encoding.
"""
from __future__ import annotations

import sys


def ensure_utf8_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        encoding = getattr(stream, "encoding", None) or ""
        if encoding.lower() != "utf-8" and hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
