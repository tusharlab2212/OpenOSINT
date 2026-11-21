"""Research workspace store (openosint/workspace.py): CRUD, links, validation, persistence."""

from __future__ import annotations

import os
import sqlite3
import stat
import sys

import pytest

from openosint import workspace as ws
from openosint.workspace import Conflict, InvalidInput, NotFound, WorkspaceStore


@pytest.fixture
def db(tmp_path):
    return tmp_path / "data" / "workspace.db"


@pytest.fixture
def store(db):
    with WorkspaceStore(db) as s:
        yield s


@pytest.fixture
def inv(store):
    return store.create_investigation("Example Org exposure", "Public footprint of example.com")


# --- investigations ----------------------------------------------------------


def test_create_and_get_investigation(store):
    created = store.create_investigation("  Case A  ", "desc")
    assert created["title"] == "Case A"
    assert created["description"] == "desc"
    assert ws.is_valid_id(created["id"])
    assert created["created_at"] == created["updated_at"]
    assert store.get_investigation(created["id"]) == created


def test_description_is_optional(store):
    assert store.create_investigation("No description")["description"] == ""


def test_list_investigations_with_counts(store, inv):
    other = store.create_investigation("Second")
    store.add_item(inv["id"], "targets", {"kind": "domain", "value": "example.com"})
    store.add_item(inv["id"], "notes", {"body": "start with DNS"})
    listed = store.list_investigations()
    assert {i["id"] for i in listed} == {inv["id"], other["id"]}
    # Most recently updated first: adding items touched `inv`.
    assert listed[0]["id"] == inv["id"]
    assert listed[0]["counts"] == {
        "targets": 1,
        "sources": 0,
        "findings": 0,
        "notes": 1,
        "evidence": 0,
    }


def test_rename_and_edit_description(store, inv):
    updated = store.update_investigation(inv["id"], {"title": "Renamed", "description": ""})
    assert updated["title"] == "Renamed" and updated["description"] == ""
    assert updated["updated_at"] >= inv["updated_at"]
    only_desc = store.update_investigation(inv["id"], {"description": "new"})
    assert only_desc["title"] == "Renamed"


def test_rename_to_empty_title_is_rejected(store, inv):
    with pytest.raises(InvalidInput, match="title is required"):
        store.update_investigation(inv["id"], {"title": "   "})
    assert store.get_investigation(inv["id"])["title"] == inv["title"]


def test_delete_investigation_removes_everything_in_it(store, inv, db):
    t = store.add_item(inv["id"], "targets", {"kind": "domain", "value": "example.com"})
    store.add_item(
        inv["id"],
        "findings",
        {"title": "f", "source_url": "https://example.com/", "target_id": t["id"]},
    )
    store.add_item(inv["id"], "evidence", {"description": "e"})
    store.add_item(inv["id"], "notes", {"body": "n"})
    store.delete_investigation(inv["id"])
    with pytest.raises(NotFound):
        store.get_investigation(inv["id"])
    conn = sqlite3.connect(db)
    try:
        for table in ws.SECTIONS:
            assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0, table
    finally:
        conn.close()


def test_unknown_or_malformed_ids_are_not_found(store, inv):
    for bad in ("0" * 32, "../etc", "", "x" * 32, inv["id"].upper()):
        with pytest.raises(NotFound):
            store.get_investigation(bad)
    with pytest.raises(NotFound):
        store.delete_investigation("0" * 32)
    with pytest.raises(NotFound):
        store.add_item(inv["id"], "secrets", {})


@pytest.mark.parametrize(
    "title, description, message",
    [
        ("", "", "title is required"),
        ("x" * (ws.TITLE_MAX + 1), "", "longer than"),
        ("ok", "x" * (ws.TEXT_MAX + 1), "longer than"),
        ("bad\x00title", "", "control characters"),
        (123, "", "must be text"),
    ],
)
def test_investigation_validation(store, title, description, message):
    with pytest.raises(InvalidInput, match=message):
        store.create_investigation(title, description)


# --- targets -----------------------------------------------------------------


@pytest.mark.parametrize(
    "kind, value, stored",
    [
        ("domain", "Example.COM.", "example.com"),
        ("email", "Person@Example.com", "person@example.com"),
        ("url", "https://example.com/about", "https://example.com/about"),
        ("username", "some_handle", "some_handle"),
        ("ip", "192.0.2.10", "192.0.2.10"),
        ("phone", "+1 555 0100", "+1 555 0100"),
        ("other", "Example Org Ltd", "Example Org Ltd"),
    ],
)
def test_target_kinds_are_normalised(store, inv, kind, value, stored):
    assert store.add_item(inv["id"], "targets", {"kind": kind, "value": value})["value"] == stored


