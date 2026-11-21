"""Timeline and correlation in the research workspace: events, dates, links, correlations,
schema 4 migration, the API and the page wiring."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from openosint import workspace as ws
from openosint.workspace import InvalidInput, NotFound, WorkspaceStore

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = (ROOT / "openosint" / "web" / "static" / "workspace.js").read_text(encoding="utf-8")
TIMELINE_JS = (ROOT / "openosint" / "web" / "static" / "workspace-timeline.js").read_text(
    encoding="utf-8"
)


@pytest.fixture
def store(tmp_path):
    with WorkspaceStore(tmp_path / "workspace.db") as s:
        yield s


@pytest.fixture
def inv(store):
    return store.create_investigation("Example Org chronology")


def _event(store, inv, title="Event", **extra):
    data = {"title": title, "start_date": "2026-03-01", **extra}
    return store.add_item(inv["id"], "events", data)


# --- events: fields and defaults ----------------------------------------------------


def test_event_defaults_are_unverified(store, inv):
    ev = _event(store, inv)
    assert (ev["provenance"], ev["category"], ev["date_precision"]) == (
        "hypothesis",
        "other",
        "exact",
    )
    assert ev["links"] == [] and ev["correlation_ids"] == []
    assert "verified" not in ws.EVENT_PROVENANCE


def test_event_fields_round_trip(store, inv):
    ev = _event(
        store,
        inv,
        "Domain registered",
        description="Registry shows a new registration",
        category="registration",
        provenance="reported",
        notes="check the registrar",
    )
    assert (ev["title"], ev["description"], ev["category"], ev["provenance"], ev["notes"]) == (
        "Domain registered",
        "Registry shows a new registration",
        "registration",
        "reported",
        "check the registrar",
    )
    edited = store.update_item(inv["id"], "events", ev["id"], {"provenance": "observation"})
    assert edited["provenance"] == "observation" and edited["title"] == "Domain registered"


# --- dates ---------------------------------------------------------------------------


def test_date_only_event(store, inv):
    ev = _event(store, inv, start_date="2026-03-01")
    assert (ev["start_time"], ev["timezone"], ev["sort_key"]) == ("", "", "2026-03-01T00:00")


def test_time_with_timezone_sorts_in_utc_and_keeps_what_was_entered(store, inv):
    ev = _event(
        store, inv, start_date="2026-03-01", start_time="23:30", timezone="America/New_York"
    )
    assert (ev["start_date"], ev["start_time"], ev["timezone"]) == (
        "2026-03-01",
        "23:30",
        "America/New_York",
    )
    assert ev["sort_key"] == "2026-03-02T04:30"


@pytest.mark.parametrize(
    "tz, key",
    [
        ("UTC", "2026-03-01T12:00"),
        ("+05:30", "2026-03-01T06:30"),
        ("UTC-03:00", "2026-03-01T15:00"),
    ],
)
def test_utc_and_fixed_offsets(store, inv, tz, key):
    assert _event(store, inv, start_time="12:00", timezone=tz)["sort_key"] == key


def test_time_without_timezone_keeps_wall_clock(store, inv):
    assert _event(store, inv, start_time="09:15")["sort_key"] == "2026-03-01T09:15"


@pytest.mark.parametrize(
    "start, key",
    [
        ("2026", "2026-01-01T00:00"),
        ("2026-07", "2026-07-01T00:00"),
        ("2026-07-04", "2026-07-04T00:00"),
    ],
)
def test_approximate_dates(store, inv, start, key):
    ev = _event(store, inv, date_precision="approximate", start_date=start)
    assert (ev["start_date"], ev["sort_key"]) == (start, key)


def test_range(store, inv):
    ev = _event(
        store,
        inv,
        date_precision="range",
        start_date="2026-03-03",
        end_date="2026-03-10",
        end_time="18:00",
    )
    assert (ev["end_date"], ev["end_time"], ev["sort_key"]) == (
        "2026-03-10",
        "18:00",
        "2026-03-03T00:00",
    )
    same_day = _event(
        store,
        inv,
        date_precision="range",
        start_date="2026-03-03",
        start_time="09:00",
        end_date="2026-03-03",
        end_time="17:00",
    )
    assert same_day["end_time"] == "17:00"


def test_end_fields_are_cleared_for_non_ranges(store, inv):
    ev = _event(store, inv, date_precision="range", start_date="2026-03-03", end_date="2026-03-10")
    exact = store.update_item(inv["id"], "events", ev["id"], {"date_precision": "exact"})
    assert (exact["end_date"], exact["end_time"]) == ("", "")


@pytest.mark.parametrize(
    "extra, message",
    [
        ({"start_date": ""}, "start_date is required"),
        ({"start_date": "2026-02-30"}, "not a valid date"),
        ({"start_date": "01/03/2026"}, "YYYY-MM-DD"),
        ({"start_date": "2026-03"}, "YYYY-MM-DD"),  # partial dates only when approximate
        ({"date_precision": "approximate", "start_date": "2026-13"}, "not a valid date"),
        ({"date_precision": "approximate", "start_date": "26"}, "YYYY, YYYY-MM or YYYY-MM-DD"),
        (
            {"date_precision": "approximate", "start_date": "2026-03", "start_time": "10:00"},
            "needs a full date",
        ),
        ({"start_time": "24:00"}, "HH:MM"),
        ({"start_time": "9:5"}, "HH:MM"),
        ({"start_time": "10:00", "timezone": "Mars/Olympus"}, "unknown timezone"),
        ({"start_time": "10:00", "timezone": "../../etc/passwd"}, "timezone must be"),
        ({"start_time": "10:00", "timezone": "+15:00"}, "timezone must be"),
        ({"date_precision": "range"}, "end_date is required"),
        ({"date_precision": "range", "end_date": "2026-02-28"}, "ends before it starts"),
        (
            {
                "date_precision": "range",
                "start_time": "18:00",
                "end_date": "2026-03-01",
                "end_time": "09:00",
            },
            "ends before it starts",
        ),
        ({"date_precision": "sometime"}, "date_precision must be one of"),
        ({"category": "gossip"}, "category must be one of"),
        ({"provenance": "verified"}, "provenance must be one of"),
        ({"title": ""}, "title is required"),
        ({"title": "two\nlines"}, "one line"),
    ],
)
def test_event_validation(store, inv, extra, message):
    with pytest.raises(InvalidInput, match=message):
        _event(store, inv, **extra)
    assert store.get_workspace(inv["id"])["events"] == []


def test_events_are_returned_chronologically(store, inv):
    _event(store, inv, "c", start_date="2026-05-01")
    _event(store, inv, "a", date_precision="approximate", start_date="2025")
    _event(
        store, inv, "b", start_date="2026-03-01", start_time="23:30", timezone="America/New_York"
    )
    _event(store, inv, "b2", start_date="2026-03-02", start_time="01:00", timezone="UTC")
    titles = [e["title"] for e in store.get_workspace(inv["id"])["events"]]
    assert titles == ["a", "b2", "b", "c"]  # 01:00 UTC is before 23:30 New York (04:30 UTC)


# --- links -----------------------------------------------------------------------------


@pytest.fixture
def linkables(store, inv):
    i = inv["id"]
    return {
        "target": store.add_item(i, "targets", {"kind": "domain", "value": "example.com"}),
        "entity": store.add_item(i, "entities", {"kind": "organization", "label": "Example Org"}),
        "finding": store.add_item(i, "findings", {"title": "Registered by Example Org"}),
        "evidence": store.add_item(i, "evidence", {"description": "Registry record"}),
        "source": store.add_item(i, "sources", {"url": "https://example.com/registry"}),
    }


def test_event_links_to_every_kind(store, inv, linkables):
    links = [{"kind": k, "id": v["id"]} for k, v in linkables.items()]
    ev = _event(store, inv, links=links + links[:1])  # duplicates are dropped
    got = {(link["kind"], link["id"]) for link in ev["links"]}
    assert got == {(k, v["id"]) for k, v in linkables.items()}
    labels = {link["kind"]: link["label"] for link in ev["links"]}
    assert labels["target"] == "domain: example.com" and labels["entity"] == "Example Org"
    assert labels["source"] == "https://example.com/registry"
    cleared = store.update_item(inv["id"], "events", ev["id"], {"links": []})
    assert cleared["links"] == []


@pytest.mark.parametrize(
    "links, message",
    [
        ([{"kind": "evidence", "id": "0" * 32}], "does not belong"),
        ([{"kind": "note", "id": "0" * 32}], "link kind must be one of"),
        ([{"kind": "evidence"}], "evidence link needs an id"),
        (["not-a-dict"], "kind and an id"),
        ("not-a-list", "must be a list"),
        ([{"kind": "evidence", "id": "0" * 32}] * 101, "at most 100"),
    ],
)
def test_link_validation(store, inv, links, message):
    with pytest.raises(InvalidInput, match=message):
        _event(store, inv, links=links)


def test_links_cannot_cross_investigations(store, inv):
    other = store.create_investigation("Other")
    foreign = store.add_item(other["id"], "evidence", {"description": "elsewhere"})
    with pytest.raises(InvalidInput, match="does not belong"):
        _event(store, inv, links=[{"kind": "evidence", "id": foreign["id"]}])


@pytest.mark.parametrize("kind", ["target", "entity", "finding", "evidence", "source"])
def test_deleting_a_linked_item_removes_the_link_but_keeps_the_event(store, inv, linkables, kind):
    section = ws.EVENT_LINK_KINDS[kind]
    ev = _event(store, inv, links=[{"kind": kind, "id": linkables[kind]["id"]}])
    store.delete_item(inv["id"], section, linkables[kind]["id"])
    kept = store.get_item(inv["id"], "events", ev["id"])
    assert kept["links"] == []
    count = store._conn.execute("SELECT COUNT(*) FROM event_links").fetchone()[0]
    assert count == 0


# --- correlations -------------------------------------------------------------------------


def test_correlation_defaults_to_a_hypothesis(store, inv):
    a, b = _event(store, inv, "a", start_date="2026-03-05"), _event(store, inv, "b")
    c = store.add_item(
        inv["id"],
        "correlations",
        {"title": "Same week", "explanation": "Close in time", "event_ids": [a["id"], b["id"]]},
    )
    assert (c["status"], c["confidence"]) == ("hypothesis", "low")
    assert c["event_ids"] == [b["id"], a["id"]]  # chronological
    assert c["incomplete"] is False and c["unsupported"] is False
    assert store.get_item(inv["id"], "events", a["id"])["correlation_ids"] == [c["id"]]


def test_correlation_needs_two_events(store, inv):
    a = _event(store, inv)
    for ids in ([], [a["id"]], [a["id"], a["id"]]):
        with pytest.raises(InvalidInput, match="at least two events"):
            store.add_item(inv["id"], "correlations", {"title": "x", "event_ids": ids})


def test_documented_correlation_must_cite_something(store, inv, linkables):
    a, b = _event(store, inv, "a"), _event(store, inv, "b")
    base = {"title": "x", "event_ids": [a["id"], b["id"]], "status": "documented"}
    with pytest.raises(InvalidInput, match="must cite a finding or evidence"):
        store.add_item(inv["id"], "correlations", base)
    by_evidence = store.add_item(
        inv["id"], "correlations", {**base, "evidence_ids": [linkables["evidence"]["id"]]}
    )
    assert by_evidence["evidence_ids"] == [linkables["evidence"]["id"]]
    by_finding = store.add_item(
        inv["id"], "correlations", {**base, "finding_id": linkables["finding"]["id"]}
    )
    assert by_finding["finding_title"] == "Registered by Example Org"
    with pytest.raises(InvalidInput, match="must cite"):
        store.update_item(inv["id"], "correlations", by_evidence["id"], {"evidence_ids": []})
    hypo = store.add_item(inv["id"], "correlations", {**base, "status": "hypothesis"})
    with pytest.raises(InvalidInput, match="must cite"):
        store.update_item(inv["id"], "correlations", hypo["id"], {"status": "documented"})


def test_correlation_flags_instead_of_silent_changes(store, inv, linkables):
    a, b = _event(store, inv, "a"), _event(store, inv, "b")
    c = store.add_item(
        inv["id"],
        "correlations",
        {
            "title": "x",
            "event_ids": [a["id"], b["id"]],
            "status": "documented",
            "evidence_ids": [linkables["evidence"]["id"]],
        },
    )
    store.delete_item(inv["id"], "evidence", linkables["evidence"]["id"])
    store.delete_item(inv["id"], "events", a["id"])
    after = store.get_item(inv["id"], "correlations", c["id"])
    assert after["status"] == "documented"
    assert after["unsupported"] is True and after["incomplete"] is True
    assert after["event_ids"] == [b["id"]]


@pytest.mark.parametrize(
    "extra, message",
    [
        ({"title": ""}, "title is required"),
        ({"status": "proven"}, "status must be one of"),
        ({"confidence": "total"}, "confidence must be one of"),
        ({"evidence_ids": ["0" * 32]}, "does not belong"),
        ({"finding_id": "0" * 32}, "does not belong"),
        ({"recorded_by": "a\nb"}, "one line"),
    ],
)
def test_correlation_validation(store, inv, extra, message):
    a, b = _event(store, inv, "a"), _event(store, inv, "b")
    with pytest.raises(InvalidInput, match=message):
        store.add_item(
            inv["id"], "correlations", {"title": "x", "event_ids": [a["id"], b["id"]], **extra}
        )


def test_nothing_creates_events_or_correlations_by_itself(store, inv, linkables):
    _event(store, inv, "a")
    _event(store, inv, "b", start_date="2026-03-01")
    data = store.get_workspace(inv["id"])
    assert data["correlations"] == []  # same date, still not correlated
    assert [len(e["links"]) for e in data["events"]] == [0, 0]


def test_investigation_delete_and_counts(store, inv, linkables):
    a, b = (
        _event(store, inv, "a", links=[{"kind": "evidence", "id": linkables["evidence"]["id"]}]),
        _event(store, inv, "b"),
    )
    store.add_item(inv["id"], "correlations", {"title": "x", "event_ids": [a["id"], b["id"]]})
    counts = store.list_investigations()[0]["counts"]
    assert set(counts) == set(ws.ALL_SECTIONS)
    assert (counts["events"], counts["correlations"]) == (2, 1)
    store.delete_investigation(inv["id"])
    for table in (
        "events",
        "event_links",
        "correlations",
        "correlation_events",
        "correlation_evidence",
    ):
        assert store._conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0, table


def test_unknown_ids(store, inv):
    with pytest.raises(NotFound):
        store.get_item(inv["id"], "events", "0" * 32)
    with pytest.raises(NotFound):
        store.update_item(inv["id"], "correlations", "0" * 32, {"title": "x"})


# --- migration ----------------------------------------------------------------------------


def test_schema_3_database_gains_the_timeline_tables_without_data_changes(tmp_path):
    db = tmp_path / "workspace.db"
    with WorkspaceStore(db) as s:
        inv = s.create_investigation("Before the timeline")
        s.add_item(inv["id"], "entities", {"kind": "person", "label": "kept"})
    conn = sqlite3.connect(db)
    conn.executescript(
        "DROP TABLE correlation_evidence; DROP TABLE correlation_events; DROP TABLE correlations;"
        "DROP TABLE event_links; DROP TABLE events; PRAGMA user_version=3;"
    )
    conn.close()
    with WorkspaceStore(db) as s:
        data = s.get_workspace(inv["id"])
        assert [e["label"] for e in data["entities"]] == ["kept"]
        assert data["events"] == [] and data["correlations"] == []
        _event(s, inv)
    conn = sqlite3.connect(db)
    try:
        # Upgraded straight to the current schema (4 added the timeline tables).
        assert conn.execute("PRAGMA user_version").fetchone()[0] == ws.SCHEMA_VERSION >= 4
    finally:
        conn.close()


# --- API ------------------------------------------------------------------------------------


@pytest_asyncio.fixture
async def client(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENOSINT_HOME", str(tmp_path / "home"))
    import openosint.web_server as w

    w._RATE_STORE.clear()
    app = w.create_app(host="127.0.0.1")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://127.0.0.1") as c:
        yield c
    w._RATE_STORE.clear()


async def test_api_timeline_lifecycle(client):
    inv = (await client.post("/api/investigations", json={"title": "API timeline"})).json()
    base = f"/api/investigations/{inv['id']}"
    ev = (await client.post(f"{base}/evidence", json={"description": "Post archive"})).json()
    r = await client.post(
        f"{base}/events",
        json={
            "title": "Post published",
            "start_date": "2026-03-01",
            "start_time": "10:00",
            "timezone": "Europe/London",
            "provenance": "reported",
            "category": "publication",
            "links": [{"kind": "evidence", "id": ev["id"]}],
        },
    )
    assert r.status_code == 201, r.text
    e1 = r.json()
    e2 = (
        await client.post(f"{base}/events", json={"title": "Reply", "start_date": "2026-03-02"})
    ).json()
    assert (
        await client.post(f"{base}/events", json={"title": "x", "start_date": "2026-02-31"})
    ).status_code == 422
    assert (
        await client.post(
            f"{base}/events",
            json={
                "title": "x",
                "start_date": "2026-03-01",
                "links": [{"kind": "bogus", "id": "x"}],
            },
        )
    ).status_code == 422
    assert (
        await client.post(
            f"{base}/events", json={"title": "x", "start_date": "2026-03-01", "verified": True}
        )
    ).status_code == 422
    r = await client.post(
        f"{base}/correlations",
        json={
            "title": "Reply to the post",
            "event_ids": [e1["id"], e2["id"]],
            "status": "documented",
        },
    )
    assert r.status_code == 422 and "cite" in r.json()["detail"]
    c = (
        await client.post(
            f"{base}/correlations",
            json={"title": "Reply to the post", "event_ids": [e2["id"], e1["id"]]},
        )
    ).json()
    assert c["status"] == "hypothesis" and c["event_ids"] == [e1["id"], e2["id"]]
    r = await client.patch(
        f"{base}/events/{e2['id']}", json={"start_time": "08:00", "timezone": "UTC"}
    )
    assert r.json()["sort_key"] == "2026-03-02T08:00"
    full = (await client.get(base)).json()
    assert [e["id"] for e in full["events"]] == [e1["id"], e2["id"]]
    assert full["events"][0]["links"][0]["kind"] == "evidence"
    assert (await client.delete(f"{base}/correlations/{c['id']}")).json()["status"] == "deleted"
    assert len((await client.get(base)).json()["events"]) == 2  # events kept


async def test_api_timeline_routes_are_restricted(client, monkeypatch):
    import openosint.web_server as w

    inv = (await client.post("/api/investigations", json={"title": "R"})).json()
    base = f"/api/investigations/{inv['id']}"
    ev = (
        await client.post(f"{base}/events", json={"title": "a", "start_date": "2026-01-01"})
    ).json()
    monkeypatch.setattr(w, "DEMO_MODE", True)
    for method, path, body in (
        ("POST", f"{base}/events", {"title": "b", "start_date": "2026-01-01"}),
        ("PATCH", f"{base}/events/{ev['id']}", {"title": "c"}),
        ("DELETE", f"{base}/events/{ev['id']}", None),
        ("POST", f"{base}/correlations", {"title": "x", "event_ids": []}),
    ):
        assert (await client.request(method, path, json=body)).status_code == 403, (method, path)


async def test_api_cross_site_event_writes_are_rejected(client):
    inv = (await client.post("/api/investigations", json={"title": "X"})).json()
    r = await client.post(
        f"/api/investigations/{inv['id']}/events",
        json={"title": "a", "start_date": "2026-01-01"},
        headers={"Origin": "https://evil.example", "Sec-Fetch-Site": "cross-site"},
    )
    assert r.status_code == 403


# --- page wiring (static) -------------------------------------------------------------------


def test_timeline_code_never_injects_html_or_calls_out():
    for source in (SCRIPT, TIMELINE_JS):
        for sink in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval("):
            assert sink not in source, sink
    assert (
        "fetch(" not in TIMELINE_JS
        and "http://" not in TIMELINE_JS
        and "https://" not in TIMELINE_JS
    )
    assert "from '/static/workspace-timeline.js'" in SCRIPT


def test_timeline_defaults_and_confirmations():
    assert "provenance: 'hypothesis', date_precision: 'exact'" in SCRIPT
    assert "status: 'hypothesis', confidence: 'low', event_ids: []" in SCRIPT
    assert "correlation(s), which will lose it." in SCRIPT
    assert "Its events are kept. This cannot be undone." in SCRIPT
    assert "PAGE_SIZE = 100" in TIMELINE_JS
