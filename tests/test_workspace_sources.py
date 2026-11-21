"""Evidence and source management: source metadata, reliability, provenance, traceability,
and the schema 1 -> 2 migration of an existing workspace.db."""

from __future__ import annotations

import sqlite3

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from openosint import workspace as ws
from openosint.workspace import InvalidInput, NotFound, WorkspaceStore


@pytest.fixture
def store(tmp_path):
    with WorkspaceStore(tmp_path / "workspace.db") as s:
        yield s


@pytest.fixture
def inv(store):
    return store.create_investigation("Example Org sourcing")


# --- source metadata -------------------------------------------------------------


def test_source_metadata_round_trip(store, inv):
    s = store.add_item(
        inv["id"],
        "sources",
        {
            "url": "https://web.archive.org/web/2026/https://example.com/about",
            "title": "Example Org — About us (archived)",
            "source_type": "archive",
            "original_url": "https://example.com/about",
            "published_on": "2025-12-01",
            "accessed_on": "2026-01-10",
        },
    )
    assert s["source_type"] == "archive"
    assert s["original_url"] == "https://example.com/about"
    assert (s["published_on"], s["accessed_on"]) == ("2025-12-01", "2026-01-10")
    assert s["title"] == "Example Org — About us (archived)"


def test_new_source_defaults_are_unassessed(store, inv):
    s = store.add_item(inv["id"], "sources", {"url": "https://example.com/"})
    assert s["source_type"] == "unspecified"
    assert s["reliability"] == "unassessed"
    assert s["reliability_rationale"] == "" and s["reliability_assessed_on"] == ""
    assert s["published_on"] == "" and s["accessed_on"] == "" and s["original_url"] == ""


def test_source_created_from_a_finding_is_unassessed(store, inv):
    f = store.add_item(inv["id"], "findings", {"title": "x", "source_url": "https://example.com/x"})
    source = store.get_item(inv["id"], "sources", f["source_id"])
    assert source["reliability"] == "unassessed" and source["source_type"] == "unspecified"
    assert source["accessed_on"] == ""  # not guessed from the finding's date


@pytest.mark.parametrize(
    "data, message",
    [
        ({"url": "https://example.com/", "source_type": "blog-ish"}, "source_type must be one of"),
        ({"url": "https://example.com/", "original_url": "javascript:alert(1)"}, "original_url"),
        ({"url": "https://example.com/", "published_on": "Dec 2025"}, "YYYY-MM-DD"),
        ({"url": "https://example.com/", "accessed_on": "2026-13-01"}, "not a valid date"),
        ({"url": "https://example.com/", "reliability": "G"}, "reliability must be one of"),
        ({"url": "https://example.com/", "reliability": "B"}, "needs a rationale"),
        (
            {"url": "https://example.com/", "reliability": "A", "reliability_rationale": "  "},
            "needs a rationale",
        ),
    ],
)
def test_source_metadata_validation(store, inv, data, message):
    with pytest.raises(InvalidInput, match=message):
        store.add_item(inv["id"], "sources", data)
    assert store.get_workspace(inv["id"])["sources"] == []


def test_source_url_is_preserved(store, inv):
    s = store.add_item(inv["id"], "sources", {"url": "https://example.com/Original?Case=1"})
    assert s["url"] == "https://example.com/Original?Case=1"  # stored exactly as entered
    with pytest.raises(InvalidInput, match="cannot be changed"):
        store.update_item(inv["id"], "sources", s["id"], {"url": "https://example.com/other"})
    # Sending the same URL (as the edit form does) is accepted.
    same = store.update_item(inv["id"], "sources", s["id"], {"url": s["url"], "title": "T"})
    assert same["url"] == s["url"] and same["title"] == "T"


def test_optional_dates_can_be_cleared(store, inv):
    s = store.add_item(
        inv["id"], "sources", {"url": "https://example.com/", "accessed_on": "2026-01-01"}
    )
    assert (
        store.update_item(inv["id"], "sources", s["id"], {"accessed_on": ""})["accessed_on"] == ""
    )


