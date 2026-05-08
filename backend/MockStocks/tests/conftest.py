from __future__ import annotations

import sys
from pathlib import Path


MOCKSTOCKS_ROOT = Path(__file__).resolve().parents[1]
SRC_PATH = MOCKSTOCKS_ROOT / "src"

if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))
