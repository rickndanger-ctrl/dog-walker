"""Load installed trusted app code with Python's isolated mode."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dog_walker.tool_server import main

main()
