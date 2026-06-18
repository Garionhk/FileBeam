import sys
from pathlib import Path

# Make the project importable when running `pytest` from the repo root.
ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
