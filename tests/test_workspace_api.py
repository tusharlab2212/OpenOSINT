"""Research workspace web API (/api/investigations) and page (/workspace)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

ROOT = Path(__file__).resolve().parent.parent
PAGE = (ROOT / "openosint" / "web" / "workspace.html").read_text(encoding="utf-8")
SCRIPT = (ROOT / "openosint" / "web" / "static" / "workspace.js").read_text(encoding="utf-8")
INDEX = (ROOT / "openosint" / "web" / "index.html").read_text(encoding="utf-8")


@pytest_asyncio.fixture
async def client(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENOSINT_HOME", str(tmp_path / "home"))
    import openosint.web_server as w

    w._RATE_STORE.clear()
    app = w.create_app(host="127.0.0.1")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://127.0.0.1") as c:
        yield c
    w._RATE_STORE.clear()


async def _new(client, title="Example Org exposure", description="") -> dict:
    r = await client.post("/api/investigations", json={"title": title, "description": description})
    assert r.status_code == 201, r.text
    return r.json()


async def test_investigation_lifecycle(client):
    assert (await client.get("/api/investigations")).json() == {"investigations": []}
    inv = await _new(client, description="scope: public sources only")

    listed = (await client.get("/api/investigations")).json()["investigations"]
    assert [i["id"] for i in listed] == [inv["id"]]
    assert listed[0]["counts"]["findings"] == 0

    full = (await client.get(f"/api/investigations/{inv['id']}")).json()
    assert full["description"] == "scope: public sources only"
    assert {k: full[k] for k in ("targets", "sources", "findings", "notes", "evidence")} == {
        "targets": [],
        "sources": [],
        "findings": [],
        "notes": [],
        "evidence": [],
    }

    r = await client.patch(f"/api/investigations/{inv['id']}", json={"title": "Renamed"})
    assert r.status_code == 200 and r.json()["title"] == "Renamed"
    assert r.json()["description"] == "scope: public sources only"

    r = await client.delete(f"/api/investigations/{inv['id']}")
    assert r.json() == {"status": "deleted", "id": inv["id"]}
    assert (await client.get(f"/api/investigations/{inv['id']}")).status_code == 404
    assert (await client.delete(f"/api/investigations/{inv['id']}")).status_code == 404


async def test_sections_and_links(client):
    inv = await _new(client)
    base = f"/api/investigations/{inv['id']}"
    target = (
        await client.post(f"{base}/targets", json={"kind": "domain", "value": "Example.com"})
    ).json()
    assert target["value"] == "example.com"

    r = await client.post(
        f"{base}/findings",
        json={
            "title": "Mail is handled by a third party",
            "confidence": "medium",
            "kind": "observation",
            "source_url": "https://example.com/mx",
            "target_id": target["id"],
        },
    )
    assert r.status_code == 201
    finding = r.json()
    assert (
        finding["source_url"] == "https://example.com/mx"
        and finding["target_value"] == "example.com"
    )

    r = await client.post(
        f"{base}/evidence",
        json={
            "description": "Saved DNS answer",
            "source_url": "https://example.com/mx",
            "finding_id": finding["id"],
            "collected_on": "2026-03-01",
        },
    )
    assert r.status_code == 201 and r.json()["finding_title"] == finding["title"]
    note = (await client.post(f"{base}/notes", json={"body": "verify with a second source"})).json()

    full = (await client.get(base)).json()
    assert len(full["sources"]) == 1 and full["sources"][0]["evidence_count"] == 1
    assert [n["id"] for n in full["notes"]] == [note["id"]]

    r = await client.patch(
        f"{base}/findings/{finding['id']}",
        json={"confidence": "high", "notes": "confirmed manually"},
    )
    assert r.json()["confidence"] == "high" and r.json()["notes"] == "confirmed manually"

    assert (await client.delete(f"{base}/notes/{note['id']}")).json()["status"] == "deleted"
    assert (await client.delete(f"{base}/notes/{note['id']}")).status_code == 404


async def test_finding_confidence_is_never_raised_by_default(client):
    inv = await _new(client)
    r = await client.post(
        f"/api/investigations/{inv['id']}/findings", json={"title": "Tool said so"}
    )
    assert r.json()["confidence"] == "low"


@pytest.mark.parametrize(
    "path, body",
    [
        ("findings", {"title": "x", "confidence": "certain"}),
        ("findings", {"title": "x", "kind": "fact"}),
        ("findings", {"title": "x", "source_url": "javascript:alert(1)"}),
        ("findings", {"title": "x", "unexpected": 1}),
        ("findings", {"title": ""}),
        ("targets", {"kind": "password", "value": "x"}),
        ("targets", {"kind": "domain", "value": "not a domain"}),
        ("sources", {"url": "data:text/html,hi"}),
        ("evidence", {"description": "x", "collected_on": "yesterday"}),
        ("notes", {"body": "x" * 20001}),
    ],
)
async def test_invalid_input_is_rejected(client, path, body):
    inv = await _new(client)
    r = await client.post(f"/api/investigations/{inv['id']}/{path}", json=body)
    assert r.status_code == 422, r.text
    assert (await client.get(f"/api/investigations/{inv['id']}")).json()[path] == []


async def test_investigation_validation_and_conflicts(client):
    assert (await client.post("/api/investigations", json={"title": ""})).status_code == 422
    assert (
        await client.post("/api/investigations", json={"description": "no title"})
    ).status_code == 422
    assert (await client.post("/api/investigations", json={"title": "x" * 201})).status_code == 422
    inv = await _new(client)
    base = f"/api/investigations/{inv['id']}"
    assert (await client.patch(base, json={"title": " "})).status_code == 422
    await client.post(f"{base}/targets", json={"kind": "email", "value": "a@example.com"})
    r = await client.post(f"{base}/targets", json={"kind": "email", "value": "A@example.com"})
    assert r.status_code == 409


async def test_unknown_ids_and_cross_investigation_items_are_404(client):
    a, b = await _new(client, "A"), await _new(client, "B")
    note = (await client.post(f"/api/investigations/{a['id']}/notes", json={"body": "x"})).json()
    assert (
        await client.patch(f"/api/investigations/{b['id']}/notes/{note['id']}", json={"body": "y"})
    ).status_code == 404
    assert (
        await client.delete(f"/api/investigations/{b['id']}/notes/{note['id']}")
    ).status_code == 404
    assert (await client.get("/api/investigations/not-an-id")).status_code == 404
    assert (await client.get("/api/investigations/" + "0" * 32)).status_code == 404


async def test_data_survives_an_app_restart(client, tmp_path):
    inv = await _new(client, "Persisted")
    await client.post(
        f"/api/investigations/{inv['id']}/targets",
        json={"kind": "username", "value": "some_handle"},
    )
    import openosint.web_server as w

    app2 = w.create_app(host="127.0.0.1")  # a fresh app reading the same data directory
    async with AsyncClient(transport=ASGITransport(app=app2), base_url="http://127.0.0.1") as c2:
        full = (await c2.get(f"/api/investigations/{inv['id']}")).json()
    assert full["title"] == "Persisted" and full["targets"][0]["value"] == "some_handle"
    assert (tmp_path / "home" / "workspace.db").exists()


async def test_restricted_requests_are_refused(client, monkeypatch):
    import openosint.web_server as w

    inv = await _new(client)
    monkeypatch.setattr(w, "DEMO_MODE", True)
    monkeypatch.setattr(w, "DEMO_REASON", "public bind", raising=False)
    for method, path, body in (
        ("GET", "/api/investigations", None),
        ("POST", "/api/investigations", {"title": "x"}),
        ("GET", f"/api/investigations/{inv['id']}", None),
        ("POST", f"/api/investigations/{inv['id']}/notes", {"body": "x"}),
        ("DELETE", f"/api/investigations/{inv['id']}", None),
    ):
        r = await client.request(method, path, json=body)
        assert r.status_code == 403, (method, path)
        assert "local, unrestricted instance" in r.json()["detail"]


async def test_proxied_request_without_trusted_proxy_is_refused(client):
    r = await client.get("/api/investigations", headers={"X-Forwarded-For": "198.51.100.7"})
    assert r.status_code == 403


async def test_cross_site_browser_request_is_rejected_by_the_origin_guard(client):
    r = await client.post(
        "/api/investigations",
        json={"title": "x"},
        headers={"Origin": "https://evil.example", "Sec-Fetch-Site": "cross-site"},
    )
    assert r.status_code == 403
    assert (await client.get("/api/investigations")).json()["investigations"] == []


async def test_workspace_page_is_served(client):
    r = await client.get("/workspace")
    assert r.status_code == 200 and "Research workspace" in r.text
    assert "/static/workspace.js" in r.text
    assert (await client.get("/static/workspace.js")).status_code == 200


async def test_workspace_routes_make_no_outbound_calls(client, monkeypatch):
    import socket

    def refuse(*args, **kwargs):
        raise AssertionError("workspace route opened a network connection")

    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket.socket, "connect", refuse)
    inv = await _new(client)
    base = f"/api/investigations/{inv['id']}"
    await client.post(f"{base}/targets", json={"kind": "url", "value": "https://example.com/"})
    await client.post(f"{base}/findings", json={"title": "x", "source_url": "https://example.com/"})
    await client.post(f"{base}/sources", json={"url": "https://example.org/"})
    assert (await client.get(base)).status_code == 200


# --- page and script wiring (static checks) -------------------------------------


def test_script_never_injects_html():
    for sink in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval("):
        assert sink not in SCRIPT, sink
    assert "x-html" not in PAGE


def test_links_only_through_the_safe_url_check():
    assert "import { safeHttpUrl } from '/static/url-safety.js'" in SCRIPT
    hrefs = re.findall(r"href: ([^,}]+)", SCRIPT)
    assert hrefs == ["safe"], hrefs
    assert "rel: 'noopener noreferrer'" in SCRIPT


def test_script_only_calls_local_investigation_routes():
    urls = set(re.findall(r"api\('(?:GET|POST|PUT|PATCH|DELETE)', `?'?([^`',]+)", SCRIPT))
    allowed = ("/api/investigations", "base", "${base}/", "${graphBase()}/", "${timelineBase()}/")
    assert urls and all(u.startswith(allowed) for u in urls), urls
    assert "const base = `/api/investigations/${state.current.id}/${section}`;" in SCRIPT
    # The graph's route helper (and its `base`) only ever point at this investigation's routes.
    assert "return `/api/investigations/${state.current.id}`;" in SCRIPT
    assert "const base = `${graphBase()}/${section}`;" in SCRIPT
    assert (
        "function timelineBase() {\n    return `/api/investigations/${state.current.id}`;" in SCRIPT
    )
    assert "const base = `${timelineBase()}/${section}`;" in SCRIPT
    assert "fetch(path" in SCRIPT and SCRIPT.count("fetch(") == 1


def test_delete_needs_the_typed_title():
    assert 'id="ws-delete-confirm" class="danger" disabled' in PAGE
    assert "deleteConfirmed(inv.title, input.value)" in SCRIPT
    assert "cannot be undone" in PAGE.lower()


def test_main_ui_links_to_the_workspace():
    assert 'href="/workspace" data-testid="workspace-link"' in INDEX


def test_page_is_mobile_ready():
    assert '<meta name="viewport" content="width=device-width, initial-scale=1">' in PAGE
    assert "@media (max-width:760px)" in PAGE


def test_element_builder_flattens_nested_children():
    # Regression: metadata rows are built as nested arrays; a one-level flat() rendered
    # them as "[object HTMLElement]" text instead of elements.
    assert "children.flat(Infinity)" in SCRIPT
