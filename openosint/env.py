# openosint/env.py
"""
Single .env loader shared by every entry point (CLI, web server, MCP server).

With a regular (non-editable) `pip install openosint`, the package lives
under site-packages — anchoring purely on `__file__` resolves into
`site-packages/.env`, a path no user will ever populate. A bare
`load_dotenv()` call has the same problem for the common case, since
python-dotenv's default search starts from the caller's `__file__`, not
the cwd.

Precedence, highest first — `override=False` throughout, so the first source to
set a variable wins:
  A. real environment variables
  B. the data-directory config, `$OPENOSINT_HOME/config.env` (where the web UI
     saves keys; see openosint/config_store.py)
  C. legacy `.env` files, resolved as below
A legacy `.env` is read in place and never copied implicitly. When the package-root
one is loaded and B does not exist yet, a one-line stderr hint points at the explicit
`openosint config import`. When B and the legacy file give a variable different
values, B wins and a stderr warning names both files and the variable (never values).

Legacy `.env` resolution (first match wins), identical for every entry point:
  1. `$OPENOSINT_ENV_FILE`, if set — fail loudly on a bad path rather than
     silently loading nothing.
  2. The repo-root `.env` next to this package, for a source/editable checkout
     (under a regular pip install this resolves inside site-packages and is
     never populated).

A `.env` in the current working directory or any parent is NEVER loaded.
Loading it would hand configuration (API keys, base URLs, proxies, PATH, active
mode) to whoever wrote a file in whatever directory the command happens to be
run from: a cloned repository, an unpacked archive, a shared folder. Such a
file is only detected, never read, and a one-line stderr notice names it and
says how to use it on purpose (`OPENOSINT_ENV_FILE`, or
`openosint config import`, which defaults to that file). The
`prefer_package_root` argument is kept for API compatibility and no longer
changes anything: with the directory search gone there is only one
non-explicit location.

`[*] Loaded .env: <path>` is always printed to stderr, never stdout, in
every entry point — stdout must stay clean for the MCP protocol and for
`--json` CLI output.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import dotenv_values, find_dotenv, load_dotenv

from openosint.config_store import (
    config_path,
    legacy_candidates,
    read_config,
    shadowed_keys,
)
from openosint.settings_catalog import SAVEABLE_NAMES

_loaded_path: str | None = None
_load_attempted = False
# variable name -> "config" | "legacy", for variables a file (not the real
# environment) supplied. Lets the web UI tell a saved value from one that a real
# environment variable will override after the next restart.
_origins: dict[str, str] = {}


def value_source(name: str) -> str | None:
    """Where *name*'s current value came from: "environment", "config", "legacy" or None."""
    if not os.environ.get(name, "").strip():
        return None
    return _origins.get(name, "environment")


def mark_saved(name: str) -> None:
    """Record that *name* now holds a value this process saved to the config file.

    Without this, a key saved from the UI would later look like a real
    environment variable and block the user from changing it again.
    """
    _origins[name] = "config"


def _load_file(path: str | Path, origin: str) -> None:
    before = set(os.environ)
    load_dotenv(dotenv_path=path, override=False)
    for name in set(os.environ) - before:
        _origins[name] = origin


def _resolve_path(*, prefer_package_root: bool = False) -> str:
    """The legacy .env to load: $OPENOSINT_ENV_FILE, else the repo-root .env, else "".

    Never searches the working directory (see the module docstring).
    `prefer_package_root` is accepted for compatibility and has no effect.
    """
    explicit = os.environ.get("OPENOSINT_ENV_FILE", "").strip()
    if explicit:
        if not Path(explicit).is_file():
            raise FileNotFoundError(f"OPENOSINT_ENV_FILE={explicit!r} does not exist.")
        return explicit

    repo_root_env = Path(__file__).resolve().parent.parent / ".env"
    if repo_root_env.is_file():
        return str(repo_root_env)
    return ""


def ignored_working_dir_env() -> Path | None:
    """The nearest `.env` in the working directory or a parent that is NOT loaded.

    Detection only: the file's existence is checked, its contents are never read
    here. Returns None when there is no such file, or when it is the same file
    load_env() loaded on purpose (e.g. running from the repo root, or
    OPENOSINT_ENV_FILE pointing at it).
    """
    try:
        found = find_dotenv(usecwd=True)
    except OSError:  # e.g. the working directory was deleted: nothing to report
        return None
    if not found:
        return None
    path = Path(found)
    if _loaded_path and path.resolve() == Path(_loaded_path).resolve():
        return None
    return path


def _notice_ignored_working_dir_env(config_file: Path) -> None:
    ignored = ignored_working_dir_env()
    if ignored is None:
        return
    print(
        f"[!] Not loading {ignored}: .env files in the working directory or its parents "
        "are no longer read automatically. To use it on purpose, set "
        f"OPENOSINT_ENV_FILE={ignored} or run `openosint config import` to copy its "
        f"keys into {config_file}.",
        file=sys.stderr,
    )


