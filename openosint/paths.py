"""Where OpenOSINT keeps its persistent data (graph.db, session history)."""

from __future__ import annotations

import os
from pathlib import Path

# Investigation data (history, graph) is readable by its owner only. Applied when
# OpenOSINT creates a directory or file; existing ones keep their mode (changing it
# silently could break a setup that shares them on purpose — `openosint config import`
# offers to tighten an exposed data directory).
PRIVATE_DIR_MODE = 0o700
PRIVATE_FILE_MODE = 0o600


def home_dir() -> Path:
    """$OPENOSINT_HOME if set, else ~/.openosint. Not created here."""
    override = os.environ.get("OPENOSINT_HOME", "").strip()
    return Path(override).expanduser() if override else Path.home() / ".openosint"


def ensure_private_dir(path: Path) -> Path:
    """Create *path* and any missing parents as owner-only (0700); existing ones untouched.

    ``Path.mkdir(parents=True, mode=…)`` applies the mode to the last directory only,
    so a missing data home (e.g. ~/.openosint when history is written first) would get
    the umask default; each missing level is created explicitly instead.
    """
    path = Path(path)
    missing = []
    for candidate in (path, *path.parents):
        if candidate.exists():
            break
        missing.append(candidate)
    for directory in reversed(missing):
        try:
            directory.mkdir(mode=PRIVATE_DIR_MODE)
        except FileExistsError:  # created concurrently: leave its mode alone
            pass
    return path


def create_private_file(path: Path) -> bool:
    """Create *path* empty with owner-only permissions (0600) if it does not exist.

    Returns True if it was created. An existing file is left as it is.
    """
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, PRIVATE_FILE_MODE)
    except FileExistsError:
        return False
    os.close(fd)
    return True