# --- reliability -----------------------------------------------------------------


def test_reliability_is_user_assigned_with_rationale_and_date(store, inv):
    s = store.add_item(inv["id"], "sources", {"url": "https://example.com/registry"})
    rated = store.update_item(
        inv["id"],
        "sources",
        s["id"],
        {"reliability": "b", "reliability_rationale": "Official company registry extract"},
    )
    assert rated["reliability"] == "B"
    assert rated["reliability_rationale"] == "Official company registry extract"
    assert rated["reliability_assessed_on"] == ws._today()


def test_changing_other_fields_never_changes_the_rating(store, inv):
    s = store.add_item(
        inv["id"],
        "sources",
        {"url": "https://example.com/", "reliability": "C", "reliability_rationale": "r"},
    )
    store._conn.execute(
        "UPDATE sources SET reliability_assessed_on = '2020-01-01' WHERE id = ?", (s["id"],)
    )
    store._conn.commit()
    edited = store.update_item(inv["id"], "sources", s["id"], {"title": "renamed", "notes": "n"})
    assert (edited["reliability"], edited["reliability_assessed_on"]) == ("C", "2020-01-01")
    # Re-sending the same rating and rationale (as the edit form does) keeps the date too.
    resent = store.update_item(
        inv["id"], "sources", s["id"], {"reliability": "C", "reliability_rationale": "r"}
    )
    assert resent["reliability_assessed_on"] == "2020-01-01"


def test_clearing_the_rationale_of_a_rated_source_is_refused(store, inv):
    s = store.add_item(
        inv["id"],
        "sources",
        {"url": "https://example.com/", "reliability": "D", "reliability_rationale": "r"},
    )
    with pytest.raises(InvalidInput, match="needs a rationale"):
        store.update_item(inv["id"], "sources", s["id"], {"reliability_rationale": ""})


def test_back_to_unassessed_clears_the_date(store, inv):
    s = store.add_item(
        inv["id"],
        "sources",
        {"url": "https://example.com/", "reliability": "F", "reliability_rationale": "r"},
    )
    reset = store.update_item(inv["id"], "sources", s["id"], {"reliability": "unassessed"})
    assert reset["reliability"] == "unassessed" and reset["reliability_assessed_on"] == ""
    assert reset["reliability_rationale"] == "r"  # the user's text is kept


def test_nothing_in_the_store_assigns_a_rating_by_itself(store, inv):
    store.add_item(
        inv["id"],
        "findings",
        {"title": "a", "source_url": "https://example.com/a", "confidence": "high"},
    )
    store.add_item(
        inv["id"], "evidence", {"description": "b", "source_url": "https://example.com/b"}
    )
    assert {s["reliability"] for s in store.get_workspace(inv["id"])["sources"]} == {"unassessed"}


# --- provenance ------------------------------------------------------------------


@pytest.mark.parametrize("kind", ["observation", "reported", "assumption", "conclusion"])
def test_finding_provenance_kinds(store, inv, kind):
    assert store.add_item(inv["id"], "findings", {"title": "x", "kind": kind})["kind"] == kind


def test_evidence_provenance(store, inv):
    assert store.add_item(inv["id"], "evidence", {"description": "x"})["kind"] == "unspecified"
    e = store.add_item(inv["id"], "evidence", {"description": "y", "kind": "reported"})
    assert e["kind"] == "reported"
    assert (
        store.update_item(inv["id"], "evidence", e["id"], {"kind": "observation"})["kind"]
        == "observation"
    )
    for bad in ("assumption", "conclusion", "fact"):
        with pytest.raises(InvalidInput, match="kind must be one of"):
            store.add_item(inv["id"], "evidence", {"description": "z", "kind": bad})


# --- traceability ----------------------------------------------------------------


