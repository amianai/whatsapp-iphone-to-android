#!/usr/bin/env python3
"""Entry point for the WhatsApp Migration Interactive TUI Wizard."""

import os
import sys
from pathlib import Path

project_dir = Path(__file__).resolve().parent
venv_python = project_dir / ".venv" / "bin" / "python3"
if venv_python.exists() and sys.executable != str(venv_python):
    os.execv(str(venv_python), [str(venv_python)] + sys.argv)

# Add project root to path
sys.path.insert(0, str(project_dir))

from wa_backup.tui import start_wizard

if __name__ == "__main__":
    try:
        start_wizard()
    except KeyboardInterrupt:
        print("\n\nOperación cancelada por el usuario.")
        sys.exit(0)
