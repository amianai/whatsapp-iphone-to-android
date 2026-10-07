#!/usr/bin/env python3
"""Convenience alias for wa-fuse interactive wizard."""

import os
import sys
from pathlib import Path

project_dir = Path(__file__).resolve().parent
venv_python = project_dir / ".venv" / "bin" / "python3"
if venv_python.exists() and sys.executable != str(venv_python):
    os.execv(str(venv_python), [str(venv_python)] + sys.argv)

sys.path.insert(0, str(project_dir))

from wa_fuse.tui import start_wizard

if __name__ == "__main__":
    lang = None
    for idx, arg in enumerate(sys.argv):
        if arg in ("--lang", "-l") and idx + 1 < len(sys.argv):
            lang = sys.argv[idx + 1]
            break
        elif arg.startswith("--lang="):
            lang = arg.split("=", 1)[1]
            break

    try:
        start_wizard(lang=lang)
    except KeyboardInterrupt:
        print("\n\nOperation cancelled / Operación cancelada.")
        sys.exit(0)