@pytest.fixture
def linked(store, inv):
    i = inv["id"]
    s1 = store.add_item(
        i,
        "sources",
        {"url": "https://example.com/a", "reliability": "B", "reliability_rationale": "r"},
    )
    s2 = store.add_item(i, "sources", {"url": "https://example.com/b"})
    f_direct = store.add_item(i, "findings", {"title": "cites a", "source_id": s1["id"]})
    f_via = store.add_item(i, "findings", {"title": "supported by evidence", "kind": "conclusion"})
    e1 = store.add_item(
        i,
        "evidence",
        {
            "description": "from a",
            "source_id": s1["id"],
            "finding_id": f_via["id"],
            "kind": "observation",
        },
    )
    e2 = store.add_item(
        i,
        "evidence",
        {
            "description": "from b",
            "source_id": s2["id"],
            "finding_id": f_via["id"],
            "kind": "reported",
        },
    )
    return {"s1": s1, "s2": s2, "f_direct": f_direct, "f_via": f_via, "e1": e1, "e2": e2}


def test_workspace_carries_link_ids_and_source_reliability(store, inv, linked):
    data = store.get_workspace(inv["id"])
    s1 = next(s for s in data["sources"] if s["id"] == linked["s1"]["id"])
    assert s1["finding_ids"] == [linked["f_direct"]["id"]]
    assert s1["evidence_ids"] == [linked["e1"]["id"]]
    assert set(s1["supported_finding_ids"]) == {linked["f_direct"]["id"], linked["f_via"]["id"]}
    f_via = next(f for f in data["findings"] if f["id"] == linked["f_via"]["id"])
    assert set(f_via["evidence_ids"]) == {linked["e1"]["id"], linked["e2"]["id"]}
    f_direct = next(f for f in data["findings"] if f["id"] == linked["f_direct"]["id"])
    assert f_direct["source_reliability"] == "B"
    e1 = next(e for e in data["evidence"] if e["id"] == linked["e1"]["id"])
    assert e1["source_reliability"] == "B"


def test_trace_source(store, inv, linked):
    trace = store.trace_source(inv["id"], linked["s1"]["id"])
    assert trace["source"]["url"] == "https://example.com/a"
    assert [f["id"] for f in trace["findings"]] == [linked["f_direct"]["id"]]
    assert [e["id"] for e in trace["evidence"]] == [linked["e1"]["id"]]
    assert [f["id"] for f in trace["findings_via_evidence"]] == [linked["f_via"]["id"]]


def test_trace_finding(store, inv, linked):
    trace = store.trace_finding(inv["id"], linked["f_via"]["id"])
    assert trace["source"] is None
    by_id = {e["id"]: e for e in trace["evidence"]}
    assert by_id[linked["e1"]["id"]]["source"]["reliability"] == "B"
    assert by_id[linked["e2"]["id"]]["source"]["url"] == "https://example.com/b"
    assert by_id[linked["e2"]["id"]]["kind"] == "reported"
    direct = store.trace_finding(inv["id"], linked["f_direct"]["id"])
    assert direct["source"]["id"] == linked["s1"]["id"] and direct["evidence"] == []


def test_trace_unknown_or_foreign_ids(store, inv, linked):
    other = store.create_investigation("Other")
    for call, item in (
        (store.trace_source, linked["s1"]["id"]),
        (store.trace_finding, linked["f_via"]["id"]),
    ):
        with pytest.raises(NotFound):
            call(other["id"], item)
        with pytest.raises(NotFound):
            call(inv["id"], "0" * 32)
        with pytest.raises(NotFound):
            call(inv["id"], "not-an-id")


def test_deleting_a_source_keeps_the_trace_consistent(store, inv, linked):
    store.delete_item(inv["id"], "sources", linked["s1"]["id"])
    trace = store.trace_finding(inv["id"], linked["f_via"]["id"])
    assert {e["id"]: e["source"] for e in trace["evidence"]}[linked["e1"]["id"]] is None
    assert store.trace_finding(inv["id"], linked["f_direct"]["id"])["source"] is None