@pytest.mark.parametrize(
    "data, message",
    [
        ({"kind": "domain", "value": "not a domain"}, "not a domain"),
        ({"kind": "email", "value": "no-at-sign"}, "not an email"),
        ({"kind": "url", "value": "javascript:alert(1)"}, "http"),
        ({"kind": "password", "value": "x"}, "kind must be one of"),
        ({"kind": "username", "value": ""}, "value is required"),
        ({"kind": "username", "value": "two\nlines"}, "one line"),
    ],
)
def test_target_validation(store, inv, data, message):
    with pytest.raises(InvalidInput, match=message):
        store.add_item(inv["id"], "targets", data)


def test_duplicate_target_is_a_conflict(store, inv):
    store.add_item(inv["id"], "targets", {"kind": "domain", "value": "example.com"})
    with pytest.raises(Conflict):
        store.add_item(inv["id"], "targets", {"kind": "domain", "value": "EXAMPLE.com"})
    # The same value in another investigation is fine.
    other = store.create_investigation("Other")
    store.add_item(other["id"], "targets", {"kind": "domain", "value": "example.com"})


def test_edit_target_revalidates_against_its_kind(store, inv):
    t = store.add_item(inv["id"], "targets", {"kind": "domain", "value": "example.com"})
    assert (
        store.update_item(inv["id"], "targets", t["id"], {"value": "Example.ORG"})["value"]
        == "example.org"
    )
    with pytest.raises(InvalidInput):
        store.update_item(inv["id"], "targets", t["id"], {"kind": "email"})


# --- findings ----------------------------------------------------------------


def test_finding_fields_and_defaults(store, inv):
    f = store.add_item(inv["id"], "findings", {"title": "Mail handled by a third party"})
    assert f["confidence"] == "low"  # never inferred upward
    assert f["kind"] == "observation"
    assert f["recorded_on"] == ws._today()
    assert f["source_id"] is None and f["target_id"] is None and f["source_url"] is None


def test_finding_with_all_fields(store, inv):
    t = store.add_item(inv["id"], "targets", {"kind": "domain", "value": "example.com"})
    f = store.add_item(
        inv["id"],
        "findings",
        {
            "title": "SPF allows a third-party sender",
            "description": "TXT record includes an external include.",
            "kind": "conclusion",
            "confidence": "High",
            "source_url": "https://example.com/dns",
            "target_id": t["id"],
            "notes": "check again next week",
            "recorded_on": "2026-01-15",
        },
    )
    assert f["confidence"] == "high" and f["kind"] == "conclusion"
    assert f["source_url"] == "https://example.com/dns"
    assert (f["target_kind"], f["target_value"]) == ("domain", "example.com")
    assert f["recorded_on"] == "2026-01-15" and f["notes"] == "check again next week"


@pytest.mark.parametrize(
    "data, message",
    [
        ({"title": ""}, "title is required"),
        ({"title": "x", "confidence": "certain"}, "confidence must be one of"),
        ({"title": "x", "kind": "fact"}, "kind must be one of"),
        ({"title": "x", "source_url": "javascript:alert(1)"}, "http"),
        ({"title": "x", "source_url": "https://exa mple.com"}, "http"),
        ({"title": "x", "recorded_on": "15/01/2026"}, "YYYY-MM-DD"),
        ({"title": "x", "recorded_on": "2026-02-30"}, "not a valid date"),
        ({"title": "x", "target_id": "0" * 32}, "does not belong"),
        ({"title": "x", "target_id": "nope"}, "not a valid id"),
    ],
)
def test_finding_validation(store, inv, data, message):
    with pytest.raises(InvalidInput, match=message):
        store.add_item(inv["id"], "findings", data)


def test_links_cannot_cross_investigations(store, inv):
    other = store.create_investigation("Other")
    foreign = store.add_item(other["id"], "targets", {"kind": "domain", "value": "example.org"})
    foreign_src = store.add_item(other["id"], "sources", {"url": "https://example.org/"})
    with pytest.raises(InvalidInput, match="does not belong"):
        store.add_item(inv["id"], "findings", {"title": "x", "target_id": foreign["id"]})
    with pytest.raises(InvalidInput, match="does not belong"):
        store.add_item(inv["id"], "findings", {"title": "x", "source_id": foreign_src["id"]})
    with pytest.raises(NotFound):
        store.update_item(inv["id"], "targets", foreign["id"], {"notes": "x"})


