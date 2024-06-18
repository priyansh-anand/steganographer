#!/usr/bin/env python3
"""
Lets you keep running `python3 steganographer.py ...` from a clone of the
repository without installing anything. The code lives in src/steganographer.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from steganographer.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
