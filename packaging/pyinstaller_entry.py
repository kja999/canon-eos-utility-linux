"""PyInstaller entry point for the self-contained GUI bundle.

Kept separate from ``canon_eos_utility/__main__.py`` because PyInstaller runs the
entry script as ``__main__`` without a package context, so a relative import
would fail.
"""

from __future__ import annotations

from canon_eos_utility.app import run

if __name__ == "__main__":
    raise SystemExit(run())
