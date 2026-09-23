"""Named settings profiles, stored as JSON files on this computer.

The mouse has no profile slots of its own. A profile holds the settings in the
same JSON form the web UI uses (see settings.config_to_json), so the files stay
readable and never carry unknown config bytes from one mouse to another.
Loading a profile writes it to the mouse like any other settings change.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

from .protocol import Config
from .settings import apply_json

PROFILE_DIR = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "xm2ctl" / "profiles"
FORMAT_VERSION = 1
NAME_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9 _-]{0,39}")


def check_name(name: object) -> str:
    """Return the stripped name, or raise ValueError if it is not a valid profile name."""
    if not isinstance(name, str) or not NAME_PATTERN.fullmatch(name.strip()):
        raise ValueError("Profile names use 1-40 letters, digits, spaces, '-' or '_'.")
    return name.strip()


def _path(name: str, directory: Path) -> Path:
    return directory / f"{check_name(name)}.json"


def list_profiles(directory: Path = PROFILE_DIR) -> list[str]:
    if not directory.is_dir():
        return []
    names = (path.stem for path in directory.glob("*.json"))
    return sorted((name for name in names if NAME_PATTERN.fullmatch(name)), key=str.lower)


def exists(name: str, directory: Path = PROFILE_DIR) -> bool:
    return _path(name, directory).is_file()


def load(name: str, directory: Path = PROFILE_DIR) -> dict:
    """Return the settings stored in a profile."""
    try:
        data = json.loads(_path(name, directory).read_text())
    except FileNotFoundError:
        raise ValueError(f"Profile '{name}' does not exist.") from None
    except json.JSONDecodeError as exc:
        raise ValueError(f"Profile '{name}' is not valid JSON: {exc}") from None
    if (not isinstance(data, dict) or data.get("format") != FORMAT_VERSION
            or not isinstance(data.get("settings"), dict)):
        raise ValueError(f"Profile '{name}' has an unknown format.")
    return data["settings"]


def load_all(directory: Path = PROFILE_DIR) -> dict[str, dict]:
    """Return {name: settings} of every readable profile, skipping broken files."""
    profiles = {}
    for name in list_profiles(directory):
        try:
            profiles[name] = load(name, directory)
        except (ValueError, OSError):
            continue
    return profiles


def save(name: str, settings: dict, directory: Path = PROFILE_DIR) -> Path:
    path = _path(name, directory)
    directory.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps({"format": FORMAT_VERSION, "settings": settings}, indent=2) + "\n")
    tmp.replace(path)
    return path


def delete(name: str, directory: Path = PROFILE_DIR) -> None:
    try:
        _path(name, directory).unlink()
    except FileNotFoundError:
        raise ValueError(f"Profile '{name}' does not exist.") from None


def apply(cfg: Config, settings: dict, wired: bool) -> list[str]:
    """Apply profile settings to cfg. Returns notes about settings that were skipped."""
    notes = []
    if wired and settings.get("polling") not in (None, cfg.polling_rate):
        notes.append(f"Polling rate {settings['polling']} Hz skipped: it can only be changed "
                     "over the wireless receiver.")
        settings = {key: value for key, value in settings.items() if key != "polling"}
    apply_json(cfg, settings, wired)
    return notes
