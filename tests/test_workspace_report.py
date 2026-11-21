"""Investigation reports (openosint/workspace_report.py and GET …/report): content
integrity, traceability, safe rendering, PDF export, settings validation and the API."""

from __future__ import annotations

import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from openosint import workspace_report as report
from openosint.workspace import InvalidInput, WorkspaceStore

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = (ROOT / "openosint" / "web" / "static" / "workspace.js").read_text(encoding="utf-8")
NOW = datetime(2026, 11, 21, 9, 30, tzinfo=timezone.utc)
XSS = '<script>alert("x")</script><img src=x onerror=alert(1)>'


@pytest.fixture
def store(tmp_path):
    with WorkspaceStore(tmp_path / "workspace.db") as s:
        yield s


@pytest.fixture
def full(store):
    """An investigation with one of everything, including hostile text and notes."""
    inv = store.create_investigation(f"Example Org {XSS}", "Scope: public sources.\nLine two.")
    i = inv["id"]
    t = store.add_item(
        i, "targets", {"kind": "domain", "value": "example.com", "notes": "NOTE-TARGET"}
    )
    s = store.add_item(
        i,
        "sources",
        {
            "url": "https://example.com/registry?a=1&b=2",
            "title": "Registry extract",
            "source_type": "government",
            "original_url": "https://example.org/original",
            "published_on": "2025-12-01",
            "accessed_on": "2026-01-10",
            "reliability": "B",
            "reliability_rationale": "Official registry",
        },
    )
    unrated = store.add_item(i, "sources", {"url": "https://example.net/blog"})
    f = store.add_item(
        i,
        "findings",
        {
            "title": f"Registered {XSS}",
            "kind": "reported",
            "confidence": "medium",
            "source_id": s["id"],
            "target_id": t["id"],
            "notes": "NOTE-FINDING",
            "recorded_on": "2026-02-01",
        },
    )
    concl = store.add_item(
        i, "findings", {"title": "Likely the same operator", "kind": "conclusion"}
    )
    ev = store.add_item(
        i,
        "evidence",
        {
            "description": "Registry record",
            "kind": "observation",
            "source_id": s["id"],
            "finding_id": f["id"],
            "collected_on": "2026-02-02",
        },
    )
    a = store.add_item(i, "entities", {"kind": "organization", "label": "Example Org"})
    d = store.add_item(i, "entities", {"kind": "domain", "target_id": t["id"]})
    rel = store.add_item(
        i,
        "relationships",
        {
            "from_entity_id": a["id"],
            "to_entity_id": d["id"],
            "label": "registered",
            "status": "documented",
            "evidence_ids": [ev["id"]],
            "recorded_by": "Analyst A",
        },
    )
    hyp = store.add_item(
        i,
        "relationships",
        {"from_entity_id": d["id"], "to_entity_id": a["id"], "label": "linked to"},
    )
    e1 = store.add_item(
        i,
        "events",
        {
            "title": "Domain registered",
            "start_date": "2026-03-01",
            "start_time": "23:30",
            "timezone": "America/New_York",
            "provenance": "reported",
            "links": [{"kind": "evidence", "id": ev["id"]}, {"kind": "source", "id": s["id"]}],
        },
    )
    e2 = store.add_item(
        i,
        "events",
        {
            "title": "Campaign",
            "date_precision": "range",
            "start_date": "2026-03-03",
            "end_date": "2026-03-10",
        },
    )
    e3 = store.add_item(
        i,
        "events",
        {"title": "Account created", "date_precision": "approximate", "start_date": "2026-02"},
    )
    c = store.add_item(
        i,
        "correlations",
        {
            "title": "Registered before the campaign",
            "event_ids": [e1["id"], e2["id"]],
            "explanation": "Close in time",
        },
    )
    store.add_item(i, "notes", {"body": "NOTE-WORKING check history"})
    ids = dict(
        inv=i,
        target=t,
        source=s,
        unrated=unrated,
        finding=f,
        concl=concl,
        evidence=ev,
        rel=rel,
        hyp=hyp,
        e1=e1,
        e2=e2,
        e3=e3,
        corr=c,
    )
    return store.get_workspace(i), ids


def _html(ws, **opts):
    return report.render_html(report.build_report(ws, report.parse_options(**opts), NOW))


# --- settings -------------------------------------------------------------------------


def test_default_settings_exclude_notes():
    opts = report.parse_options()
    assert opts.sections == report.DEFAULT_SECTIONS and "notes" not in opts.sections
    assert not opts.include_notes


@pytest.mark.parametrize(
    "kwargs, sections",
    [
        ({"sections": "findings, Evidence"}, ("findings", "evidence")),
        (
            {"sections": ["notes", "overview"]},
            ("overview", "notes"),
        ),  # report order, not input order
        ({"sections": "timeline,timeline"}, ("timeline",)),
    ],
)
def test_section_selection(kwargs, sections):
    assert report.parse_options(**kwargs).sections == sections