# --- migration from schema 1 ---------------------------------------------------------

_V1_SCHEMA = """
CREATE TABLE investigations (id TEXT PRIMARY KEY, title TEXT NOT NULL, description TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE targets (id TEXT PRIMARY KEY, investigation_id TEXT NOT NULL REFERENCES investigations(id) ON DELETE CASCADE,
    kind TEXT NOT NULL, value TEXT NOT NULL, notes TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL, UNIQUE (investigation_id, kind, value));
CREATE TABLE sources (id TEXT PRIMARY KEY, investigation_id TEXT NOT NULL REFERENCES investigations(id) ON DELETE CASCADE,
    url TEXT NOT NULL, title TEXT NOT NULL DEFAULT '', notes TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL, UNIQUE (investigation_id, url));
CREATE TABLE findings (id TEXT PRIMARY KEY, investigation_id TEXT NOT NULL REFERENCES investigations(id) ON DELETE CASCADE,
    title TEXT NOT NULL, description TEXT NOT NULL DEFAULT '', kind TEXT NOT NULL DEFAULT 'observation',
    confidence TEXT NOT NULL DEFAULT 'low', source_id TEXT REFERENCES sources(id) ON DELETE SET NULL,
    target_id TEXT REFERENCES targets(id) ON DELETE SET NULL, notes TEXT NOT NULL DEFAULT '',
    recorded_on TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE notes (id TEXT PRIMARY KEY, investigation_id TEXT NOT NULL REFERENCES investigations(id) ON DELETE CASCADE,
    body TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE evidence (id TEXT PRIMARY KEY, investigation_id TEXT NOT NULL REFERENCES investigations(id) ON DELETE CASCADE,
    description TEXT NOT NULL, source_id TEXT REFERENCES sources(id) ON DELETE SET NULL,
    target_id TEXT REFERENCES targets(id) ON DELETE SET NULL, finding_id TEXT REFERENCES findings(id) ON DELETE SET NULL,
    collected_on TEXT NOT NULL, notes TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
PRAGMA user_version=1;
"""

INV, SRC, FND, EVD = "1" * 32, "2" * 32, "3" * 32, "4" * 32
T0 = "2026-01-01T00:00:00+00:00"


def _v1_db(path):
    conn = sqlite3.connect(path)
    conn.executescript(_V1_SCHEMA)
    conn.execute("INSERT INTO investigations VALUES (?, 'Old case', 'kept', ?, ?)", (INV, T0, T0))
    conn.execute(
        "INSERT INTO sources VALUES (?, ?, 'https://example.com/Kept?x=1', 'Old title', 'old notes', ?, ?)",
        (SRC, INV, T0, T0),
    )
    conn.execute(
        "INSERT INTO findings VALUES (?, ?, 'Old finding', 'd', 'conclusion', 'medium', ?, NULL, 'n', '2025-05-05', ?, ?)",
        (FND, INV, SRC, T0, T0),
    )
    conn.execute(
        "INSERT INTO evidence VALUES (?, ?, 'Old evidence', ?, NULL, ?, '2025-05-06', 'en', ?, ?)",
        (EVD, INV, SRC, FND, T0, T0),
    )
    conn.commit()
    conn.close()