def test_source_url_creates_and_reuses_one_source(store, inv):
    f1 = store.add_item(
        inv["id"], "findings", {"title": "a", "source_url": "https://example.com/p"}
    )
    f2 = store.add_item(
        inv["id"], "findings", {"title": "b", "source_url": "https://example.com/p"}
    )
    e = store.add_item(
        inv["id"], "evidence", {"description": "c", "source_url": "https://example.com/p"}
    )
    assert f1["source_id"] == f2["source_id"] == e["source_id"]
    sources = store.get_workspace(inv["id"])["sources"]
    assert len(sources) == 1
    assert (sources[0]["finding_count"], sources[0]["evidence_count"]) == (2, 1)


def test_finding_can_link_an_existing_source_by_id(store, inv):
    src = store.add_item(
        inv["id"], "sources", {"url": "https://example.com/report", "title": "Report"}
    )
    f = store.add_item(inv["id"], "findings", {"title": "x", "source_id": src["id"]})
    assert f["source_url"] == "https://example.com/report"
    with pytest.raises(InvalidInput, match="not both"):
        store.add_item(
            inv["id"],
            "findings",
            {"title": "y", "source_id": src["id"], "source_url": "https://example.com/"},
        )


def test_clearing_links_on_edit(store, inv):
    t = store.add_item(inv["id"], "targets", {"kind": "domain", "value": "example.com"})
    f = store.add_item(
        inv["id"],
        "findings",
        {"title": "x", "source_url": "https://example.com/", "target_id": t["id"]},
    )
    cleared = store.update_item(inv["id"], "findings", f["id"], {"source_url": "", "target_id": ""})
    assert cleared["source_id"] is None and cleared["target_id"] is None
    # The source itself stays in the investigation's source list.
    assert len(store.get_workspace(inv["id"])["sources"]) == 1


def test_deleting_a_target_or_source_unlinks_but_keeps_findings(store, inv):
    t = store.add_item(inv["id"], "targets", {"kind": "domain", "value": "example.com"})
    f = store.add_item(
        inv["id"],
        "findings",
        {"title": "x", "source_url": "https://example.com/", "target_id": t["id"]},
    )
    e = store.add_item(
        inv["id"], "evidence", {"description": "e", "finding_id": f["id"], "target_id": t["id"]}
    )
    store.delete_item(inv["id"], "targets", t["id"])
    store.delete_item(inv["id"], "sources", f["source_id"])
    finding = store.get_item(inv["id"], "findings", f["id"])
    assert finding["target_id"] is None and finding["source_id"] is None
    store.delete_item(inv["id"], "findings", f["id"])
    evidence = store.get_item(inv["id"], "evidence", e["id"])
    assert evidence["finding_id"] is None and evidence["target_id"] is None


def test_findings_are_ordered_by_recorded_date(store, inv):
    store.add_item(inv["id"], "findings", {"title": "old", "recorded_on": "2025-01-01"})
    store.add_item(inv["id"], "findings", {"title": "new", "recorded_on": "2026-01-01"})
    assert [f["title"] for f in store.get_workspace(inv["id"])["findings"]] == ["new", "old"]


# --- evidence, sources, notes --------------------------------------------------


def test_evidence_entry(store, inv):
    t = store.add_item(inv["id"], "targets", {"kind": "username", "value": "some_handle"})
    f = store.add_item(inv["id"], "findings", {"title": "Profile exists"})
    e = store.add_item(
        inv["id"],
        "evidence",
        {
            "description": "Archived copy of the public profile page",
            "source_url": "https://example.com/u/some_handle",
            "collected_on": "2026-02-01",
            "target_id": t["id"],
            "finding_id": f["id"],
        },
    )
    assert e["collected_on"] == "2026-02-01"
    assert e["source_url"] == "https://example.com/u/some_handle"
    assert e["target_value"] == "some_handle" and e["finding_title"] == "Profile exists"
    with pytest.raises(InvalidInput, match="description is required"):
        store.add_item(inv["id"], "evidence", {"description": " "})
    assert (
        store.add_item(inv["id"], "evidence", {"description": "d"})["collected_on"] == ws._today()
    )


