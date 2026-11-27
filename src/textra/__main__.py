"""``python -m textra`` behaves exactly like the installed ``textra`` command."""

from __future__ import annotations

from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