@pytest.mark.parametrize(
    "kwargs, message",
    [
        ({"sections": "findings,secrets"}, "unknown section"),
        ({"sections": ","}, "at least one section"),
        ({"sections": [1, 2]}, "list of section names"),
        ({"title": "x" * 201}, "longer than"),
        ({"title": "two\nlines"}, "one line"),
        ({"subtitle": "tab\there"}, "one line"),
        ({"title": 5}, "must be text"),
    ],
)
def test_invalid_settings(kwargs, message):
    with pytest.raises(InvalidInput, match=message):
        report.parse_options(**kwargs)


# --- content integrity ------------------------------------------------------------------


def test_every_recorded_item_appears_with_its_reference(full):
    ws, ids = full
    html = _html(
        ws,
        sections="overview,targets,entities,relationships,findings,evidence,sources,timeline,correlations,notes",
    )
    for ref in (
        "T1",
        "N1",
        "N2",
        "R1",
        "R2",
        "F1",
        "F2",
        "E1",
        "S1",
        "S2",
        "V1",
        "V2",
        "V3",
        "C1",
        "M1",
    ):
        assert f'id="{ref}"' in html, ref
    assert "Registry extract" in html and "Domain registered" in html and "Campaign" in html


def test_references_follow_the_order_the_report_shows(full):
    ws, _ = full
    html = _html(ws, sections="findings")
    # Findings are grouped by provenance (observation, reported, assumption, conclusion),
    # so the source-reported one is F1 and the conclusion F2, top to bottom.
    assert html.index('id="F1"') < html.index('id="F2"')
    assert "Registered" in html[html.index('id="F1"') : html.index('id="F2"')]


def test_nothing_is_invented(full):
    ws, ids = full
    html = _html(ws)
    # Unassessed stays unassessed; no rating, rationale or date is made up for it.
    s2 = html[html.index('id="S2"') :]
    s2 = s2[: s2.index("</article>")]
    assert "Not assessed" in s2 and "Rationale" not in s2 and "Assessed on" not in s2
    # A source with no type or dates shows no type or date fields.
    assert "Published" not in s2 and "Accessed" not in s2 and "Type" not in s2
    # The conclusion finding has no source: no source line is shown for it.
    f2 = html[html.index('id="F2"') :]
    f2 = f2[: f2.index("</article>")]
    assert "Source" not in f2 and "Supporting evidence" not in f2


def test_labels_say_who_assigned_confidence_and_reliability(full):
    ws, _ = full
    html = _html(ws)
    assert "Confidence (investigator-assigned)" in html
    assert "Reliability (investigator-assigned)" in html
    assert "B — Usually reliable" in html and "Official registry" in html
    assert "OpenOSINT does not assign, verify or change them." in html
    assert "Nothing in this report was generated, inferred or verified automatically." in html


def test_provenance_is_distinguished(full):
    ws, _ = full
    html = _html(ws)
    assert "Source-reported claims" in html and "Analyst conclusions" in html  # finding groups
    assert 'class="badge reported">Source-reported claim<' in html
    assert 'class="badge conclusion">Analyst conclusion<' in html
    assert 'class="badge observation">Direct observation<' in html  # evidence
    # Relationships and correlations: documented vs hypothesis, never upgraded.
    assert (
        "<dt>Status</dt><dd>Documented</dd>" in html
        and "<dt>Status</dt><dd>Hypothesis</dd>" in html
    )
    assert "<dt>Status</dt><dd>Analyst hypothesis</dd>" in html
    assert "Time order is not causation." in html


def test_timeline_is_chronological_with_date_kinds(full):
    ws, _ = full
    html = _html(ws, sections="timeline")
    order = [html.index(t) for t in ("Account created", "Domain registered", "Campaign")]
    assert order == sorted(order)
    assert "≈ 2026-02" in html and "2026-03-03 → 2026-03-10" in html
    assert "2026-03-01 23:30 (America/New_York)" in html


def test_cross_references_link_only_to_included_sections(full):
    ws, ids = full
    html = _html(ws, sections="findings,evidence")
    assert 'href="#E1"' in html and 'href="#F1"' in html
    assert 'href="#S1"' not in html and 'href="#T1"' not in html  # not in this report
    # The source is still traceable: its original URL is shown instead of a dead link.
    assert "https://example.com/registry?a=1&amp;b=2" in html
    assert "example.com" in html  # the target, as text


