"""Launch a real terminal and its scoped model helper connection."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dog_walker.terminal import main
raise SystemExit(main())