def test_schema_1_database_is_migrated_without_changing_data(tmp_path):
    db = tmp_path / "workspace.db"
    _v1_db(db)
    with WorkspaceStore(db) as s:
        data = s.get_workspace(INV)
    assert (data["title"], data["description"], data["updated_at"]) == ("Old case", "kept", T0)
    src = data["sources"][0]
    assert (src["url"], src["title"], src["notes"]) == (
        "https://example.com/Kept?x=1",
        "Old title",
        "old notes",
    )
    assert (src["reliability"], src["source_type"], src["reliability_assessed_on"]) == (
        "unassessed",
        "unspecified",
        "",
    )
    finding = data["findings"][0]
    assert (finding["kind"], finding["confidence"], finding["recorded_on"]) == (
        "conclusion",
        "medium",
        "2025-05-05",
    )
    ev = data["evidence"][0]
    assert ev["kind"] == "unspecified"  # not guessed
    assert (ev["description"], ev["collected_on"], ev["notes"]) == (
        "Old evidence",
        "2025-05-06",
        "en",
    )
    conn = sqlite3.connect(db)
    try:
        # Upgraded straight to the current schema (2 added these columns; 3 the graph tables).
        assert conn.execute("PRAGMA user_version").fetchone()[0] == ws.SCHEMA_VERSION >= 2
    finally:
        conn.close()


def test_migration_is_idempotent(tmp_path):
    db = tmp_path / "workspace.db"
    _v1_db(db)
    for _ in range(3):
        with WorkspaceStore(db) as s:
            assert len(s.get_workspace(INV)["sources"]) == 1


# --- API -------------------------------------------------------------------------


@pytest_asyncio.fixture
async def client(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENOSINT_HOME", str(tmp_path / "home"))
    import openosint.web_server as w

    w._RATE_STORE.clear()
    app = w.create_app(host="127.0.0.1")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://127.0.0.1") as c:
        yield c
    w._RATE_STORE.clear()


async def test_api_source_metadata_reliability_and_trace(client):
    inv = (await client.post("/api/investigations", json={"title": "API"})).json()
    base = f"/api/investigations/{inv['id']}"
    r = await client.post(
        f"{base}/sources",
        json={
            "url": "https://example.com/report",
            "source_type": "government",
            "published_on": "2025-11-30",
            "accessed_on": "2026-01-02",
            "reliability": "A",
            "reliability_rationale": "Primary official record",
        },
    )
    assert r.status_code == 201, r.text
    src = r.json()
    assert (src["reliability"], src["reliability_assessed_on"]) == ("A", ws._today())

    r = await client.patch(f"{base}/sources/{src['id']}", json={"url": "https://example.com/other"})
    assert r.status_code == 422 and "cannot be changed" in r.json()["detail"]
    r = await client.post(
        f"{base}/sources", json={"url": "https://example.com/x", "reliability": "C"}
    )
    assert r.status_code == 422 and "rationale" in r.json()["detail"]
    r = await client.post(
        f"{base}/sources", json={"url": "https://example.com/x", "source_type": "rumour"}
    )
    assert r.status_code == 422

    f = (await client.post(f"{base}/findings", json={"title": "Claim", "kind": "reported"})).json()
    e = (
        await client.post(
            f"{base}/evidence",
            json={
                "description": "Report text",
                "kind": "reported",
                "source_id": src["id"],
                "finding_id": f["id"],
            },
        )
    ).json()
    assert e["kind"] == "reported" and e["source_reliability"] == "A"

    trace = (await client.get(f"{base}/sources/{src['id']}/trace")).json()
    assert [x["id"] for x in trace["evidence"]] == [e["id"]]
    assert [x["id"] for x in trace["findings_via_evidence"]] == [f["id"]]
    ftrace = (await client.get(f"{base}/findings/{f['id']}/trace")).json()
    assert ftrace["evidence"][0]["source"]["reliability"] == "A"
    assert (await client.get(f"{base}/findings/{'0' * 32}/trace")).status_code == 404


async def test_api_trace_routes_are_restricted_like_the_rest(client, monkeypatch):
    import openosint.web_server as w

    inv = (await client.post("/api/investigations", json={"title": "R"})).json()
    src = (
        await client.post(
            f"/api/investigations/{inv['id']}/sources", json={"url": "https://example.com/"}
        )
    ).json()
    monkeypatch.setattr(w, "DEMO_MODE", True)
    r = await client.get(f"/api/investigations/{inv['id']}/sources/{src['id']}/trace")
    assert r.status_code == 403
