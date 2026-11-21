"""Research workspace: investigations and what an investigator records in them.

An investigation holds targets, sources, findings, notes and evidence. Everything here is
entered by the user; nothing in this module runs a tool or contacts a target or a source
URL. Data lives in one SQLite file, ``workspace.db`` in the data directory
(``$OPENOSINT_HOME``, default ``~/.openosint``), created owner-only like the graph store.

Sources are the single place a URL is kept: a finding or evidence entry given a
``source_url`` is linked to the investigation's source with that URL (created if new), so
the Sources list always shows every URL the findings and evidence rely on.
"""

from __future__ import annotations

import re
import sqlite3
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from openosint.paths import create_private_file, ensure_private_dir, home_dir

DB_FILENAME = "workspace.db"
SCHEMA_VERSION = 1

TARGET_KINDS = ("username", "domain", "email", "url", "ip", "phone", "other")
CONFIDENCE_LEVELS = ("low", "medium", "high")
# Keeps what was observed apart from what is inferred from it.
FINDING_KINDS = ("observation", "assumption", "conclusion")

TITLE_MAX = 200
SHORT_TEXT_MAX = 500
TEXT_MAX = 20_000
URL_MAX = 2048

_ID_RE = re.compile(r"^[0-9a-f]{32}$")
_URL_RE = re.compile(r"^https?://[^\s/?#]+[^\s]*$", re.I)
_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
_DOMAIN_RE = re.compile(r"^(?=.{1,253}$)([a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS investigations (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS targets (
    id TEXT PRIMARY KEY,
    investigation_id TEXT NOT NULL REFERENCES investigations(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    value TEXT NOT NULL,
    notes TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (investigation_id, kind, value)
);
CREATE TABLE IF NOT EXISTS sources (
    id TEXT PRIMARY KEY,
    investigation_id TEXT NOT NULL REFERENCES investigations(id) ON DELETE CASCADE,
    url TEXT NOT NULL,
    title TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (investigation_id, url)
);
CREATE TABLE IF NOT EXISTS findings (
    id TEXT PRIMARY KEY,
    investigation_id TEXT NOT NULL REFERENCES investigations(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    kind TEXT NOT NULL DEFAULT 'observation',
    confidence TEXT NOT NULL DEFAULT 'low',
    source_id TEXT REFERENCES sources(id) ON DELETE SET NULL,
    target_id TEXT REFERENCES targets(id) ON DELETE SET NULL,
    notes TEXT NOT NULL DEFAULT '',
    recorded_on TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS notes (
    id TEXT PRIMARY KEY,
    investigation_id TEXT NOT NULL REFERENCES investigations(id) ON DELETE CASCADE,
    body TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS evidence (
    id TEXT PRIMARY KEY,
    investigation_id TEXT NOT NULL REFERENCES investigations(id) ON DELETE CASCADE,
    description TEXT NOT NULL,
    source_id TEXT REFERENCES sources(id) ON DELETE SET NULL,
    target_id TEXT REFERENCES targets(id) ON DELETE SET NULL,
    finding_id TEXT REFERENCES findings(id) ON DELETE SET NULL,
    collected_on TEXT NOT NULL,
    notes TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_targets_inv ON targets(investigation_id);
CREATE INDEX IF NOT EXISTS idx_sources_inv ON sources(investigation_id);
CREATE INDEX IF NOT EXISTS idx_findings_inv ON findings(investigation_id);
CREATE INDEX IF NOT EXISTS idx_notes_inv ON notes(investigation_id);
CREATE INDEX IF NOT EXISTS idx_evidence_inv ON evidence(investigation_id);
"""

# The sections of an investigation, in display order.
SECTIONS = ("targets", "sources", "findings", "notes", "evidence")


class WorkspaceError(Exception):
    """Base error; ``status`` is the HTTP status the web API answers with."""

    status = 400


class NotFound(WorkspaceError):
    status = 404


class InvalidInput(WorkspaceError):
    status = 422


class Conflict(WorkspaceError):
    status = 409


def default_db_path() -> Path:
    return home_dir() / DB_FILENAME


def is_valid_id(value: object) -> bool:
    return isinstance(value, str) and bool(_ID_RE.match(value))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


# ---------------------------------------------------------------------------
# Field validation (shared by every entry point)
# ---------------------------------------------------------------------------


def _text(value: Any, field: str, *, max_len: int, required: bool = False) -> str:
    if value is None:
        value = ""
    if not isinstance(value, str):
        raise InvalidInput(f"{field} must be text")
    value = value.strip()
    if required and not value:
        raise InvalidInput(f"{field} is required")
    if len(value) > max_len:
        raise InvalidInput(f"{field} is longer than {max_len} characters")
    if any(ord(c) < 32 and c not in "\n\r\t" for c in value):
        raise InvalidInput(f"{field} contains control characters")
    return value


def _choice(value: Any, field: str, choices: tuple[str, ...]) -> str:
    if not isinstance(value, str) or value.strip().lower() not in choices:
        raise InvalidInput(f"{field} must be one of: {', '.join(choices)}")
    return value.strip().lower()


def validate_url(value: Any, field: str = "url", *, required: bool = True) -> str:
    """An http(s) URL, or '' when not required. Stored only; never fetched."""
    url = _text(value, field, max_len=URL_MAX, required=required)
    if not url:
        return ""
    if "\n" in url or "\r" in url or "\t" in url or not _URL_RE.match(url):
        raise InvalidInput(f"{field} must be an http:// or https:// URL")
    return url


def _date(value: Any, field: str) -> str:
    if value in (None, ""):
        return _today()
    if not isinstance(value, str) or not _DATE_RE.match(value.strip()):
        raise InvalidInput(f"{field} must be a date in YYYY-MM-DD form")
    try:
        return date.fromisoformat(value.strip()).isoformat()
    except ValueError:
        raise InvalidInput(f"{field} is not a valid date") from None


def validate_target(kind: Any, value: Any) -> tuple[str, str]:
    """Normalise a (kind, value) pair; checks the format the kind implies."""
    kind = _choice(kind, "kind", TARGET_KINDS)
    value = _text(value, "value", max_len=SHORT_TEXT_MAX, required=True)
    if "\n" in value or "\r" in value:
        raise InvalidInput("value must be on one line")
    if kind == "email":
        value = value.lower()
        if not _EMAIL_RE.match(value):
            raise InvalidInput("value is not an email address")
    elif kind == "domain":
        value = value.lower().rstrip(".")
        if not _DOMAIN_RE.match(value):
            raise InvalidInput("value is not a domain name (e.g. example.com)")
    elif kind == "url":
        value = validate_url(value, "value")
    return kind, value


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------


class WorkspaceStore:
    """One SQLite connection to workspace.db. Use as a context manager; not thread-shared."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        path = Path(db_path) if db_path is not None else default_db_path()
        if str(path) != ":memory:":
            # Same conventions as the graph store and session history: the data
            # directory is created 0700 and a new database file 0600.
            ensure_private_dir(path.parent)
            create_private_file(path)
        self._conn = sqlite3.connect(str(path))
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.execute("PRAGMA journal_mode=WAL")
        version = self._conn.execute("PRAGMA user_version").fetchone()[0]
        if version > SCHEMA_VERSION:
            self._conn.close()
            raise WorkspaceError(
                f"{path} was written by a newer OpenOSINT (schema {version}); upgrade to open it"
            )
        self._conn.executescript(_SCHEMA)
        self._conn.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> WorkspaceStore:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    # -- investigations ----------------------------------------------------

    def create_investigation(self, title: Any, description: Any = "") -> dict:
        title = _text(title, "title", max_len=TITLE_MAX, required=True)
        description = _text(description, "description", max_len=TEXT_MAX)
        inv_id, now = uuid.uuid4().hex, _now()
        with self._conn:
            self._conn.execute(
                "INSERT INTO investigations VALUES (?, ?, ?, ?, ?)",
                (inv_id, title, description, now, now),
            )
        return self.get_investigation(inv_id)

    def list_investigations(self) -> list[dict]:
        counts = {
            section: f"(SELECT COUNT(*) FROM {section} WHERE investigation_id = i.id)"
            for section in SECTIONS
        }
        rows = self._conn.execute(
            "SELECT i.*, "
            + ", ".join(f"{sql} AS {name}_count" for name, sql in counts.items())
            + " FROM investigations i ORDER BY i.updated_at DESC, i.created_at DESC"
        ).fetchall()
        out = []
        for row in rows:
            item = dict(row)
            item["counts"] = {s: item.pop(f"{s}_count") for s in SECTIONS}
            out.append(item)
        return out

    def get_investigation(self, inv_id: str) -> dict:
        row = self._conn.execute(
            "SELECT * FROM investigations WHERE id = ?", (self._id(inv_id),)
        ).fetchone()
        if row is None:
            raise NotFound("investigation not found")
        return dict(row)

    def get_workspace(self, inv_id: str) -> dict:
        """The investigation with every section, links resolved for display."""
        inv = self.get_investigation(inv_id)
        q = self._conn.execute
        inv["targets"] = [
            dict(r)
            for r in q(
                "SELECT * FROM targets WHERE investigation_id = ? ORDER BY created_at, rowid",
                (inv_id,),
            )
        ]
        inv["sources"] = [
            dict(r)
            for r in q(
                "SELECT s.*, "
                "(SELECT COUNT(*) FROM findings f WHERE f.source_id = s.id) AS finding_count, "
                "(SELECT COUNT(*) FROM evidence e WHERE e.source_id = s.id) AS evidence_count "
                "FROM sources s WHERE s.investigation_id = ? ORDER BY s.created_at, s.rowid",
                (inv_id,),
            )
        ]
        inv["findings"] = [
            dict(r)
            for r in q(
                "SELECT f.*, s.url AS source_url, t.kind AS target_kind, t.value AS target_value "
                "FROM findings f LEFT JOIN sources s ON s.id = f.source_id "
                "LEFT JOIN targets t ON t.id = f.target_id "
                "WHERE f.investigation_id = ? ORDER BY f.recorded_on DESC, f.created_at DESC",
                (inv_id,),
            )
        ]
        inv["notes"] = [
            dict(r)
            for r in q(
                "SELECT * FROM notes WHERE investigation_id = ? ORDER BY created_at DESC, rowid DESC",
                (inv_id,),
            )
        ]
        inv["evidence"] = [
            dict(r)
            for r in q(
                "SELECT e.*, s.url AS source_url, t.kind AS target_kind, t.value AS target_value, "
                "f.title AS finding_title "
                "FROM evidence e LEFT JOIN sources s ON s.id = e.source_id "
                "LEFT JOIN targets t ON t.id = e.target_id "
                "LEFT JOIN findings f ON f.id = e.finding_id "
                "WHERE e.investigation_id = ? ORDER BY e.collected_on DESC, e.created_at DESC",
                (inv_id,),
            )
        ]
        return inv

    def update_investigation(self, inv_id: str, fields: dict) -> dict:
        self.get_investigation(inv_id)
        updates: dict[str, str] = {}
        if "title" in fields:
            updates["title"] = _text(fields["title"], "title", max_len=TITLE_MAX, required=True)
        if "description" in fields:
            updates["description"] = _text(fields["description"], "description", max_len=TEXT_MAX)
        with self._conn:
            self._update_row("investigations", inv_id, updates)
        return self.get_investigation(inv_id)

    def delete_investigation(self, inv_id: str) -> None:
        with self._conn:
            cur = self._conn.execute("DELETE FROM investigations WHERE id = ?", (self._id(inv_id),))
        if cur.rowcount == 0:
            raise NotFound("investigation not found")

    # -- section items -----------------------------------------------------

    def add_item(self, inv_id: str, section: str, data: dict) -> dict:
        self.get_investigation(inv_id)
        values = self._validated(inv_id, section, data, partial=False)
        item_id, now = uuid.uuid4().hex, _now()
        values.update(id=item_id, investigation_id=inv_id, created_at=now, updated_at=now)
        cols = ", ".join(values)
        marks = ", ".join("?" for _ in values)
        with self._conn:
            try:
                self._conn.execute(
                    f"INSERT INTO {section} ({cols}) VALUES ({marks})", tuple(values.values())
                )
            except sqlite3.IntegrityError as exc:
                raise self._conflict(section) from exc
            self._touch(inv_id, now)
        return self.get_item(inv_id, section, item_id)

    def update_item(self, inv_id: str, section: str, item_id: str, data: dict) -> dict:
        self.get_item(inv_id, section, item_id)
        values = self._validated(inv_id, section, data, partial=True, item_id=item_id)
        with self._conn:
            try:
                self._update_row(section, item_id, values)
            except sqlite3.IntegrityError as exc:
                raise self._conflict(section) from exc
            self._touch(inv_id, _now())
        return self.get_item(inv_id, section, item_id)

    def delete_item(self, inv_id: str, section: str, item_id: str) -> None:
        self.get_item(inv_id, section, item_id)
        with self._conn:
            self._conn.execute(f"DELETE FROM {section} WHERE id = ?", (item_id,))
            self._touch(inv_id, _now())

    def get_item(self, inv_id: str, section: str, item_id: str) -> dict:
        self._section(section)
        self.get_investigation(inv_id)
        item = next(
            (i for i in self.get_workspace(inv_id)[section] if i["id"] == self._id(item_id)),
            None,
        )
        if item is None:
            raise NotFound(f"{section[:-1] if section != 'evidence' else 'evidence'} not found")
        return item

    # -- helpers -----------------------------------------------------------

    @staticmethod
    def _id(value: str) -> str:
        if not is_valid_id(value):
            raise NotFound("not found")
        return value

    @staticmethod
    def _section(section: str) -> str:
        if section not in SECTIONS:
            raise NotFound("unknown section")
        return section

    @staticmethod
    def _conflict(section: str) -> Conflict:
        if section == "targets":
            return Conflict("this investigation already has that target")
        if section == "sources":
            return Conflict("this investigation already has a source with that URL")
        return Conflict("conflicting entry")

    def _touch(self, inv_id: str, now: str) -> None:
        self._conn.execute("UPDATE investigations SET updated_at = ? WHERE id = ?", (now, inv_id))

    def _update_row(self, table: str, row_id: str, updates: dict) -> None:
        if not updates:
            return
        updates = dict(updates, updated_at=_now())
        assignments = ", ".join(f"{col} = ?" for col in updates)
        self._conn.execute(
            f"UPDATE {table} SET {assignments} WHERE id = ?", (*updates.values(), row_id)
        )

    def _ref(self, inv_id: str, table: str, value: Any, field: str) -> str | None:
        """An optional link to another item of the same investigation."""
        if value in (None, ""):
            return None
        if not is_valid_id(value):
            raise InvalidInput(f"{field} is not a valid id")
        row = self._conn.execute(
            f"SELECT 1 FROM {table} WHERE id = ? AND investigation_id = ?", (value, inv_id)
        ).fetchone()
        if row is None:
            raise InvalidInput(f"{field} does not belong to this investigation")
        return value

    def _source_for(self, inv_id: str, data: dict) -> str | None:
        """Resolve source_id / source_url to a source id, creating the source if new."""
        if data.get("source_id"):
            if data.get("source_url"):
                raise InvalidInput("give source_id or source_url, not both")
            return self._ref(inv_id, "sources", data["source_id"], "source_id")
        url = validate_url(data.get("source_url"), "source_url", required=False)
        if not url:
            return None
        row = self._conn.execute(
            "SELECT id FROM sources WHERE investigation_id = ? AND url = ?", (inv_id, url)
        ).fetchone()
        if row is not None:
            return row["id"]
        source_id, now = uuid.uuid4().hex, _now()
        self._conn.execute(
            "INSERT INTO sources (id, investigation_id, url, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (source_id, inv_id, url, now, now),
        )
        return source_id

    def _validated(
        self, inv_id: str, section: str, data: dict, *, partial: bool, item_id: str = ""
    ) -> dict:
        """Column values for an insert (all fields) or an update (only those given)."""
        self._section(section)
        if not isinstance(data, dict):
            raise InvalidInput("expected an object")
        has = (lambda k: k in data) if partial else (lambda k: True)
        out: dict[str, Any] = {}

        if section == "targets":
            if partial and ("kind" in data or "value" in data):
                current = self._conn.execute(
                    "SELECT kind, value FROM targets WHERE id = ?", (item_id,)
                ).fetchone()
                kind = data.get("kind", current["kind"] if current else None)
                value = data.get("value", current["value"] if current else None)
                out["kind"], out["value"] = validate_target(kind, value)
            elif not partial:
                out["kind"], out["value"] = validate_target(data.get("kind"), data.get("value"))
            if has("notes"):
                out["notes"] = _text(data.get("notes"), "notes", max_len=TEXT_MAX)

        elif section == "sources":
            if has("url"):
                out["url"] = validate_url(data.get("url"), "url")
            if has("title"):
                out["title"] = _text(data.get("title"), "title", max_len=TITLE_MAX)
            if has("notes"):
                out["notes"] = _text(data.get("notes"), "notes", max_len=TEXT_MAX)

        elif section == "findings":
            if has("title"):
                out["title"] = _text(data.get("title"), "title", max_len=TITLE_MAX, required=True)
            if has("description"):
                out["description"] = _text(data.get("description"), "description", max_len=TEXT_MAX)
            if has("kind"):
                out["kind"] = _choice(data.get("kind") or "observation", "kind", FINDING_KINDS)
            if has("confidence"):
                # Never inferred: a finding without an explicit level is recorded as low.
                out["confidence"] = _choice(
                    data.get("confidence") or "low", "confidence", CONFIDENCE_LEVELS
                )
            if has("target_id"):
                out["target_id"] = self._ref(inv_id, "targets", data.get("target_id"), "target_id")
            if has("source_id") or has("source_url"):
                out["source_id"] = self._source_for(inv_id, data)
            if has("notes"):
                out["notes"] = _text(data.get("notes"), "notes", max_len=TEXT_MAX)
            if has("recorded_on"):
                out["recorded_on"] = _date(data.get("recorded_on"), "recorded_on")

        elif section == "notes":
            if has("body"):
                out["body"] = _text(data.get("body"), "body", max_len=TEXT_MAX, required=True)

        elif section == "evidence":
            if has("description"):
                out["description"] = _text(
                    data.get("description"), "description", max_len=TEXT_MAX, required=True
                )
            if has("source_id") or has("source_url"):
                out["source_id"] = self._source_for(inv_id, data)
            if has("target_id"):
                out["target_id"] = self._ref(inv_id, "targets", data.get("target_id"), "target_id")
            if has("finding_id"):
                out["finding_id"] = self._ref(
                    inv_id, "findings", data.get("finding_id"), "finding_id"
                )
            if has("collected_on"):
                out["collected_on"] = _date(data.get("collected_on"), "collected_on")
            if has("notes"):
                out["notes"] = _text(data.get("notes"), "notes", max_len=TEXT_MAX)

        return out