def test_flags_survive_into_the_report(store, full):
    ws, ids = full
    store.delete_item(ids["inv"], "evidence", ids["evidence"]["id"])
    store.delete_item(ids["inv"], "events", ids["e2"]["id"])
    html = _html(store.get_workspace(ids["inv"]))
    assert "Marked documented, but the finding and evidence it cited were deleted." in html
    assert "Fewer than two of its events remain." in html


def test_analyst_notes_only_when_selected(full):
    ws, _ = full
    without = _html(ws)
    for note in ("NOTE-TARGET", "NOTE-FINDING", "NOTE-WORKING"):
        assert note not in without
    assert "Analyst notes are not included." in without
    with_notes = _html(ws, sections=list(report.DEFAULT_SECTIONS) + ["notes"])
    for note in ("NOTE-TARGET", "NOTE-FINDING", "NOTE-WORKING"):
        assert note in with_notes
    assert "Analyst notes are included." in with_notes


def test_empty_investigation(store):
    inv = store.create_investigation("Empty")
    html = _html(store.get_workspace(inv["id"]))
    assert html.count("None recorded.") == len(report.DEFAULT_SECTIONS) - 1  # all but overview
    assert "<h1>Empty</h1>" in html


def test_title_and_subtitle(full):
    ws, _ = full
    html = _html(ws, title="Custom title", subtitle="Internal draft")
    assert "<h1>Custom title</h1>" in html and '<p class="subtitle">Internal draft</p>' in html
    assert "<title>Custom title</title>" in html


# --- safe rendering -------------------------------------------------------------------


def test_html_escapes_everything_and_has_no_script(full):
    ws, _ = full
    html = _html(ws, sections=list(report.REPORT_SECTIONS))
    assert "<script" not in html.lower()
    assert "<img" not in html.lower()
    assert "onerror=alert" not in html.replace("onerror=alert(1)&gt;", "")
    assert "&lt;script&gt;" in html and "&lt;img src=x" in html
    assert re.search(r"\son[a-z]+\s*=", html.replace("onerror=alert(1)&gt;", "")) is None
    assert f'content="{report.META_CSP}"' in html.replace("&#x27;", "'")
    assert "frame-ancestors" not in report.META_CSP and "frame-ancestors 'self'" in report.CSP


def test_only_http_urls_become_links():
    model = {
        "title": "t",
        "subtitle": "",
        "investigation_title": "t",
        "generated_at": "now",
        "legend": [],
        "notes_included": False,
        "sections": [
            report.Section(
                "sources",
                "Sources",
                groups=[
                    (
                        "",
                        [
                            report.Item(
                                "S1",
                                ["x"],
                                fields=[
                                    ("URL", [{"url": "javascript:alert(1)"}]),
                                    ("U2", [{"url": 'https://e.com/"><b>'}]),
                                ],
                            )
                        ],
                    )
                ],
            )
        ],
    }
    html = report.render_html(model)
    assert 'href="javascript' not in html and "javascript:alert(1)" in html  # shown, not linked
    assert '"><b>' not in html


def test_safe_url():
    assert report.safe_url("https://example.com/a?b=c") == "https://example.com/a?b=c"
    for bad in ("javascript:alert(1)", "data:text/html,x", "//e.com", 'https://e.com/"x', None, 5):
        assert report.safe_url(bad) == ""


# --- PDF ---------------------------------------------------------------------------


def test_pdf_is_generated(full, tmp_path):
    ws, _ = full
    model = report.build_report(
        ws, report.parse_options(sections=list(report.REPORT_SECTIONS)), NOW
    )
    pdf = report.render_pdf(model)
    assert pdf.startswith(b"%PDF-") and pdf.rstrip().endswith(b"%%EOF") and len(pdf) > 3000
    if shutil.which("pdftotext"):
        path = tmp_path / "r.pdf"
        path.write_bytes(pdf)
        text = subprocess.run(
            ["pdftotext", str(path), "-"], capture_output=True, text=True, check=True
        ).stdout
        assert "Registry extract" in text and "B - Usually reliable" in text
        assert '<script>alert("x")</script>' in text  # shown as text, not interpreted
        assert "approx. 2026-02" in text and "2026-03-03 -> 2026-03-10" in text
        assert "NOTE-WORKING" in text


def test_pdf_escapes_reportlab_markup():
    assert report._p('<b>x</b> & "q"') == "&lt;b&gt;x&lt;/b&gt; &amp; &quot;q&quot;"
    assert report._plain("≈ a → b — c") == "approx. a -> b - c"


def test_empty_investigation_pdf(store):
    inv = store.create_investigation("Empty")
    model = report.build_report(store.get_workspace(inv["id"]), report.parse_options(), NOW)
    assert report.render_pdf(model).startswith(b"%PDF-")


def test_report_filename():
    assert (
        report.report_filename('Example Org <x> / "y"', "pdf", NOW)
        == "report-example-org-x-y-2026-11-21.pdf"
    )
    assert report.report_filename("***", "html", NOW) == "report-investigation-2026-11-21.html"


