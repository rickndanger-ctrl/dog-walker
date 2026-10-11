#!/usr/bin/env python3
"""Create or run Dog Walker's preliminary paired helper benchmark."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dog_walker.benchmark import main

if __name__ == "__main__":
    raise SystemExit(main())
