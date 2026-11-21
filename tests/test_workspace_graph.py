"""Entity relationship graph in the research workspace: entities, relationships, citations,
positions, migration to schema 3, the API and the page wiring."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from openosint import workspace as ws
from openosint.workspace import InvalidInput, NotFound, WorkspaceStore

ROOT = Path(__file__).resolve().parent.parent
PAGE = (ROOT / "openosint" / "web" / "workspace.html").read_text(encoding="utf-8")
SCRIPT = (ROOT / "openosint" / "web" / "static" / "workspace.js").read_text(encoding="utf-8")
GRAPH_JS = (ROOT / "openosint" / "web" / "static" / "workspace-graph.js").read_text(
    encoding="utf-8"
)


@pytest.fixture
def store(tmp_path):
    with WorkspaceStore(tmp_path / "workspace.db") as s:
        yield s


@pytest.fixture
def inv(store):
    return store.create_investigation("Example Org network")


def _entity(store, inv, label, kind="person", **extra):
    return store.add_item(inv["id"], "entities", {"kind": kind, "label": label, **extra})


def _rel(store, inv, a, b, label="linked to", **extra):
    return store.add_item(
        inv["id"],
        "relationships",
        {"from_entity_id": a["id"], "to_entity_id": b["id"], "label": label, **extra},
    )


# --- entities ------------------------------------------------------------------


@pytest.mark.parametrize("kind", ws.ENTITY_KINDS)
def test_every_entity_kind(store, inv, kind):
    e = _entity(store, inv, f"{kind} entity", kind=kind)
    assert (e["kind"], e["label"]) == (kind, f"{kind} entity")
    assert e["pos_x"] is None and e["relationship_count"] == 0


def test_entity_fields_and_edit(store, inv):
    e = _entity(store, inv, "Jane Example", description="Director", notes="from registry")
    assert (e["description"], e["notes"]) == ("Director", "from registry")
    edited = store.update_item(inv["id"], "entities", e["id"], {"label": "J. Example", "notes": ""})
    assert (edited["label"], edited["notes"], edited["description"]) == (
        "J. Example",
        "",
        "Director",
    )


def test_entity_linked_to_a_target_takes_its_value(store, inv):
    t = store.add_item(inv["id"], "targets", {"kind": "domain", "value": "example.com"})
    e = store.add_item(inv["id"], "entities", {"kind": "domain", "target_id": t["id"]})
    assert e["label"] == "example.com"
    assert (e["target_kind"], e["target_value"]) == ("domain", "example.com")
    named = store.add_item(
        inv["id"], "entities", {"kind": "domain", "target_id": t["id"], "label": "Main site"}
    )
    assert named["label"] == "Main site"
    store.delete_item(inv["id"], "targets", t["id"])
    assert store.get_item(inv["id"], "entities", e["id"])["target_id"] is None


@pytest.mark.parametrize(
    "data, message",
    [
        ({"kind": "person"}, "label is required"),
        ({"kind": "alien", "label": "x"}, "kind must be one of"),
        ({"label": "x"}, "kind must be one of"),
        ({"kind": "person", "label": "two\nlines"}, "one line"),
        ({"kind": "person", "label": "x" * (ws.TITLE_MAX + 1)}, "longer than"),
        ({"kind": "person", "label": "x", "target_id": "0" * 32}, "does not belong"),
        ({"kind": "person", "label": "x", "pos_x": float("nan")}, "out of range"),
        ({"kind": "person", "label": "x", "pos_x": 1e9}, "out of range"),
        ({"kind": "person", "label": "x", "pos_y": "12"}, "must be a number"),
    ],
)
def test_entity_validation(store, inv, data, message):
    with pytest.raises(InvalidInput, match=message):
        store.add_item(inv["id"], "entities", data)
    assert store.get_workspace(inv["id"])["entities"] == []


def test_entity_position(store, inv):
    e = _entity(store, inv, "A")
    store._conn.execute("UPDATE investigations SET updated_at = '2000-01-01T00:00:00+00:00'")
    store._conn.commit()
    assert store.set_entity_position(inv["id"], e["id"], 12.5, -40) == {
        "id": e["id"],
        "pos_x": 12.5,
        "pos_y": -40.0,
    }
    saved = store.get_item(inv["id"], "entities", e["id"])
    assert (saved["pos_x"], saved["pos_y"]) == (12.5, -40.0)
    # Moving a node is layout, not a change to the investigation.
    assert store.get_investigation(inv["id"])["updated_at"] == "2000-01-01T00:00:00+00:00"
    for bad in ((True, 0), (float("inf"), 0), (0, None)):
        with pytest.raises(InvalidInput):
            store.set_entity_position(inv["id"], e["id"], *bad)


# --- relationships ----------------------------------------------------------------


def test_relationship_defaults_are_a_low_confidence_hypothesis(store, inv):
    a, b = _entity(store, inv, "A"), _entity(store, inv, "B", kind="organization")
    r = _rel(store, inv, a, b, "works for")
    assert (r["status"], r["confidence"]) == ("hypothesis", "low")
    assert (r["from_label"], r["to_label"], r["from_kind"], r["to_kind"]) == (
        "A",
        "B",
        "person",
        "organization",
    )
    assert r["evidence_ids"] == [] and r["unsupported"] is False


def test_documented_relationship_must_cite_something(store, inv):
    a, b = _entity(store, inv, "A"), _entity(store, inv, "B")
    with pytest.raises(InvalidInput, match="must cite a finding or evidence"):
        _rel(store, inv, a, b, status="documented")
    f = store.add_item(inv["id"], "findings", {"title": "Registry lists A as director of B"})
    by_finding = _rel(store, inv, a, b, status="documented", finding_id=f["id"])
    assert by_finding["status"] == "documented" and by_finding["finding_title"] == f["title"]
    ev = store.add_item(inv["id"], "evidence", {"description": "Registry extract"})
    by_evidence = _rel(
        store, inv, a, b, "director of", status="documented", evidence_ids=[ev["id"]]
    )
    assert by_evidence["evidence_ids"] == [ev["id"]]


def test_promoting_a_hypothesis_needs_a_citation(store, inv):
    a, b = _entity(store, inv, "A"), _entity(store, inv, "B")
    r = _rel(store, inv, a, b)
    with pytest.raises(InvalidInput, match="must cite"):
        store.update_item(inv["id"], "relationships", r["id"], {"status": "documented"})
    ev = store.add_item(inv["id"], "evidence", {"description": "e"})
    promoted = store.update_item(
        inv["id"], "relationships", r["id"], {"status": "documented", "evidence_ids": [ev["id"]]}
    )
    assert promoted["status"] == "documented"
    # Removing the last citation from a documented relationship is refused.
    with pytest.raises(InvalidInput, match="must cite"):
        store.update_item(inv["id"], "relationships", r["id"], {"evidence_ids": []})


@pytest.mark.parametrize(
    "extra, message",
    [
        ({"label": ""}, "label is required"),
        ({"label": "a\nb"}, "one line"),
        ({"status": "confirmed"}, "status must be one of"),
        ({"confidence": "certain"}, "confidence must be one of"),
        ({"finding_id": "0" * 32}, "does not belong"),
        ({"evidence_ids": ["0" * 32]}, "does not belong"),
        ({"evidence_ids": "not-a-list"}, "must be a list"),
        ({"recorded_by": "a\nb"}, "one line"),
    ],
)
def test_relationship_validation(store, inv, extra, message):
    a, b = _entity(store, inv, "A"), _entity(store, inv, "B")
    with pytest.raises(InvalidInput, match=message):
        _rel(store, inv, a, b, **extra)


def test_relationship_endpoints(store, inv):
    a, b = _entity(store, inv, "A"), _entity(store, inv, "B")
    with pytest.raises(InvalidInput, match="two different entities"):
        _rel(store, inv, a, a)
    with pytest.raises(InvalidInput, match="from_entity_id is required"):
        store.add_item(inv["id"], "relationships", {"to_entity_id": b["id"], "label": "x"})
    other = store.create_investigation("Other")
    foreign = store.add_item(other["id"], "entities", {"kind": "person", "label": "F"})
    with pytest.raises(InvalidInput, match="does not belong"):
        store.add_item(
            inv["id"],
            "relationships",
            {"from_entity_id": a["id"], "to_entity_id": foreign["id"], "label": "x"},
        )
    r = _rel(store, inv, a, b)
    with pytest.raises(InvalidInput, match="two different entities"):
        store.update_item(inv["id"], "relationships", r["id"], {"to_entity_id": a["id"]})


def test_relationship_fields_round_trip(store, inv):
    a, b = _entity(store, inv, "A"), _entity(store, inv, "B")
    e1 = store.add_item(
        inv["id"], "evidence", {"description": "first", "collected_on": "2026-01-01"}
    )
    e2 = store.add_item(
        inv["id"], "evidence", {"description": "second", "collected_on": "2026-02-01"}
    )
    r = _rel(
        store,
        inv,
        a,
        b,
        "communicated with",
        confidence="medium",
        description="Emails in a public mailing list",
        notes="check dates",
        recorded_by="Analyst A",
        evidence_ids=[e2["id"], e1["id"], e1["id"]],
    )
    assert r["evidence_ids"] == [e1["id"], e2["id"]]  # de-duplicated, oldest first
    assert (r["description"], r["notes"], r["recorded_by"]) == (
        "Emails in a public mailing list",
        "check dates",
        "Analyst A",
    )
    ws_data = store.get_workspace(inv["id"])
    assert {e["id"]: e["relationship_ids"] for e in ws_data["evidence"]} == {
        e1["id"]: [r["id"]],
        e2["id"]: [r["id"]],
    }


def test_deleting_an_entity_deletes_its_relationships(store, inv):
    a, b, c = (_entity(store, inv, n) for n in "ABC")
    _rel(store, inv, a, b)
    keep = _rel(store, inv, b, c)
    assert store.get_item(inv["id"], "entities", b["id"])["relationship_count"] == 2
    store.delete_item(inv["id"], "entities", a["id"])
    assert [r["id"] for r in store.get_workspace(inv["id"])["relationships"]] == [keep["id"]]


def test_deleted_citations_flag_a_documented_relationship(store, inv):
    a, b = _entity(store, inv, "A"), _entity(store, inv, "B")
    ev = store.add_item(inv["id"], "evidence", {"description": "e"})
    r = _rel(store, inv, a, b, status="documented", evidence_ids=[ev["id"]])
    store.delete_item(inv["id"], "evidence", ev["id"])
    after = store.get_item(inv["id"], "relationships", r["id"])
    # Not silently downgraded: still documented, flagged for the investigator to resolve.
    assert after["status"] == "documented" and after["evidence_ids"] == []
    assert after["unsupported"] is True


def test_nothing_creates_entities_or_relationships_by_itself(store, inv):
    t = store.add_item(inv["id"], "targets", {"kind": "domain", "value": "example.com"})
    store.add_item(
        inv["id"],
        "findings",
        {"title": "x", "target_id": t["id"], "source_url": "https://example.com/"},
    )
    store.add_item(inv["id"], "evidence", {"description": "y", "target_id": t["id"]})
    data = store.get_workspace(inv["id"])
    assert data["entities"] == [] and data["relationships"] == []


def test_trace_relationship(store, inv):
    a, b = _entity(store, inv, "A"), _entity(store, inv, "B")
    src = store.add_item(
        inv["id"],
        "sources",
        {"url": "https://example.com/r", "reliability": "B", "reliability_rationale": "r"},
    )
    ev = store.add_item(
        inv["id"], "evidence", {"description": "e", "source_id": src["id"], "kind": "reported"}
    )
    f = store.add_item(inv["id"], "findings", {"title": "F"})
    r = _rel(store, inv, a, b, status="documented", evidence_ids=[ev["id"]], finding_id=f["id"])
    trace = store.trace_relationship(inv["id"], r["id"])
    assert (trace["from_entity"]["label"], trace["to_entity"]["label"]) == ("A", "B")
    assert trace["finding"]["title"] == "F"
    assert trace["evidence"][0]["kind"] == "reported"
    assert trace["evidence"][0]["source"]["reliability"] == "B"
    with pytest.raises(NotFound):
        store.trace_relationship(inv["id"], "0" * 32)


def test_investigation_counts_unchanged_and_delete_cascades(store, inv, tmp_path):
    a, b = _entity(store, inv, "A"), _entity(store, inv, "B")
    ev = store.add_item(inv["id"], "evidence", {"description": "e"})
    _rel(store, inv, a, b, evidence_ids=[ev["id"]])
    assert set(store.list_investigations()[0]["counts"]) == set(ws.SECTIONS)
    store.delete_investigation(inv["id"])
    for table in ("entities", "relationships", "relationship_evidence"):
        assert store._conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0, table


# --- migration ------------------------------------------------------------------------


def test_schema_2_database_gains_the_graph_tables_without_data_changes(tmp_path):
    db = tmp_path / "workspace.db"
    with WorkspaceStore(db) as s:
        inv = s.create_investigation("Before the graph")
        s.add_item(inv["id"], "notes", {"body": "kept"})
    conn = sqlite3.connect(db)
    conn.executescript(
        "DROP TABLE relationship_evidence; DROP TABLE relationships; DROP TABLE entities;"
        "PRAGMA user_version=2;"
    )
    conn.close()
    with WorkspaceStore(db) as s:
        data = s.get_workspace(inv["id"])
        assert [n["body"] for n in data["notes"]] == ["kept"]
        assert data["entities"] == [] and data["relationships"] == []
        _entity(s, inv, "New")
    conn = sqlite3.connect(db)
    try:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == ws.SCHEMA_VERSION == 3
    finally:
        conn.close()


# --- API ------------------------------------------------------------------------------


@pytest_asyncio.fixture
async def client(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENOSINT_HOME", str(tmp_path / "home"))
    import openosint.web_server as w

    w._RATE_STORE.clear()
    app = w.create_app(host="127.0.0.1")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://127.0.0.1") as c:
        yield c
    w._RATE_STORE.clear()


async def test_api_graph_lifecycle(client):
    inv = (await client.post("/api/investigations", json={"title": "API graph"})).json()
    base = f"/api/investigations/{inv['id']}"
    a = (await client.post(f"{base}/entities", json={"kind": "person", "label": "A"})).json()
    b = (await client.post(f"{base}/entities", json={"kind": "organization", "label": "B"})).json()
    r = await client.post(
        f"{base}/relationships",
        json={
            "from_entity_id": a["id"],
            "to_entity_id": b["id"],
            "label": "works for",
            "status": "documented",
        },
    )
    assert r.status_code == 422 and "cite" in r.json()["detail"]
    ev = (await client.post(f"{base}/evidence", json={"description": "Staff page"})).json()
    r = await client.post(
        f"{base}/relationships",
        json={
            "from_entity_id": a["id"],
            "to_entity_id": b["id"],
            "label": "works for",
            "status": "documented",
            "evidence_ids": [ev["id"]],
        },
    )
    assert r.status_code == 201, r.text
    rel = r.json()
    r = await client.put(f"{base}/entities/{a['id']}/position", json={"x": 1, "y": 2})
    assert r.json() == {"id": a["id"], "pos_x": 1.0, "pos_y": 2.0}
    assert (
        await client.put(f"{base}/entities/{a['id']}/position", json={"x": "a", "y": 2})
    ).status_code == 422
    trace = (await client.get(f"{base}/relationships/{rel['id']}/trace")).json()
    assert trace["evidence"][0]["id"] == ev["id"]
    full = (await client.get(base)).json()
    assert len(full["entities"]) == 2 and full["relationships"][0]["label"] == "works for"
    r = await client.patch(f"{base}/relationships/{rel['id']}", json={"confidence": "high"})
    assert r.json()["confidence"] == "high"
    assert (
        await client.post(f"{base}/entities", json={"kind": "person", "label": "x", "bogus": 1})
    ).status_code == 422
    assert (await client.delete(f"{base}/entities/{a['id']}")).json()["status"] == "deleted"
    assert (await client.get(base)).json()["relationships"] == []
    assert (await client.get(f"{base}/relationships/{rel['id']}/trace")).status_code == 404


async def test_api_graph_routes_are_restricted(client, monkeypatch):
    import openosint.web_server as w

    inv = (await client.post("/api/investigations", json={"title": "R"})).json()
    base = f"/api/investigations/{inv['id']}"
    a = (await client.post(f"{base}/entities", json={"kind": "person", "label": "A"})).json()
    monkeypatch.setattr(w, "DEMO_MODE", True)
    for method, path, body in (
        ("POST", f"{base}/entities", {"kind": "person", "label": "B"}),
        ("PUT", f"{base}/entities/{a['id']}/position", {"x": 0, "y": 0}),
        ("DELETE", f"{base}/entities/{a['id']}", None),
        ("GET", f"{base}/relationships/{'0' * 32}/trace", None),
    ):
        r = await client.request(method, path, json=body)
        assert r.status_code == 403, (method, path)


async def test_api_cross_site_graph_writes_are_rejected(client):
    inv = (await client.post("/api/investigations", json={"title": "X"})).json()
    r = await client.post(
        f"/api/investigations/{inv['id']}/entities",
        json={"kind": "person", "label": "A"},
        headers={"Origin": "https://evil.example", "Sec-Fetch-Site": "cross-site"},
    )
    assert r.status_code == 403
    assert (await client.get(f"/api/investigations/{inv['id']}")).json()["entities"] == []


# --- page wiring (static) -------------------------------------------------------------------


def test_page_loads_the_vendored_graph_library_only():
    assert '<script src="/static/vendor/cytoscape/cytoscape.min.js"></script>' in PAGE
    assert PAGE.index("cytoscape.min.js") < PAGE.index('<script type="module">')
    assert "http://" not in GRAPH_JS and "https://" not in GRAPH_JS
    assert "from '/static/workspace-graph.js'" in SCRIPT


def test_graph_code_never_injects_html_or_calls_out():
    for source in (SCRIPT, GRAPH_JS):
        for sink in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval("):
            assert sink not in source, sink
    assert "fetch(" not in GRAPH_JS and "import(" not in GRAPH_JS


def test_destructive_graph_actions_are_confirmed():
    assert "window.confirm(message)" in SCRIPT
    assert "relationship(s)" in SCRIPT and "This cannot be undone." in SCRIPT
    assert "Rearrange every entity? Your current node positions are replaced." in SCRIPT


def test_nodes_get_distinct_positions_before_cytoscape_sees_them():
    # Regression: parallel edges between nodes at the same point (where unplaced nodes
    # started) made Cytoscape throw ("reading 'corners'"), so such graphs never rendered.
    mount = SCRIPT[SCRIPT.index("function mountGraph(inv)") :]
    assert mount.index("withDistinctPositions(graphElements(inv))") < mount.index(
        "window.cytoscape({"
    )


def test_new_relationships_start_as_hypotheses():
    assert (
        "if (section === 'relationships') return { status: 'hypothesis', confidence: 'low'"
        in SCRIPT
    )