def test_report_module_makes_no_network_calls():
    source = Path(report.__file__).read_text(encoding="utf-8")
    for forbidden in (
        "requests",
        "httpx",
        "aiohttp",
        "urllib.request",
        "socket",
        "subprocess",
        "openosint.tools",
    ):
        assert f"import {forbidden}" not in source and f"from {forbidden}" not in source, forbidden


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


async def _seed(client) -> str:
    inv = (await client.post("/api/investigations", json={"title": "API report"})).json()
    base = f"/api/investigations/{inv['id']}"
    await client.post(f"{base}/findings", json={"title": f"Finding {XSS}", "notes": "NOTE-API"})
    return inv["id"]


async def test_api_html_report(client):
    iid = await _seed(client)
    r = await client.get(f"/api/investigations/{iid}/report")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/html")
    assert r.headers["content-security-policy"] == report.CSP
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["cache-control"] == "no-store"
    assert r.headers["content-disposition"].startswith("inline;")
    assert "<script" not in r.text.lower() and "NOTE-API" not in r.text
    r = await client.get(
        f"/api/investigations/{iid}/report",
        params={"download": "true", "sections": "findings,notes"},
    )
    assert (
        r.headers["content-disposition"]
        == 'attachment; filename="report-api-report-'
        + datetime.now(timezone.utc).strftime("%Y-%m-%d")
        + '.html"'
    )
    assert "NOTE-API" in r.text


async def test_api_pdf_report(client):
    iid = await _seed(client)
    r = await client.get(
        f"/api/investigations/{iid}/report", params={"format": "pdf", "title": "Custom"}
    )
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf"
    assert r.content.startswith(b"%PDF-")
    assert r.headers["content-disposition"].startswith('attachment; filename="report-custom-')


@pytest.mark.parametrize(
    "params",
    [
        {"format": "docx"},
        {"sections": "findings,secrets"},
        {"sections": ","},
        {"title": "a\nb"},
        {"title": "x" * 201},
    ],
)
async def test_api_rejects_invalid_settings(client, params):
    iid = await _seed(client)
    assert (await client.get(f"/api/investigations/{iid}/report", params=params)).status_code == 422


async def test_api_unknown_investigation(client):
    assert (await client.get(f"/api/investigations/{'0' * 32}/report")).status_code == 404


async def test_api_report_is_restricted(client, monkeypatch):
    import openosint.web_server as w

    iid = await _seed(client)
    monkeypatch.setattr(w, "DEMO_MODE", True)
    for fmt in ("html", "pdf"):
        assert (
            await client.get(f"/api/investigations/{iid}/report", params={"format": fmt})
        ).status_code == 403


async def test_api_cross_site_report_request_is_rejected(client):
    iid = await _seed(client)
    r = await client.get(
        f"/api/investigations/{iid}/report",
        headers={"Origin": "https://evil.example", "Sec-Fetch-Site": "cross-site"},
    )
    assert r.status_code == 403


# --- page wiring (static) ------------------------------------------------------------------


def test_report_tab_wiring():
    assert "{ id: 'report', label: 'Report', noCount: true }" in SCRIPT
    assert "sandbox: ''" in SCRIPT  # the preview frame runs nothing
    assert (
        "export const DEFAULT_REPORT_SECTIONS = REPORT_SECTIONS.map(([k]) => k).filter((k) => k !== 'notes');"
        in SCRIPT
    )
    assert "return `/api/investigations/${encodeURIComponent(invId)}/report?${params}`;" in SCRIPT


def test_pdf_handles_fields_longer_than_a_page(store, tmp_path):
    # Regression: a field value taller than a page (here a 6,000-character rationale, well
    # under the 20,000 the store accepts) made reportlab raise LayoutError: the export 500'd.
    inv = store.create_investigation("Long fields")
    i = inv["id"]
    long_text = "x" * 6000  # no spaces, so it cannot wrap on words either
    store.add_item(
        i,
        "sources",
        {
            "url": "https://example.com/" + "a" * 2000,
            "reliability": "C",
            "reliability_rationale": long_text,
        },
    )
    store.add_item(i, "findings", {"title": "Ёжик 東京 مرحبا 🙂", "description": long_text})
    model = report.build_report(store.get_workspace(i), report.parse_options(), NOW)
    pdf = report.render_pdf(model)
    assert pdf.startswith(b"%PDF-")
    if shutil.which("pdftotext"):
        path = tmp_path / "long.pdf"
        path.write_bytes(pdf)
        text = subprocess.run(
            ["pdftotext", str(path), "-"], capture_output=True, text=True, check=True
        ).stdout
        assert "Rationale:" in text and text.count("x") >= 12000  # both long values are all there
