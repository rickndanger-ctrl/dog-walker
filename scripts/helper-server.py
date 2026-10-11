"""Load Handler's user-launched operator MCP server with isolated Python."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dog_walker.helper_mcp import main
main()
