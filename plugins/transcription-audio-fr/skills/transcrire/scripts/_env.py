"""Emplacements partagés par install.py et transcribe.py.

Bibliothèque standard uniquement, compatible Python 3.9, pour pouvoir tourner
avec n'importe quel python3 avant que l'environnement dédié n'existe.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


APP = "transcription-audio-fr"
DEFAULT_MODEL = "small"
SAMPLE_RATE = 16000
NOT_INSTALLED_EXIT = 10


def data_dir() -> Path:
    """Dossier propre à l'utilisateur, hors du plugin, pour survivre à ses mises à jour."""
    override = os.environ.get("TRANSCRIPTION_FR_HOME")
    if override:
        return Path(override).expanduser()
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP
    if os.name == "nt":
        return Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))) / APP
    return Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local" / "share"))) / APP


def venv_dir() -> Path:
    return data_dir() / "venv"


def models_dir() -> Path:
    return data_dir() / "models"


def glossary_path() -> Path:
    return data_dir() / "glossaire.md"


def default_out_dir() -> Path:
    return Path.home() / "Documents" / "Transcriptions"


def venv_python() -> Path:
    if os.name == "nt":
        return venv_dir() / "Scripts" / "python.exe"
    return venv_dir() / "bin" / "python"


def running_in_venv() -> bool:
    try:
        return Path(sys.prefix).resolve() == venv_dir().resolve()
    except OSError:
        return False


def relaunch_in_venv(script: Path) -> None:
    """Relance le script avec le Python de l'environnement dédié, si ce n'est pas déjà lui."""
    if running_in_venv():
        return
    python = venv_python()
    if not python.exists():
        print(
            "L'environnement de transcription n'est pas installé. Lancer d'abord :\n"
            f'  python3 "{script.with_name("install.py")}"',
            file=sys.stderr,
        )
        sys.exit(NOT_INSTALLED_EXIT)
    completed = subprocess.run([str(python), str(script), *sys.argv[1:]])
    sys.exit(completed.returncode)
