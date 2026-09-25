"""Single executable entry point for the JaegerAgent package."""

from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] == "selfcheck":
        from .core.selfcheck import main as selfcheck_main

        return selfcheck_main(args[1:])
    if args and args[0] == "multimodal":
        args = args[1:]
    from .core.runner import main as multimodal_main

    return multimodal_main(args)


if __name__ == "__main__":
    raise SystemExit(main())
