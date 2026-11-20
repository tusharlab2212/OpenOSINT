# openosint/utils.py
"""
Shared utility functions for OpenOSINT tool modules.

run_subprocess() centralises the asyncio subprocess execution pattern
(binary check → create_subprocess_exec → wait_for → kill on timeout)
that all binary-based OSINT tool wrappers share.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import shutil
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import NamedTuple

from openosint.tools.exceptions import (
    ToolExecutionError,
    ToolNotFoundError,
    ToolTimeoutError,
)

# Environment passed to external programs (holehe, sherlock, sublist3r, phoneinfoga).
# Allowlist, compared upper-cased: what a process needs to start and reach the network
# (proxy and CA-bundle variables, so proxy mode and corporate TLS keep working).
# Everything else — API keys, OPENOSINT_* settings, PYTHONPATH/PYTHONSTARTUP — stays
# out of third-party code that has no use for it.
_CHILD_ENV_ALLOW: frozenset[str] = frozenset(
    {
        "PATH", "HOME", "USER", "LOGNAME", "SHELL", "LANG", "LANGUAGE", "TZ", "TERM",
        "TMPDIR", "TEMP", "TMP",
        "XDG_CONFIG_HOME", "XDG_CACHE_HOME", "XDG_DATA_HOME", "VIRTUAL_ENV",
        "PYTHONIOENCODING", "PYTHONUTF8",
        # Windows: a process cannot start, or find its profile, without these.
        "SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT", "SYSTEMDRIVE", "USERPROFILE",
        "APPDATA", "LOCALAPPDATA", "HOMEDRIVE", "HOMEPATH", "PROGRAMDATA",
        # Network: proxies and trusted CAs.
        "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY",
        "SSL_CERT_FILE", "SSL_CERT_DIR", "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE",
    }
)  # fmt: skip
_CHILD_ENV_ALLOW_PREFIXES: tuple[str, ...] = ("LC_",)

_MAX_TARGET_CHARS = 256


def child_env(base: Mapping[str, str] | None = None) -> dict[str, str]:
    """The environment an external program gets: *base* (default os.environ) filtered
    to ``_CHILD_ENV_ALLOW``. Proxy variables in *base* (see proxy.get_subprocess_env)
    are kept."""
    source = os.environ if base is None else base
    return {
        name: value
        for name, value in source.items()
        if name.upper() in _CHILD_ENV_ALLOW or name.upper().startswith(_CHILD_ENV_ALLOW_PREFIXES)
    }


def validate_cli_target(value: str, kind: str) -> str:
    """Check a target before it becomes a command-line argument of an external program.

    Returns it stripped. Raises ToolExecutionError for an empty value, one starting with
    "-" (the program would read it as an option: argument injection), control
    characters, or more than ``_MAX_TARGET_CHARS`` characters.
    """
    text = str(value).strip()
    if not text:
        raise ToolExecutionError(f"The {kind} is empty.")
    if text.startswith("-"):
        raise ToolExecutionError(
            f"Refusing {kind} {text[:40]!r}: a value starting with '-' would be read as a "
            "program option."
        )
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in text):
        raise ToolExecutionError(f"Refusing {kind}: it contains control characters.")
    if len(text) > _MAX_TARGET_CHARS:
        raise ToolExecutionError(f"Refusing {kind}: longer than {_MAX_TARGET_CHARS} characters.")
    return text

logger = logging.getLogger(__name__)


# Upstream banners, social and donation lines, and promotions that a wrapped CLI prints
# around its results. They are not findings: left in, they reach the model and the user as
# if the tool had reported them. Credit to the tool is OpenOSINT's own attribution_line().
_PROMO_LINE_RE = re.compile(
    r"go deeper than a username"  # sherlock -> OSINTSearch
    r"|try osintsearch"  # sherlock -> OSINTSearch
    r"|^twitter\s*:"  # holehe credit
    r"|^github\s*:"  # holehe credit
    r"|^for btc donations"  # holehe donation address
    r"|coded by ahmed aboul-ela",  # sublist3r banner
    re.IGNORECASE,
)

_UPSTREAM_URLS = {
    "sherlock": "https://github.com/sherlock-project/sherlock",
    "holehe": "https://github.com/megadose/holehe",
    "sublist3r": "https://github.com/aboul3la/Sublist3r",
}


def strip_promotions(raw: str) -> str:
    """Drop upstream banner, social, donation and promotion lines from a wrapped tool's stdout."""
    kept = [line for line in raw.splitlines() if not _PROMO_LINE_RE.search(line.strip())]
    return "\n".join(kept).strip()


def attribution_line(tool: str) -> str:
    """OpenOSINT's own credit line for the open-source tool behind a result."""
    return f"Results via {tool} ({_UPSTREAM_URLS[tool]})"


class SubprocessResult(NamedTuple):
    """Result of a completed external subprocess call."""

    stdout: str
    stderr: str
    return_code: int


def find_binary(binary: str) -> str | None:
    """Resolve *binary* the way tools run it: this interpreter's bin dir, then PATH.

    The interpreter's own bin dir comes first so console scripts installed next
    to OpenOSINT (a venv, or the environment `uvx` builds) are found without
    being on the user's PATH.
    """
    venv_bin = str(Path(sys.executable).parent)
    return shutil.which(binary, path=os.pathsep.join([venv_bin, os.environ.get("PATH", "")]))


async def run_subprocess(
    binary: str,
    args: list[str],
    timeout_seconds: int,
    install_hint: str = "",
    env: dict[str, str] | None = None,
) -> SubprocessResult:
    """
    Execute an external binary asynchronously and return its output.

    Parameters
    ----------
    binary:
        Executable name discoverable via PATH.
    args:
        Arguments forwarded to the binary.
    timeout_seconds:
        Hard wall-clock limit; process is killed on expiry.
    install_hint:
        Short installation message appended to ToolNotFoundError.
    env:
        Base environment for the child process; None (default) means the current
        process environment. Either way it is filtered by child_env(): the child
        never receives API keys or other unrelated variables.

    Raises
    ------
    ToolNotFoundError
        When the binary is absent from PATH.
    ToolTimeoutError
        When the process exceeds timeout_seconds.
    """
    resolved = find_binary(binary)
    if not resolved:
        detail = f" {install_hint}" if install_hint else ""
        raise ToolNotFoundError(f"'{binary}' is not installed or not in PATH.{detail}")
    binary = resolved

    process: asyncio.subprocess.Process | None = None
    try:
        process = await asyncio.create_subprocess_exec(
            binary,
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=child_env(env),
        )
        raw_stdout, raw_stderr = await asyncio.wait_for(
            process.communicate(),
            timeout=float(timeout_seconds),
        )
        return SubprocessResult(
            stdout=raw_stdout.decode("utf-8", errors="replace").strip(),
            stderr=raw_stderr.decode("utf-8", errors="replace").strip(),
            return_code=process.returncode or 0,
        )
    except asyncio.TimeoutError:
        _kill_process(process)
        raise ToolTimeoutError(f"'{binary}' scan timed out after {timeout_seconds}s.")


def _kill_process(process: asyncio.subprocess.Process | None) -> None:
    """Terminate a subprocess, ignoring errors if it already exited."""
    if process is None:
        return
    try:
        process.kill()
    except ProcessLookupError:
        pass