def test_sources_crud_and_duplicate_url(store, inv):
    s = store.add_item(inv["id"], "sources", {"url": "https://example.com/a", "title": "A"})
    with pytest.raises(Conflict):
        store.add_item(inv["id"], "sources", {"url": "https://example.com/a"})
    with pytest.raises(InvalidInput):
        store.add_item(inv["id"], "sources", {"url": "file:///etc/passwd"})
    updated = store.update_item(inv["id"], "sources", s["id"], {"title": "A2", "notes": "n"})
    assert (updated["title"], updated["notes"], updated["url"]) == (
        "A2",
        "n",
        "https://example.com/a",
    )
    store.delete_item(inv["id"], "sources", s["id"])
    assert store.get_workspace(inv["id"])["sources"] == []


def test_notes_crud(store, inv):
    n = store.add_item(inv["id"], "notes", {"body": "first\nline two"})
    assert n["body"] == "first\nline two"
    assert store.update_item(inv["id"], "notes", n["id"], {"body": "edited"})["body"] == "edited"
    with pytest.raises(InvalidInput):
        store.update_item(inv["id"], "notes", n["id"], {"body": ""})
    store.delete_item(inv["id"], "notes", n["id"])
    with pytest.raises(NotFound):
        store.get_item(inv["id"], "notes", n["id"])


def test_item_changes_touch_the_investigation(store, inv):
    store._conn.execute("UPDATE investigations SET updated_at = '2000-01-01T00:00:00+00:00'")
    store._conn.commit()
    store.add_item(inv["id"], "notes", {"body": "x"})
    assert store.get_investigation(inv["id"])["updated_at"] > "2000-01-01T00:00:00+00:00"


def test_update_ignores_nothing_to_change(store, inv):
    n = store.add_item(inv["id"], "notes", {"body": "x"})
    assert store.update_item(inv["id"], "notes", n["id"], {})["body"] == "x"


# --- persistence and storage conventions -----------------------------------------


def test_data_persists_across_store_instances(db):
    with WorkspaceStore(db) as s:
        inv = s.create_investigation("Persisted")
        t = s.add_item(inv["id"], "targets", {"kind": "domain", "value": "example.com"})
        s.add_item(
            inv["id"],
            "findings",
            {"title": "kept", "target_id": t["id"], "source_url": "https://example.com/"},
        )
    with WorkspaceStore(db) as s:  # a new connection, as after an application restart
        restored = s.get_workspace(inv["id"])
    assert restored["title"] == "Persisted"
    assert restored["findings"][0]["target_value"] == "example.com"
    assert restored["sources"][0]["url"] == "https://example.com/"


def test_default_location_is_the_data_directory(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENOSINT_HOME", str(tmp_path / "home"))
    assert ws.default_db_path() == tmp_path / "home" / "workspace.db"
    with WorkspaceStore() as s:
        s.create_investigation("x")
    assert (tmp_path / "home" / "workspace.db").exists()


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permissions")
def test_new_data_dir_and_db_are_owner_only(db):
    with WorkspaceStore(db):
        pass
    assert stat.S_IMODE(os.stat(db.parent).st_mode) == 0o700
    assert stat.S_IMODE(os.stat(db).st_mode) == 0o600


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permissions")
def test_existing_db_keeps_its_mode(tmp_path):
    db = tmp_path / "workspace.db"
    db.touch(mode=0o640)
    os.chmod(db, 0o640)
    with WorkspaceStore(db):
        pass
    assert stat.S_IMODE(os.stat(db).st_mode) == 0o640


def test_newer_schema_is_refused(db):
    with WorkspaceStore(db):
        pass
    conn = sqlite3.connect(db)
    conn.execute(f"PRAGMA user_version={ws.SCHEMA_VERSION + 1}")
    conn.commit()
    conn.close()
    with pytest.raises(ws.WorkspaceError, match="newer OpenOSINT"):
        WorkspaceStore(db)


def test_module_never_imports_network_or_tool_code():
    source = (ws.__file__ and open(ws.__file__, encoding="utf-8").read()) or ""
    for forbidden in (
        "requests",
        "httpx",
        "aiohttp",
        "urllib.request",
        "socket",
        "openosint.tools",
        "subprocess",
    ):
        assert f"import {forbidden}" not in source and f"from {forbidden}" not in source, forbidden