def _hint_import(legacy: Path, config_file: Path) -> None:
    count = len(legacy_candidates(legacy, SAVEABLE_NAMES))
    if count:
        print(
            f"[*] {count} setting(s) in {legacy} are not saved to {config_file} "
            "(not copied automatically). Run `openosint config import` to copy them.",
            file=sys.stderr,
        )


def _warn_shadowed(config_file: Path, legacy: Path, preset: set[str]) -> None:
    """Warn, by name only, about variables where config.env silently beats the .env."""
    if not config_file.is_file():
        return
    try:
        legacy_values = {k: v for k, v in dotenv_values(legacy).items() if v is not None}
    except OSError:
        return
    names = [k for k in shadowed_keys(read_config(), legacy_values) if k not in preset]
    if names:
        print(
            f"[!] {config_file} overrides {legacy} for {', '.join(names)}: the two files "
            f"hold different values and the {config_file.name} one is used. Update or remove "
            "that entry in config.env if the .env value is the one you want.",
            file=sys.stderr,
        )


def loaded_env_path() -> Path | None:
    """The legacy .env that load_env() picked, if any (no loading is triggered)."""
    return Path(_loaded_path) if _loaded_path else None


def load_env(*, prefer_package_root: bool = False) -> Path | None:
    """Load `.env` once per process and return the path loaded, or None.

    Safe to call from multiple entry points/functions — every call after
    the first is a no-op that returns the cached result, so the banner
    line below is never printed twice for one process. `prefer_package_root`
    is kept for compatibility and has no effect — see the module docstring.

    Raises FileNotFoundError if `$OPENOSINT_ENV_FILE` is set but points at
    a nonexistent path — see `load_env_or_exit()` for the CLI-friendly
    wrapper every entry point should call instead of this directly.
    """
    global _loaded_path, _load_attempted
    if _load_attempted:
        return Path(_loaded_path) if _loaded_path else None

    path = _resolve_path(prefer_package_root=prefer_package_root)

    config_file = config_path()
    package_env = Path(__file__).resolve().parent.parent / ".env"
    preset = {name for name, value in os.environ.items() if value.strip()}

    # Config first: with override=False the first loader to set a variable wins,
    # so this is what puts it above every legacy .env.
    config_exists = config_file.is_file()
    if config_exists:
        _load_file(config_file, "config")
        print(f"[*] Loaded config: {config_file}", file=sys.stderr)

    if path:
        _load_file(path, "legacy")
        print(f"[*] Loaded .env: {path}", file=sys.stderr)
        _warn_shadowed(config_file, Path(path), preset)
        if not config_exists and Path(path).resolve() == package_env.resolve():
            _hint_import(Path(path), config_file)

    _loaded_path = path or None
    _load_attempted = True
    _notice_ignored_working_dir_env(config_file)
    return Path(_loaded_path) if _loaded_path else None


def load_env_or_exit(*, prefer_package_root: bool = False) -> Path | None:
    """`load_env()`, but a bad `$OPENOSINT_ENV_FILE` exits cleanly instead of
    raising.  Every entry point (CLI, MCP server, web server) should call
    this instead of `load_env()` directly, so a missing env file always
    produces one `[!] ...` line on stderr and `exit(2)` — never a traceback.
    """
    try:
        return load_env(prefer_package_root=prefer_package_root)
    except FileNotFoundError as exc:
        print(f"[!] {exc}", file=sys.stderr)
        raise SystemExit(2) from None


def missing_var_clause(var_name: str) -> str:
    """ "<var> environment variable is not set (...)." with no "Scan error:" prefix.

    For a tool that raises/returns its own message and lets a caller add
    that prefix when wrapping the error (see search_breach.py) — use
    missing_var_message() instead when returning the error directly.
    """
    if _load_attempted:
        # load_env() already ran (every entry point calls it before
        # importing tool modules) — report what it actually found, so this
        # matches the MCP server's swapped cwd/repo-root priority instead
        # of silently recomputing with the CLI/web default order.
        path = _loaded_path or ""
    else:
        try:
            path = _resolve_path()
        except FileNotFoundError:
            path = ""

    if path:
        hint = f".env loaded from {path}, but it doesn't set this variable"
    else:
        hint = (
            f"no .env loaded; a .env in {os.getcwd()} or its parents is not read "
            "automatically. Set OPENOSINT_ENV_FILE or export the variable"
        )
    return f"{var_name} environment variable is not set ({hint})."


def missing_var_message(var_name: str) -> str:
    """Standard "Scan error: <var> is not set (...)" sentence for a missing key.

    Used by every OSINT tool that requires a credential, so the hint about
    where .env was (or wasn't) found is consistent everywhere instead of
    being retyped per tool.
    """
    return f"Scan error: {missing_var_clause(var_name)}"
