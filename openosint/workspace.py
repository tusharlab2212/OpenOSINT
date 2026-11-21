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
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from openosint.paths import create_private_file, ensure_private_dir, home_dir

DB_FILENAME = "workspace.db"
SCHEMA_VERSION = 4

TARGET_KINDS = ("username", "domain", "email", "url", "ip", "phone", "other")
CONFIDENCE_LEVELS = ("low", "medium", "high")
# Provenance of a finding: what you saw yourself, what a source says, what you take as
# given, and what you infer. Keeps observed facts apart from claims and inferences.
FINDING_KINDS = ("observation", "reported", "assumption", "conclusion")
# Provenance of an evidence entry. Entries saved before schema 2 are "unspecified": the
# migration does not guess.
EVIDENCE_KINDS = ("unspecified", "observation", "reported")
SOURCE_TYPES = (
    "unspecified",
    "website",
    "social_media",
    "news",
    "government",
    "company",
    "court_record",
    "dataset",
    "archive",
    "document",
    "other",
)
# Source reliability on the A-F scale used in intelligence source grading. Always assigned
# by the investigator, with a written rationale; never set or changed by OpenOSINT.
RELIABILITY_RATINGS = ("unassessed", "A", "B", "C", "D", "E", "F")
# Entity relationship graph (schema 3). Everything in it is entered by the investigator:
# nothing creates an entity or asserts a relationship on its own.
ENTITY_KINDS = (
    "person",
    "organization",
    "username",
    "domain",
    "email",
    "phone",
    "ip",
    "location",
    "custom",
)
# A relationship is a documented fact only when the investigator says so and cites a
# finding or evidence for it; otherwise it is a hypothesis.
RELATIONSHIP_STATUSES = ("hypothesis", "documented")
# Suggestions for the relationship label; any other text is accepted.
RELATIONSHIP_PRESETS = (
    "owns",
    "operates",
    "works for",
    "member of",
    "uses",
    "registered",
    "hosted on",
    "linked to",
    "same as",
    "communicated with",
    "located in",
)
POSITION_LIMIT = 1_000_000.0

# Timeline (schema 4). Events and correlations are entered by the investigator; nothing
# dates, orders, links or correlates events on its own, and nothing marks one verified.
EVENT_CATEGORIES = (
    "communication",
    "registration",
    "publication",
    "account_activity",
    "infrastructure_change",
    "transaction",
    "meeting",
    "travel",
    "legal",
    "other",
)
# Where an event comes from. There is no "verified": the strongest statement is that the
# investigator observed it in a source themselves.
EVENT_PROVENANCE = ("reported", "observation", "hypothesis", "conclusion")
# exact: the date (and time) as given; approximate: around then (year or month allowed);
# range: from start to end.
DATE_PRECISIONS = ("exact", "approximate", "range")
# What an event can be linked to (kind -> table).
EVENT_LINK_KINDS = {
    "target": "targets",
    "entity": "entities",
    "finding": "findings",
    "evidence": "evidence",
    "source": "sources",
}
CORRELATION_STATUSES = ("hypothesis", "documented")
MAX_LINKS = 100
_TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
_OFFSET_RE = re.compile(r"^(?:UTC)?([+-])(0\d|1[0-4]):([0-5]\d)$")
_PARTIAL_DATE_RE = re.compile(r"^\d{4}(-\d{2}(-\d{2})?)?$")

