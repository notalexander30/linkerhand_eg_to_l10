#!/usr/bin/env python3
"""Terminal launcher for the EG/right-glove to left L10 bridge."""

import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from glove_to_l10 import main  # noqa: E402


if __name__ == "__main__":
    main()
