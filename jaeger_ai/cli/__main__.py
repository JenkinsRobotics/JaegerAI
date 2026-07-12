"""``python -m jaeger_os.cli`` entry."""

from __future__ import annotations

import sys

from . import main


if __name__ == "__main__":
    sys.exit(main())