RELIABILITY_LABELS = {
    "unassessed": "Not assessed",
    "A": "Completely reliable",
    "B": "Usually reliable",
    "C": "Fairly reliable",
    "D": "Not usually reliable",
    "E": "Unreliable",
    "F": "Reliability cannot be judged",
}

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
    source_type TEXT NOT NULL DEFAULT 'unspecified',
    original_url TEXT NOT NULL DEFAULT '',
    published_on TEXT NOT NULL DEFAULT '',
    accessed_on TEXT NOT NULL DEFAULT '',
    reliability TEXT NOT NULL DEFAULT 'unassessed',
    reliability_rationale TEXT NOT NULL DEFAULT '',
    reliability_assessed_on TEXT NOT NULL DEFAULT '',
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
    updated_at TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'unspecified'
);
CREATE INDEX IF NOT EXISTS idx_targets_inv ON targets(investigation_id);
CREATE INDEX IF NOT EXISTS idx_sources_inv ON sources(investigation_id);
CREATE INDEX IF NOT EXISTS idx_findings_inv ON findings(investigation_id);
CREATE INDEX IF NOT EXISTS idx_notes_inv ON notes(investigation_id);
CREATE INDEX IF NOT EXISTS idx_evidence_inv ON evidence(investigation_id);
CREATE TABLE IF NOT EXISTS entities (
    id TEXT PRIMARY KEY,
    investigation_id TEXT NOT NULL REFERENCES investigations(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    label TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    target_id TEXT REFERENCES targets(id) ON DELETE SET NULL,
    pos_x REAL,
    pos_y REAL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS relationships (
    id TEXT PRIMARY KEY,
    investigation_id TEXT NOT NULL REFERENCES investigations(id) ON DELETE CASCADE,
    from_entity_id TEXT NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    to_entity_id TEXT NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    label TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'hypothesis',
    confidence TEXT NOT NULL DEFAULT 'low',
    description TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    recorded_by TEXT NOT NULL DEFAULT '',
    finding_id TEXT REFERENCES findings(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS relationship_evidence (
    relationship_id TEXT NOT NULL REFERENCES relationships(id) ON DELETE CASCADE,
    evidence_id TEXT NOT NULL REFERENCES evidence(id) ON DELETE CASCADE,
    PRIMARY KEY (relationship_id, evidence_id)
);
CREATE INDEX IF NOT EXISTS idx_entities_inv ON entities(investigation_id);
CREATE INDEX IF NOT EXISTS idx_relationships_inv ON relationships(investigation_id);
CREATE INDEX IF NOT EXISTS idx_rel_evidence_ev ON relationship_evidence(evidence_id);
CREATE TABLE IF NOT EXISTS events (
    id TEXT PRIMARY KEY,
    investigation_id TEXT NOT NULL REFERENCES investigations(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    category TEXT NOT NULL DEFAULT 'other',
    provenance TEXT NOT NULL DEFAULT 'hypothesis',
    date_precision TEXT NOT NULL DEFAULT 'exact',
    start_date TEXT NOT NULL,
    start_time TEXT NOT NULL DEFAULT '',
    end_date TEXT NOT NULL DEFAULT '',
    end_time TEXT NOT NULL DEFAULT '',
    timezone TEXT NOT NULL DEFAULT '',
    sort_key TEXT NOT NULL,
    notes TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS event_links (
    event_id TEXT NOT NULL REFERENCES events(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    item_id TEXT NOT NULL,
    PRIMARY KEY (event_id, kind, item_id)
);
CREATE TABLE IF NOT EXISTS correlations (
    id TEXT PRIMARY KEY,
    investigation_id TEXT NOT NULL REFERENCES investigations(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    explanation TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'hypothesis',
    confidence TEXT NOT NULL DEFAULT 'low',
    finding_id TEXT REFERENCES findings(id) ON DELETE SET NULL,
    notes TEXT NOT NULL DEFAULT '',
    recorded_by TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS correlation_events (
    correlation_id TEXT NOT NULL REFERENCES correlations(id) ON DELETE CASCADE,
    event_id TEXT NOT NULL REFERENCES events(id) ON DELETE CASCADE,
    PRIMARY KEY (correlation_id, event_id)
);
CREATE TABLE IF NOT EXISTS correlation_evidence (
    correlation_id TEXT NOT NULL REFERENCES correlations(id) ON DELETE CASCADE,
    evidence_id TEXT NOT NULL REFERENCES evidence(id) ON DELETE CASCADE,
    PRIMARY KEY (correlation_id, evidence_id)
);
CREATE INDEX IF NOT EXISTS idx_events_inv ON events(investigation_id, sort_key);
CREATE INDEX IF NOT EXISTS idx_event_links_item ON event_links(item_id);
CREATE INDEX IF NOT EXISTS idx_correlations_inv ON correlations(investigation_id);
CREATE INDEX IF NOT EXISTS idx_corr_events_ev ON correlation_events(event_id);
"""

# Columns added in schema 2. A schema-1 database gets them with their defaults; every
# existing value is kept as it was.
_V2_COLUMNS = (
    ("sources", "source_type", "TEXT NOT NULL DEFAULT 'unspecified'"),
    ("sources", "original_url", "TEXT NOT NULL DEFAULT ''"),
    ("sources", "published_on", "TEXT NOT NULL DEFAULT ''"),
    ("sources", "accessed_on", "TEXT NOT NULL DEFAULT ''"),
    ("sources", "reliability", "TEXT NOT NULL DEFAULT 'unassessed'"),
    ("sources", "reliability_rationale", "TEXT NOT NULL DEFAULT ''"),
    ("sources", "reliability_assessed_on", "TEXT NOT NULL DEFAULT ''"),
    ("evidence", "kind", "TEXT NOT NULL DEFAULT 'unspecified'"),
)

# The sections of an investigation, in display order.
SECTIONS = ("targets", "sources", "findings", "notes", "evidence")
# The graph's sections (schema 3). Kept apart so investigation counts stay as they were.
GRAPH_SECTIONS = ("entities", "relationships")
# The timeline's sections (schema 4).
TIMELINE_SECTIONS = ("events", "correlations")
ALL_SECTIONS = SECTIONS + GRAPH_SECTIONS + TIMELINE_SECTIONS


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


def _date(value: Any, field: str, *, optional: bool = False) -> str:
    """A YYYY-MM-DD date. Empty means today, or stays empty when *optional*."""
    if value in (None, ""):
        return "" if optional else _today()
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
        self._migrate()
        self._conn.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
        self._conn.commit()

    def _migrate(self) -> None:
        """Add columns missing from an older database. Idempotent; never rewrites data."""
        for table, column, decl in _V2_COLUMNS:
            existing = {r["name"] for r in self._conn.execute(f"PRAGMA table_info({table})")}
            if column not in existing:
                self._conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")

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
            for section in ALL_SECTIONS
        }
        rows = self._conn.execute(
            "SELECT i.*, "
            + ", ".join(f"{sql} AS {name}_count" for name, sql in counts.items())
            + " FROM investigations i ORDER BY i.updated_at DESC, i.created_at DESC"
        ).fetchall()
        out = []
        for row in rows:
            item = dict(row)
            item["counts"] = {s: item.pop(f"{s}_count") for s in ALL_SECTIONS}
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
                "SELECT f.*, s.url AS source_url, s.title AS source_title, "
                "s.reliability AS source_reliability, "
                "t.kind AS target_kind, t.value AS target_value "
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
                "SELECT e.*, s.url AS source_url, s.title AS source_title, "
                "s.reliability AS source_reliability, "
                "t.kind AS target_kind, t.value AS target_value, f.title AS finding_title "
                "FROM evidence e LEFT JOIN sources s ON s.id = e.source_id "
                "LEFT JOIN targets t ON t.id = e.target_id "
                "LEFT JOIN findings f ON f.id = e.finding_id "
                "WHERE e.investigation_id = ? ORDER BY e.collected_on DESC, e.created_at DESC",
                (inv_id,),
            )
        ]
        _link_traces(inv)
        inv["entities"] = [
            dict(r)
            for r in q(
                "SELECT en.*, t.kind AS target_kind, t.value AS target_value, "
                "(SELECT COUNT(*) FROM relationships r "
                " WHERE r.from_entity_id = en.id OR r.to_entity_id = en.id) AS relationship_count "
                "FROM entities en LEFT JOIN targets t ON t.id = en.target_id "
                "WHERE en.investigation_id = ? ORDER BY en.created_at, en.rowid",
                (inv_id,),
            )
        ]
        inv["relationships"] = [
            dict(r)
            for r in q(
                "SELECT r.*, a.label AS from_label, a.kind AS from_kind, "
                "b.label AS to_label, b.kind AS to_kind, f.title AS finding_title, "
                "f.kind AS finding_kind "
                "FROM relationships r JOIN entities a ON a.id = r.from_entity_id "
                "JOIN entities b ON b.id = r.to_entity_id "
                "LEFT JOIN findings f ON f.id = r.finding_id "
                "WHERE r.investigation_id = ? ORDER BY r.created_at, r.rowid",
                (inv_id,),
            )
        ]
        links: dict[str, list[str]] = {}
        for row in q(
            "SELECT re.relationship_id, re.evidence_id FROM relationship_evidence re "
            "JOIN relationships r ON r.id = re.relationship_id WHERE r.investigation_id = ?",
            (inv_id,),
        ):
            links.setdefault(row["relationship_id"], []).append(row["evidence_id"])
        evidence = {e["id"]: e for e in inv["evidence"]}
        for rel in inv["relationships"]:
            ids = [i for i in links.get(rel["id"], []) if i in evidence]
            ids.sort(key=lambda i: (evidence[i]["collected_on"], evidence[i]["created_at"]))
            rel["evidence_ids"] = ids
            # A documented relationship whose cited finding and evidence were all deleted is
            # flagged, not silently downgraded: the investigator decides what it is now.
            rel["unsupported"] = rel["status"] == "documented" and not rel["finding_id"] and not ids
        for e in inv["evidence"]:
            e["relationship_ids"] = [
                r["id"] for r in inv["relationships"] if e["id"] in r["evidence_ids"]
            ]
        self._add_timeline(inv)
        return inv

    def _add_timeline(self, inv: dict) -> None:
        """Events (chronological) with their resolved links, and correlations."""
        q = self._conn.execute
        inv_id = inv["id"]
        inv["events"] = [
            dict(r)
            for r in q(
                "SELECT * FROM events WHERE investigation_id = ? "
                "ORDER BY sort_key, created_at, rowid",
                (inv_id,),
            )
        ]
        labels = {
            "target": {t["id"]: f"{t['kind']}: {t['value']}" for t in inv["targets"]},
            "entity": {e["id"]: e["label"] for e in inv["entities"]},
            "finding": {f["id"]: f["title"] for f in inv["findings"]},
            "evidence": {e["id"]: e["description"][:120] for e in inv["evidence"]},
            "source": {s["id"]: s["title"] or s["url"] for s in inv["sources"]},
        }
        links: dict[str, list[dict]] = {}
        for row in q(
            "SELECT l.event_id, l.kind, l.item_id FROM event_links l "
            "JOIN events ev ON ev.id = l.event_id WHERE ev.investigation_id = ? "
            "ORDER BY l.kind, l.rowid",
            (inv_id,),
        ):
            label = labels.get(row["kind"], {}).get(row["item_id"])
            if label is not None:  # a link to a deleted item is not shown
                links.setdefault(row["event_id"], []).append(
                    {"kind": row["kind"], "id": row["item_id"], "label": label}
                )
        for ev in inv["events"]:
            ev["links"] = links.get(ev["id"], [])
        inv["correlations"] = [
            dict(r)
            for r in q(
                "SELECT c.*, f.title AS finding_title FROM correlations c "
                "LEFT JOIN findings f ON f.id = c.finding_id "
                "WHERE c.investigation_id = ? ORDER BY c.created_at, c.rowid",
                (inv_id,),
            )
        ]
        order = {ev["id"]: i for i, ev in enumerate(inv["events"])}
        evidence = {e["id"] for e in inv["evidence"]}
        members: dict[str, list[str]] = {}
        cited: dict[str, list[str]] = {}
        for row in q(
            "SELECT ce.correlation_id, ce.event_id FROM correlation_events ce "
            "JOIN correlations c ON c.id = ce.correlation_id WHERE c.investigation_id = ?",
            (inv_id,),
        ):
            members.setdefault(row["correlation_id"], []).append(row["event_id"])
        for row in q(
            "SELECT ce.correlation_id, ce.evidence_id FROM correlation_evidence ce "
            "JOIN correlations c ON c.id = ce.correlation_id WHERE c.investigation_id = ?",
            (inv_id,),
        ):
            cited.setdefault(row["correlation_id"], []).append(row["evidence_id"])
        for c in inv["correlations"]:
            c["event_ids"] = sorted(
                (i for i in members.get(c["id"], []) if i in order), key=order.__getitem__
            )
            c["evidence_ids"] = [i for i in cited.get(c["id"], []) if i in evidence]
            # Flags, never silent changes: the investigator decides what the correlation is now.
            c["incomplete"] = len(c["event_ids"]) < 2
            c["unsupported"] = (
                c["status"] == "documented" and not c["finding_id"] and not c["evidence_ids"]
            )
        for ev in inv["events"]:
            ev["correlation_ids"] = [
                c["id"] for c in inv["correlations"] if ev["id"] in c["event_ids"]
            ]

    def trace_relationship(self, inv_id: str, relationship_id: str) -> dict:
        """A relationship with its two entities, its finding and its evidence (with sources)."""
        inv = self.get_workspace(inv_id)
        rel = _find(inv["relationships"], relationship_id, "relationship")
        entities = {e["id"]: e for e in inv["entities"]}
        findings = {f["id"]: f for f in inv["findings"]}
        sources = {s["id"]: s for s in inv["sources"]}
        evidence = {e["id"]: e for e in inv["evidence"]}
        return {
            "relationship": rel,
            "from_entity": entities[rel["from_entity_id"]],
            "to_entity": entities[rel["to_entity_id"]],
            "finding": findings.get(rel["finding_id"]),
            "evidence": [
                dict(evidence[i], source=sources.get(evidence[i]["source_id"]))
                for i in rel["evidence_ids"]
            ],
        }

    def trace_source(self, inv_id: str, source_id: str) -> dict:
        """What relies on a source: findings citing it, its evidence, findings that evidence supports."""
        inv = self.get_workspace(inv_id)
        source = _find(inv["sources"], source_id, "source")
        findings = {f["id"]: f for f in inv["findings"]}
        evidence = [e for e in inv["evidence"] if e["source_id"] == source["id"]]
        via = [
            findings[i] for i in source["supported_finding_ids"] if i not in source["finding_ids"]
        ]
        return {
            "source": source,
            "findings": [findings[i] for i in source["finding_ids"]],
            "evidence": evidence,
            "findings_via_evidence": via,
        }

    def trace_finding(self, inv_id: str, finding_id: str) -> dict:
        """What a finding rests on: its own source and the evidence linked to it, with theirs."""
        inv = self.get_workspace(inv_id)
        finding = _find(inv["findings"], finding_id, "finding")
        sources = {s["id"]: s for s in inv["sources"]}
        evidence = [e for e in inv["evidence"] if e["finding_id"] == finding["id"]]
        return {
            "finding": finding,
            "source": sources.get(finding["source_id"]),
            "evidence": [dict(e, source=sources.get(e["source_id"])) for e in evidence],
        }

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
        evidence_ids = values.pop("_evidence_ids", None)
        link_sets = values.pop("_links", None)
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
            if evidence_ids is not None:
                self._set_relationship_evidence(item_id, evidence_ids)
            self._write_links(item_id, link_sets)
            self._touch(inv_id, now)
        return self.get_item(inv_id, section, item_id)

    def update_item(self, inv_id: str, section: str, item_id: str, data: dict) -> dict:
        self.get_item(inv_id, section, item_id)
        values = self._validated(inv_id, section, data, partial=True, item_id=item_id)
        evidence_ids = values.pop("_evidence_ids", None)
        link_sets = values.pop("_links", None)
        with self._conn:
            try:
                self._update_row(section, item_id, values)
            except sqlite3.IntegrityError as exc:
                raise self._conflict(section) from exc
            if evidence_ids is not None:
                self._set_relationship_evidence(item_id, evidence_ids)
            self._write_links(item_id, link_sets)
            self._touch(inv_id, _now())
        return self.get_item(inv_id, section, item_id)

    def set_entity_position(self, inv_id: str, entity_id: str, x: Any, y: Any) -> dict:
        """Save where an entity sits on the graph. Layout only: no investigation timestamp."""
        self.get_item(inv_id, "entities", entity_id)
        pos = (_coordinate(x, "x"), _coordinate(y, "y"))
        with self._conn:
            self._conn.execute(
                "UPDATE entities SET pos_x = ?, pos_y = ? WHERE id = ?", (*pos, entity_id)
            )
        return {"id": entity_id, "pos_x": pos[0], "pos_y": pos[1]}

    def _set_relationship_evidence(self, relationship_id: str, evidence_ids: list[str]) -> None:
        self._conn.execute(
            "DELETE FROM relationship_evidence WHERE relationship_id = ?", (relationship_id,)
        )
        self._conn.executemany(
            "INSERT INTO relationship_evidence (relationship_id, evidence_id) VALUES (?, ?)",
            [(relationship_id, e) for e in evidence_ids],
        )

    def _write_links(self, owner_id: str, link_sets: list | None) -> None:
        """Replace link rows: each set is (table, owner column, value columns, rows)."""
        for table, owner_col, cols, rows in link_sets or ():
            self._conn.execute(f"DELETE FROM {table} WHERE {owner_col} = ?", (owner_id,))
            marks = ", ".join("?" for _ in range(len(cols) + 1))
            self._conn.executemany(
                f"INSERT INTO {table} ({owner_col}, {', '.join(cols)}) VALUES ({marks})",
                [(owner_id, *row) for row in rows],
            )

    def delete_item(self, inv_id: str, section: str, item_id: str) -> None:
        self.get_item(inv_id, section, item_id)
        with self._conn:
            self._conn.execute(f"DELETE FROM {section} WHERE id = ?", (item_id,))
            # Event links point at items of several tables, so they have no foreign key.
            kind = next((k for k, table in EVENT_LINK_KINDS.items() if table == section), None)
            if kind:
                self._conn.execute(
                    "DELETE FROM event_links WHERE kind = ? AND item_id = ?", (kind, item_id)
                )
            self._touch(inv_id, _now())

    def get_item(self, inv_id: str, section: str, item_id: str) -> dict:
        self._section(section)
        self.get_investigation(inv_id)
        item = next(
            (i for i in self.get_workspace(inv_id)[section] if i["id"] == self._id(item_id)),
            None,
        )
        if item is None:
            names = {"evidence": "evidence", "entities": "entity"}
            raise NotFound(f"{names.get(section, section[:-1])} not found")
        return item

    # -- helpers -----------------------------------------------------------

    @staticmethod
    def _id(value: str) -> str:
        if not is_valid_id(value):
            raise NotFound("not found")
        return value

    @staticmethod
    def _section(section: str) -> str:
        if section not in ALL_SECTIONS:
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
            current = (
                self._conn.execute("SELECT * FROM sources WHERE id = ?", (item_id,)).fetchone()
                if partial
                else None
            )
            if has("url"):
                url = validate_url(data.get("url"), "url")
                # The URL is the source's identity: findings and evidence cite it. Keep it as
                # first recorded; a different URL is a different source.
                if current is not None and url != current["url"]:
                    raise InvalidInput(
                        "a source's URL cannot be changed; add the new URL as another source"
                    )
                if current is None:
                    out["url"] = url
            if has("title"):
                out["title"] = _text(data.get("title"), "title", max_len=TITLE_MAX)
            if has("notes"):
                out["notes"] = _text(data.get("notes"), "notes", max_len=TEXT_MAX)
            if has("source_type"):
                out["source_type"] = _choice(
                    data.get("source_type") or "unspecified", "source_type", SOURCE_TYPES
                )
            if has("original_url"):
                out["original_url"] = validate_url(
                    data.get("original_url"), "original_url", required=False
                )
            if has("published_on"):
                out["published_on"] = _date(data.get("published_on"), "published_on", optional=True)
            if has("accessed_on"):
                out["accessed_on"] = _date(data.get("accessed_on"), "accessed_on", optional=True)
            out.update(self._reliability(data, current, partial=partial))

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
            if has("kind"):
                out["kind"] = _choice(data.get("kind") or "unspecified", "kind", EVIDENCE_KINDS)

        elif section == "entities":
            if has("kind"):
                out["kind"] = _choice(data.get("kind"), "kind", ENTITY_KINDS)
            if has("target_id"):
                out["target_id"] = self._ref(inv_id, "targets", data.get("target_id"), "target_id")
            if has("label"):
                label = _text(data.get("label"), "label", max_len=TITLE_MAX)
                if not label and out.get("target_id"):
                    # An entity made from a target takes the target's value as its name.
                    label = self._conn.execute(
                        "SELECT value FROM targets WHERE id = ?", (out["target_id"],)
                    ).fetchone()["value"][:TITLE_MAX]
                if not label:
                    raise InvalidInput("label is required")
                if "\n" in label or "\r" in label:
                    raise InvalidInput("label must be on one line")
                out["label"] = label
            if has("description"):
                out["description"] = _text(data.get("description"), "description", max_len=TEXT_MAX)
            if has("notes"):
                out["notes"] = _text(data.get("notes"), "notes", max_len=TEXT_MAX)
            for axis in ("x", "y"):
                if f"pos_{axis}" in data and data[f"pos_{axis}"] is not None:
                    out[f"pos_{axis}"] = _coordinate(data[f"pos_{axis}"], axis)

        elif section == "relationships":
            out.update(self._relationship(inv_id, data, partial=partial, item_id=item_id))

        elif section == "events":
            out.update(self._event(inv_id, data, partial=partial, item_id=item_id))

        elif section == "correlations":
            out.update(self._correlation(inv_id, data, partial=partial, item_id=item_id))

        return out

    def _event(self, inv_id: str, data: dict, *, partial: bool, item_id: str) -> dict:
        """Validate an event. The date fields are checked together, as one date."""
        current = (
            self._conn.execute("SELECT * FROM events WHERE id = ?", (item_id,)).fetchone()
            if partial
            else None
        )

        def given(key: str) -> bool:
            return key in data or not partial

        out: dict[str, Any] = {}
        if given("title"):
            title = _text(data.get("title"), "title", max_len=TITLE_MAX, required=True)
            if "\n" in title or "\r" in title:
                raise InvalidInput("title must be on one line")
            out["title"] = title
        for key in ("description", "notes"):
            if given(key):
                out[key] = _text(data.get(key), key, max_len=TEXT_MAX)
        if given("category"):
            out["category"] = _choice(data.get("category") or "other", "category", EVENT_CATEGORIES)
        if given("provenance"):
            out["provenance"] = _choice(
                data.get("provenance") or "hypothesis", "provenance", EVENT_PROVENANCE
            )
        date_keys = (
            "date_precision",
            "start_date",
            "start_time",
            "end_date",
            "end_time",
            "timezone",
        )
        if not partial or any(k in data for k in date_keys):
            merged = {
                k: (data[k] if k in data else (current[k] if current is not None else None))
                for k in date_keys
            }
            out.update(_event_dates(merged))
        if given("links"):
            raw = data.get("links") or []
            if not isinstance(raw, list) or len(raw) > MAX_LINKS:
                raise InvalidInput(f"links must be a list of at most {MAX_LINKS} items")
            rows = []
            for link in raw:
                if not isinstance(link, dict):
                    raise InvalidInput("each link needs a kind and an id")
                kind = _choice(link.get("kind"), "link kind", tuple(EVENT_LINK_KINDS))
                if not link.get("id"):
                    raise InvalidInput(f"{kind} link needs an id")
                rows.append(
                    (kind, self._ref(inv_id, EVENT_LINK_KINDS[kind], link["id"], f"{kind} link"))
                )
            out["_links"] = [
                ("event_links", "event_id", ("kind", "item_id"), list(dict.fromkeys(rows)))
            ]
        return out

    def _correlation(self, inv_id: str, data: dict, *, partial: bool, item_id: str) -> dict:
        """Validate a correlation: two or more events; documented only with a citation."""
        current = (
            self._conn.execute("SELECT * FROM correlations WHERE id = ?", (item_id,)).fetchone()
            if partial
            else None
        )

        def given(key: str) -> bool:
            return key in data or not partial

        out: dict[str, Any] = {}
        links: list = []
        if given("title"):
            title = _text(data.get("title"), "title", max_len=TITLE_MAX, required=True)
            if "\n" in title or "\r" in title:
                raise InvalidInput("title must be on one line")
            out["title"] = title
        for key in ("explanation", "notes"):
            if given(key):
                out[key] = _text(data.get(key), key, max_len=TEXT_MAX)
        if given("recorded_by"):
            recorded_by = _text(data.get("recorded_by"), "recorded_by", max_len=TITLE_MAX)
            if "\n" in recorded_by or "\r" in recorded_by:
                raise InvalidInput("recorded_by must be on one line")
            out["recorded_by"] = recorded_by
        if given("status"):
            out["status"] = _choice(
                data.get("status") or "hypothesis", "status", CORRELATION_STATUSES
            )
        if given("confidence"):
            out["confidence"] = _choice(
                data.get("confidence") or "low", "confidence", CONFIDENCE_LEVELS
            )
        if given("finding_id"):
            out["finding_id"] = self._ref(inv_id, "findings", data.get("finding_id"), "finding_id")
        if given("event_ids"):
            events = self._id_list(inv_id, "events", data.get("event_ids"), "event_ids")
            if len(events) < 2:
                raise InvalidInput("a correlation needs at least two events")
            links.append(
                ("correlation_events", "correlation_id", ("event_id",), [(e,) for e in events])
            )
        evidence_ids = None
        if given("evidence_ids"):
            evidence_ids = self._id_list(
                inv_id, "evidence", data.get("evidence_ids"), "evidence_ids"
            )
            links.append(
                (
                    "correlation_evidence",
                    "correlation_id",
                    ("evidence_id",),
                    [(e,) for e in evidence_ids],
                )
            )
        if links:
            out["_links"] = links

        status = out.get("status", current["status"] if current is not None else "hypothesis")
        finding = (
            out["finding_id"]
            if "finding_id" in out
            else (current["finding_id"] if current is not None else None)
        )
        if evidence_ids is None:
            evidence_ids = (
                [
                    r["evidence_id"]
                    for r in self._conn.execute(
                        "SELECT evidence_id FROM correlation_evidence WHERE correlation_id = ?",
                        (item_id,),
                    )
                ]
                if current is not None
                else []
            )
        if status == "documented" and not finding and not evidence_ids:
            raise InvalidInput(
                "a documented correlation must cite a finding or evidence; "
                "without one, record it as a hypothesis"
            )
        return out

    def _id_list(self, inv_id: str, table: str, raw: Any, field: str) -> list[str]:
        raw = raw or []
        if not isinstance(raw, list) or len(raw) > MAX_LINKS:
            raise InvalidInput(f"{field} must be a list of at most {MAX_LINKS} ids")
        return list(dict.fromkeys(self._ref(inv_id, table, i, field) for i in raw))

    def _relationship(self, inv_id: str, data: dict, *, partial: bool, item_id: str) -> dict:
        """Validate a relationship. A documented one must cite a finding or evidence."""
        current = (
            self._conn.execute("SELECT * FROM relationships WHERE id = ?", (item_id,)).fetchone()
            if partial
            else None
        )

        def given(key: str) -> bool:
            return key in data or not partial

        out: dict[str, Any] = {}
        ends = {}
        for key in ("from_entity_id", "to_entity_id"):
            if given(key):
                if data.get(key) in (None, ""):
                    raise InvalidInput(f"{key} is required")
                ends[key] = self._ref(inv_id, "entities", data.get(key), key)
                out[key] = ends[key]
            else:
                ends[key] = current[key]
        if ends["from_entity_id"] == ends["to_entity_id"]:
            raise InvalidInput("a relationship must connect two different entities")
        if given("label"):
            label = _text(data.get("label"), "label", max_len=TITLE_MAX, required=True)
            if "\n" in label or "\r" in label:
                raise InvalidInput("label must be on one line")
            out["label"] = label
        if given("status"):
            out["status"] = _choice(
                data.get("status") or "hypothesis", "status", RELATIONSHIP_STATUSES
            )
        if given("confidence"):
            out["confidence"] = _choice(
                data.get("confidence") or "low", "confidence", CONFIDENCE_LEVELS
            )
        for key in ("description", "notes"):
            if given(key):
                out[key] = _text(data.get(key), key, max_len=TEXT_MAX)
        if given("recorded_by"):
            recorded_by = _text(data.get("recorded_by"), "recorded_by", max_len=TITLE_MAX)
            if "\n" in recorded_by or "\r" in recorded_by:
                raise InvalidInput("recorded_by must be on one line")
            out["recorded_by"] = recorded_by
        if given("finding_id"):
            out["finding_id"] = self._ref(inv_id, "findings", data.get("finding_id"), "finding_id")
        evidence_ids = None
        if given("evidence_ids"):
            raw = data.get("evidence_ids") or []
            if not isinstance(raw, list) or len(raw) > 100:
                raise InvalidInput("evidence_ids must be a list of at most 100 ids")
            evidence_ids = list(
                dict.fromkeys(self._ref(inv_id, "evidence", e, "evidence_ids") for e in raw)
            )
            out["_evidence_ids"] = evidence_ids

        status = out.get("status", current["status"] if current is not None else "hypothesis")
        finding = (
            out["finding_id"]
            if "finding_id" in out
            else (current["finding_id"] if current is not None else None)
        )
        if evidence_ids is None:
            evidence_ids = (
                [
                    r["evidence_id"]
                    for r in self._conn.execute(
                        "SELECT evidence_id FROM relationship_evidence WHERE relationship_id = ?",
                        (item_id,),
                    )
                ]
                if current is not None
                else []
            )
        if status == "documented" and not finding and not evidence_ids:
            raise InvalidInput(
                "a documented relationship must cite a finding or evidence; "
                "without one, record it as a hypothesis"
            )
        return out

    @staticmethod
    def _reliability(data: dict, current: sqlite3.Row | None, *, partial: bool) -> dict:
        """Reliability columns to write. A rating needs a rationale; its date is today's."""
        if partial and "reliability" not in data and "reliability_rationale" not in data:
            return {}
        old_rating = current["reliability"] if current is not None else "unassessed"
        old_rationale = current["reliability_rationale"] if current is not None else ""
        raw = data.get("reliability", old_rating if partial else None) or "unassessed"
        if not isinstance(raw, str) or raw.strip().upper() not in {
            r.upper() for r in RELIABILITY_RATINGS
        }:
            raise InvalidInput(f"reliability must be one of: {', '.join(RELIABILITY_RATINGS)}")
        rating = "unassessed" if raw.strip().lower() == "unassessed" else raw.strip().upper()
        rationale = (
            _text(data.get("reliability_rationale"), "reliability_rationale", max_len=TEXT_MAX)
            if "reliability_rationale" in data
            else old_rationale
        )
        if rating != "unassessed" and not rationale:
            raise InvalidInput(
                "a reliability rating needs a rationale: say why in reliability_rationale"
            )
        out = {"reliability": rating, "reliability_rationale": rationale}
        if rating == "unassessed":
            out["reliability_assessed_on"] = ""
        elif rating != old_rating or rationale != old_rationale or current is None:
            out["reliability_assessed_on"] = _today()
        return out


def _zone(name: str):
    """A tzinfo for an IANA name ("Europe/London"), "UTC" or a fixed offset ("+05:30")."""
    if name.upper() in ("UTC", "Z"):
        return timezone.utc
    match = _OFFSET_RE.match(name)
    if match:
        sign, hours, minutes = match.groups()
        delta = timedelta(hours=int(hours), minutes=int(minutes))
        return timezone(delta if sign == "+" else -delta)
    if len(name) > 64 or not re.match(r"^[A-Za-z][A-Za-z0-9_+\-/]*$", name) or ".." in name:
        raise InvalidInput(
            "timezone must be an IANA name (e.g. Europe/London), UTC or an offset like +05:30"
        )
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        raise InvalidInput(f"unknown timezone: {name}") from None


def _event_dates(d: dict) -> dict:
    """Validate an event's date fields together and compute its sort key.

    Dates are kept as entered. The sort key is the start in UTC when a time and timezone
    are given; otherwise the date (and time) as entered, with missing parts as the start
    of the period, so events without a timezone sort by their local wall-clock time.
    """
    precision = _choice(d.get("date_precision") or "exact", "date_precision", DATE_PRECISIONS)
    start = _text(d.get("start_date"), "start_date", max_len=10, required=True)
    if precision == "approximate":
        if not _PARTIAL_DATE_RE.match(start):
            raise InvalidInput("start_date must be YYYY, YYYY-MM or YYYY-MM-DD")
    elif not _DATE_RE.match(start):
        raise InvalidInput("start_date must be a date in YYYY-MM-DD form")
    # A partial (approximate) date sorts as the start of its year or month.
    padded = {4: f"{start}-01-01", 7: f"{start}-01"}.get(len(start), start)
    try:
        date.fromisoformat(padded)
    except ValueError:
        raise InvalidInput("start_date is not a valid date") from None

    def time_of(key: str, date_value: str) -> str:
        value = _text(d.get(key), key, max_len=5)
        if value and not _TIME_RE.match(value):
            raise InvalidInput(f"{key} must be HH:MM (24-hour)")
        if value and len(date_value) != 10:
            raise InvalidInput(f"{key} needs a full date (YYYY-MM-DD)")
        return value

    start_time = time_of("start_time", start)
    tz_name = _text(d.get("timezone"), "timezone", max_len=64)
    tz = _zone(tz_name) if tz_name else None
    if precision == "range":
        end = _text(d.get("end_date"), "end_date", max_len=10, required=True)
        if not _DATE_RE.match(end):
            raise InvalidInput("end_date must be a date in YYYY-MM-DD form")
        try:
            date.fromisoformat(end)
        except ValueError:
            raise InvalidInput("end_date is not a valid date") from None
        end_time = time_of("end_time", end)
        # Both ends are in the event's one timezone (or none), so compare as entered.
        if end < start or (end == start and start_time and end_time and end_time < start_time):
            raise InvalidInput("the range ends before it starts")
    else:
        end, end_time = "", ""  # only a range has an end

    def moment(day: str, hhmm: str) -> str:
        if hhmm and tz is not None:
            local = datetime.fromisoformat(f"{day}T{hhmm}").replace(tzinfo=tz)
            return local.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M")
        return f"{day}T{hhmm or '00:00'}"

    return {
        "date_precision": precision,
        "start_date": start,
        "start_time": start_time,
        "end_date": end,
        "end_time": end_time,
        "timezone": tz_name,
        "sort_key": moment(padded, start_time),
    }


def _coordinate(value: Any, axis: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise InvalidInput(f"position {axis} must be a number")
    number = float(value)
    if number != number or abs(number) > POSITION_LIMIT:  # NaN or out of range
        raise InvalidInput(f"position {axis} is out of range")
    return number


def _find(items: list[dict], item_id: str, what: str) -> dict:
    found = next((i for i in items if i["id"] == item_id), None) if is_valid_id(item_id) else None
    if found is None:
        raise NotFound(f"{what} not found")
    return found


def _link_traces(inv: dict) -> None:
    """Add the ids that connect sources, findings and evidence, for display and tracing."""
    for f in inv["findings"]:
        f["evidence_ids"] = [e["id"] for e in inv["evidence"] if e["finding_id"] == f["id"]]
    for s in inv["sources"]:
        s["finding_ids"] = [f["id"] for f in inv["findings"] if f["source_id"] == s["id"]]
        s["evidence_ids"] = [e["id"] for e in inv["evidence"] if e["source_id"] == s["id"]]
        supported = [
            e["finding_id"]
            for e in inv["evidence"]
            if e["source_id"] == s["id"] and e["finding_id"]
        ]
        s["supported_finding_ids"] = list(dict.fromkeys(s["finding_ids"] + supported))
