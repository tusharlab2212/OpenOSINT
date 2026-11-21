"""Investigation reports from the research workspace: HTML (viewable, printable) and PDF.

A report is an assembly of what the investigator recorded. Nothing here interprets,
summarises, infers, dates or verifies anything: every value shown is a stored value, a
missing value is left out (or shown as "Not assessed" / "None recorded" where its absence
matters), and every label says who assigned it. Items get stable references (F1, E2, S3,
...) so findings, evidence, sources, relationships and events can be traced to each other.

The HTML is built here with every value escaped, carries no script, and is served with a
Content-Security-Policy that blocks scripts and remote loads. The PDF uses reportlab (a
core dependency) with the same model, escaping text for reportlab's paragraph markup.
"""

from __future__ import annotations

import html
import io
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from xml.sax.saxutils import escape as xml_escape

from openosint.workspace import (
    RELIABILITY_LABELS,
    TITLE_MAX,
    InvalidInput,
)

# Report sections in their fixed order. Analyst notes (the Notes section and the notes
# on every item) appear only when "notes" is selected.
SECTION_TITLES = {
    "overview": "Investigation overview",
    "targets": "Targets",
    "entities": "Entities",
    "relationships": "Relationships",
    "findings": "Findings",
    "evidence": "Evidence",
    "sources": "Sources",
    "timeline": "Timeline",
    "correlations": "Correlations",
    "notes": "Analyst notes",
}
REPORT_SECTIONS = tuple(SECTION_TITLES)
DEFAULT_SECTIONS = tuple(s for s in REPORT_SECTIONS if s != "notes")
FORMATS = ("html", "pdf")

PROVENANCE_LABELS = {
    "observation": "Direct observation",
    "reported": "Source-reported claim",
    "assumption": "Assumption",
    "conclusion": "Analyst conclusion",
    "hypothesis": "Hypothesis",
    "unspecified": "Provenance not specified",
}
EVENT_PROVENANCE_LABELS = {
    "reported": "Source-reported",
    "observation": "Analyst observation",
    "hypothesis": "Hypothesis",
    "conclusion": "Analyst conclusion",
}
# Findings are shown, and numbered, grouped by provenance in this order.
FINDING_ORDER = ("observation", "reported", "assumption", "conclusion")
DATE_PRECISION_LABELS = {
    "exact": "Exact date",
    "approximate": "Approximate date",
    "range": "Date range",
}
# Reference prefixes, one per kind of item.
PREFIX = {
    "targets": "T",
    "entities": "N",
    "relationships": "R",
    "findings": "F",
    "evidence": "E",
    "sources": "S",
    "events": "V",
    "correlations": "C",
    "notes": "M",
}
# Which report section shows each kind of item (for cross-reference links).
SECTION_OF = {
    "targets": "targets",
    "entities": "entities",
    "relationships": "relationships",
    "findings": "findings",
    "evidence": "evidence",
    "sources": "sources",
    "events": "timeline",
    "correlations": "correlations",
    "notes": "notes",
}

_SAFE_URL_RE = re.compile(r"^https?://[^\s\"'<>`]+$", re.I)

LEGEND = [
    (
        "Provenance",
        "Each finding, evidence entry and event says where it comes from: a direct observation "
        "(seen by the investigator in a source), a source-reported claim (what a source says, "
        "not verified), an assumption or hypothesis (not established), or an analyst conclusion "
        "(inferred by the investigator).",
    ),
    (
        "Confidence and reliability",
        "Confidence levels and A–F source reliability ratings were assigned by the investigator. "
        "OpenOSINT does not assign, verify or change them.",
    ),
    (
        "Relationships and correlations",
        "Recorded by the investigator. Each is a hypothesis unless marked documented, which "
        "requires a cited finding or evidence entry.",
    ),
    (
        "References",
        "T targets, N entities, R relationships, F findings, E evidence, S sources, V timeline "
        "events, C correlations, M notes.",
    ),
]


# ---------------------------------------------------------------------------
# Options
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ReportOptions:
    sections: tuple[str, ...] = DEFAULT_SECTIONS
    title: str = ""
    subtitle: str = ""

    @property
    def include_notes(self) -> bool:
        return "notes" in self.sections


def _one_line(value: Any, name: str) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise InvalidInput(f"{name} must be text")
    value = value.strip()
    if len(value) > TITLE_MAX:
        raise InvalidInput(f"{name} is longer than {TITLE_MAX} characters")
    if any(ord(c) < 32 for c in value):
        raise InvalidInput(f"{name} must be one line of text")
    return value


def parse_options(sections: Any = None, title: Any = None, subtitle: Any = None) -> ReportOptions:
    """Validate report settings. ``sections`` is a list or a comma-separated string."""
    if sections in (None, ""):
        chosen = DEFAULT_SECTIONS
    else:
        items = sections.split(",") if isinstance(sections, str) else sections
        if not isinstance(items, (list, tuple)) or not all(isinstance(s, str) for s in items):
            raise InvalidInput("sections must be a list of section names")
        wanted = {s.strip().lower() for s in items if s.strip()}
        unknown = wanted - set(REPORT_SECTIONS)
        if unknown:
            raise InvalidInput(
                f"unknown section(s): {', '.join(sorted(unknown))}; "
                f"choose from {', '.join(REPORT_SECTIONS)}"
            )
        if not wanted:
            raise InvalidInput("choose at least one section")
        chosen = tuple(s for s in REPORT_SECTIONS if s in wanted)
    return ReportOptions(chosen, _one_line(title, "title"), _one_line(subtitle, "subtitle"))


# ---------------------------------------------------------------------------
# Model: what goes in the report, built only from stored values
# ---------------------------------------------------------------------------


@dataclass
class Item:
    ref: str
    heading: list
    badges: list[tuple[str, str]] = field(default_factory=list)
    fields: list[tuple[str, list]] = field(default_factory=list)
    body: str = ""
    notes: str = ""
    warnings: list[str] = field(default_factory=list)


@dataclass
class Section:
    key: str
    title: str
    intro: str = ""
    groups: list[tuple[str, list[Item]]] = field(default_factory=list)
    empty: str = "None recorded."


def safe_url(url: Any) -> str:
    """The URL if it is plain http(s), else ''. Stored URLs are validated; this is a second check."""
    return url if isinstance(url, str) and _SAFE_URL_RE.match(url) else ""


def format_event_date(ev: dict) -> str:
    def at(day: str, time: str) -> str:
        return f"{day} {time}" if time else day

    zone = (
        f" ({ev['timezone']})"
        if ev.get("timezone") and (ev.get("start_time") or ev.get("end_time"))
        else ""
    )
    start = at(ev.get("start_date", ""), ev.get("start_time", ""))
    if ev.get("date_precision") == "approximate":
        return f"≈ {start}{zone}"
    if ev.get("date_precision") == "range":
        return f"{start} → {at(ev.get('end_date', ''), ev.get('end_time', ''))}{zone}"
    return f"{start}{zone}"


class _Refs:
    """Stable reference labels, and cross-references that link only to included sections."""

    def __init__(self, ws: dict, sections: tuple[str, ...]):
        self.labels: dict[tuple[str, str], str] = {}
        self.included = set(sections)
        for kind, prefix in PREFIX.items():
            items = ws.get(kind, [])
            if kind == "findings":  # numbered in the order the report shows them
                items = [
                    f for k in FINDING_ORDER for f in items if f.get("kind", "observation") == k
                ]
            for n, item in enumerate(items, start=1):
                self.labels[(kind, item["id"])] = f"{prefix}{n}"

    def label(self, kind: str, item_id: str) -> str:
        return self.labels.get((kind, item_id), "")

    def seg(self, kind: str, item_id: str | None, text: str) -> dict | str:
        """A reference segment, or just the text when that item is not in the report."""
        label = self.label(kind, item_id) if item_id else ""
        if label and SECTION_OF[kind] in self.included:
            return {"ref": label, "text": text}
        return text


def _date_only(ts: str) -> str:
    return (ts or "")[:10]


def build_report(ws: dict, options: ReportOptions, generated_at: datetime | None = None) -> dict:
    """The report model for a workspace (as returned by WorkspaceStore.get_workspace)."""
    generated_at = generated_at or datetime.now(timezone.utc)
    refs = _Refs(ws, options.sections)
    notes_on = options.include_notes
    by_id = {kind: {i["id"]: i for i in ws.get(kind, [])} for kind in PREFIX}
    sections: list[Section] = []

    def note(item: dict) -> str:
        return item.get("notes", "") if notes_on else ""

    for key in options.sections:
        s = Section(key, SECTION_TITLES[key])
        if key == "overview":
            counts = [
                (SECTION_TITLES[k] if k != "timeline" else "Timeline events", len(ws.get(kind, [])))
                for k, kind in (
                    ("targets", "targets"),
                    ("entities", "entities"),
                    ("relationships", "relationships"),
                    ("findings", "findings"),
                    ("evidence", "evidence"),
                    ("sources", "sources"),
                    ("timeline", "events"),
                    ("correlations", "correlations"),
                )
            ]
            item = Item(
                ref="",
                heading=[ws["title"]],
                fields=[
                    ("Created", [_date_only(ws.get("created_at", ""))]),
                    ("Last updated", [_date_only(ws.get("updated_at", ""))]),
                    ("Recorded items", [", ".join(f"{label}: {n}" for label, n in counts)]),
                    (
                        "Sections in this report",
                        [", ".join(SECTION_TITLES[k] for k in options.sections)],
                    ),
                ],
                body=ws.get("description", ""),
            )
            s.groups = [("", [item])]
            s.empty = ""

        elif key == "targets":
            s.groups = [
                (
                    "",
                    [
                        Item(
                            ref=refs.label("targets", t["id"]),
                            heading=[t["value"]],
                            badges=[(t["kind"], "kind")],
                            notes=note(t),
                        )
                        for t in ws.get("targets", [])
                    ],
                )
            ]

        elif key == "entities":
            items = []
            for e in ws.get("entities", []):
                fields = []
                if e.get("target_id"):
                    fields.append(
                        (
                            "Linked target",
                            [
                                refs.seg(
                                    "targets",
                                    e["target_id"],
                                    f"{e.get('target_kind')}: {e.get('target_value')}",
                                )
                            ],
                        )
                    )
                fields.append(("Relationships", [str(e.get("relationship_count", 0))]))
                items.append(
                    Item(
                        ref=refs.label("entities", e["id"]),
                        heading=[e["label"]],
                        badges=[(e["kind"], "kind")],
                        fields=fields,
                        body=e.get("description", ""),
                        notes=note(e),
                    )
                )
            s.groups = [("", items)]

        elif key == "relationships":
            s.intro = (
                "Recorded by the investigator. Not inferred, and not established unless documented."
            )
            items = []
            for r in ws.get("relationships", []):
                status = "Documented" if r["status"] == "documented" else "Hypothesis"
                warnings = []
                if r.get("unsupported"):
                    warnings.append(
                        "Marked documented, but the finding and evidence it cited were deleted."
                    )
                fields = [
                    ("Status", [status]),
                    ("Confidence (investigator-assigned)", [r["confidence"]]),
                ]
                if r.get("finding_id"):
                    fields.append(
                        (
                            "Cites finding",
                            [refs.seg("findings", r["finding_id"], r.get("finding_title") or "")],
                        )
                    )
                cited = [by_id["evidence"].get(i) for i in r.get("evidence_ids", [])]
                if any(cited):
                    fields.append(
                        (
                            "Cites evidence",
                            _join(
                                [
                                    refs.seg("evidence", c["id"], c["description"][:80])
                                    for c in cited
                                    if c
                                ]
                            ),
                        )
                    )
                if r.get("recorded_by"):
                    fields.append(("Recorded by", [r["recorded_by"]]))
                items.append(
                    Item(
                        ref=refs.label("relationships", r["id"]),
                        heading=[
                            refs.seg("entities", r["from_entity_id"], r["from_label"]),
                            f" — {r['label']} → ",
                            refs.seg("entities", r["to_entity_id"], r["to_label"]),
                        ],
                        badges=[(status.lower(), "status")],
                        fields=fields,
                        body=r.get("description", ""),
                        notes=note(r),
                        warnings=warnings,
                    )
                )
            s.groups = [("", items)]

        elif key == "findings":
            s.intro = "Recorded by the investigator, grouped by provenance. Confidence is investigator-assigned."
            groups = []
            for kind in FINDING_ORDER:
                items = []
                for f in (
                    x for x in ws.get("findings", []) if x.get("kind", "observation") == kind
                ):
                    fields = [
                        ("Confidence (investigator-assigned)", [f["confidence"]]),
                        ("Recorded", [f.get("recorded_on", "")]),
                    ]
                    if f.get("source_id"):
                        fields.append(
                            (
                                "Source",
                                _source_segs(
                                    refs,
                                    f["source_id"],
                                    f.get("source_url"),
                                    f.get("source_reliability"),
                                ),
                            )
                        )
                    if f.get("target_id"):
                        fields.append(
                            (
                                "Target",
                                [
                                    refs.seg(
                                        "targets",
                                        f["target_id"],
                                        f"{f.get('target_kind')}: {f.get('target_value')}",
                                    )
                                ],
                            )
                        )
                    support = [by_id["evidence"].get(i) for i in f.get("evidence_ids", [])]
                    if any(support):
                        fields.append(
                            (
                                "Supporting evidence",
                                _join(
                                    [
                                        refs.seg("evidence", e["id"], e["description"][:80])
                                        for e in support
                                        if e
                                    ]
                                ),
                            )
                        )
                    items.append(
                        Item(
                            ref=refs.label("findings", f["id"]),
                            heading=[f["title"]],
                            badges=[
                                (PROVENANCE_LABELS[kind], kind),
                                (f"{f['confidence']} confidence", "conf"),
                            ],
                            fields=fields,
                            body=f.get("description", ""),
                            notes=note(f),
                        )
                    )
                if items:
                    groups.append((PROVENANCE_LABELS[kind] + "s", items))
            s.groups = groups

        elif key == "evidence":
            s.intro = "Descriptions of what was collected, with their provenance and sources."
            items = []
            for e in ws.get("evidence", []):
                kind = e.get("kind") or "unspecified"
                fields = [("Collected", [e.get("collected_on", "")])]
                if e.get("source_id"):
                    fields.append(
                        (
                            "Source",
                            _source_segs(
                                refs,
                                e["source_id"],
                                e.get("source_url"),
                                e.get("source_reliability"),
                            ),
                        )
                    )
                if e.get("target_id"):
                    fields.append(
                        (
                            "Target",
                            [
                                refs.seg(
                                    "targets",
                                    e["target_id"],
                                    f"{e.get('target_kind')}: {e.get('target_value')}",
                                )
                            ],
                        )
                    )
                if e.get("finding_id"):
                    fields.append(
                        (
                            "Supports finding",
                            [refs.seg("findings", e["finding_id"], e.get("finding_title") or "")],
                        )
                    )
                rels = [by_id["relationships"].get(i) for i in e.get("relationship_ids", [])]
                if any(rels):
                    fields.append(
                        (
                            "Cited by relationships",
                            _join(
                                [
                                    refs.seg(
                                        "relationships",
                                        r["id"],
                                        f"{r['from_label']} — {r['label']} → {r['to_label']}",
                                    )
                                    for r in rels
                                    if r
                                ]
                            ),
                        )
                    )
                items.append(
                    Item(
                        ref=refs.label("evidence", e["id"]),
                        heading=[e["description"]],
                        badges=[(PROVENANCE_LABELS.get(kind, kind), kind)],
                        fields=fields,
                        notes=note(e),
                    )
                )
            s.groups = [("", items)]

        elif key == "sources":
            s.intro = "Reliability ratings are the investigator's own assessment of each source."
            items = []
            for src in ws.get("sources", []):
                rating = src.get("reliability") or "unassessed"
                fields = [("URL", [{"url": src["url"]}])]
                if src.get("original_url") and src["original_url"] != src["url"]:
                    fields.append(("Original URL", [{"url": src["original_url"]}]))
                if src.get("source_type") and src["source_type"] != "unspecified":
                    fields.append(("Type", [src["source_type"].replace("_", " ")]))
                if src.get("published_on"):
                    fields.append(("Published / observed", [src["published_on"]]))
                if src.get("accessed_on"):
                    fields.append(("Accessed", [src["accessed_on"]]))
                fields.append(("Reliability (investigator-assigned)", [_reliability_text(rating)]))
                if rating != "unassessed":
                    if src.get("reliability_rationale"):
                        fields.append(("Rationale", [src["reliability_rationale"]]))
                    if src.get("reliability_assessed_on"):
                        fields.append(("Assessed on", [src["reliability_assessed_on"]]))
                cited_by = [by_id["findings"].get(i) for i in src.get("finding_ids", [])]
                if any(cited_by):
                    fields.append(
                        (
                            "Cited by findings",
                            _join(
                                [refs.seg("findings", f["id"], f["title"]) for f in cited_by if f]
                            ),
                        )
                    )
                ev = [by_id["evidence"].get(i) for i in src.get("evidence_ids", [])]
                if any(ev):
                    fields.append(
                        (
                            "Evidence from this source",
                            _join(
                                [
                                    refs.seg("evidence", e["id"], e["description"][:80])
                                    for e in ev
                                    if e
                                ]
                            ),
                        )
                    )
                items.append(
                    Item(
                        ref=refs.label("sources", src["id"]),
                        heading=[src.get("title") or src["url"]],
                        badges=[
                            (
                                f"Reliability {rating}"
                                if rating != "unassessed"
                                else "Not assessed",
                                "rel",
                            )
                        ],
                        fields=fields,
                        notes=note(src),
                    )
                )
            s.groups = [("", items)]

        elif key == "timeline":
            s.intro = (
                "Events in chronological order as recorded by the investigator. Approximate dates "
                "are marked ≈; ranges show start → end. Events are not verified by OpenOSINT."
            )
            items = []
            for ev in ws.get("events", []):
                fields = [
                    ("When", [format_event_date(ev)]),
                    ("Date type", [DATE_PRECISION_LABELS.get(ev.get("date_precision"), "")]),
                ]
                if ev.get("start_time") and not ev.get("timezone"):
                    fields.append(("Time zone", ["Not specified"]))
                for kind, label in (
                    ("target", "Targets"),
                    ("entity", "Entities"),
                    ("finding", "Findings"),
                    ("evidence", "Evidence"),
                    ("source", "Sources"),
                ):
                    links = [link for link in ev.get("links", []) if link["kind"] == kind]
                    if links:
                        table = {
                            "target": "targets",
                            "entity": "entities",
                            "finding": "findings",
                            "evidence": "evidence",
                            "source": "sources",
                        }[kind]
                        fields.append(
                            (
                                label,
                                _join(
                                    [refs.seg(table, link["id"], link["label"]) for link in links]
                                ),
                            )
                        )
                items.append(
                    Item(
                        ref=refs.label("events", ev["id"]),
                        heading=[ev["title"]],
                        badges=[
                            (ev.get("category", "other").replace("_", " "), "kind"),
                            (
                                EVENT_PROVENANCE_LABELS.get(
                                    ev.get("provenance"), ev.get("provenance", "")
                                ),
                                ev.get("provenance", ""),
                            ),
                        ],
                        fields=fields,
                        body=ev.get("description", ""),
                        notes=note(ev),
                    )
                )
            s.groups = [("", items)]

        elif key == "correlations":
            s.intro = (
                "Groupings of events recorded by the investigator. Each is an analyst hypothesis "
                "unless documented with a cited finding or evidence. Time order is not causation."
            )
            items = []
            events = by_id["events"]
            for c in ws.get("correlations", []):
                status = "Documented" if c["status"] == "documented" else "Analyst hypothesis"
                warnings = []
                if c.get("unsupported"):
                    warnings.append(
                        "Marked documented, but the finding and evidence it cited were deleted."
                    )
                if c.get("incomplete"):
                    warnings.append("Fewer than two of its events remain.")
                members = [events.get(i) for i in c.get("event_ids", [])]
                fields = [
                    ("Status", [status]),
                    ("Confidence (investigator-assigned)", [c["confidence"]]),
                    (
                        "Events",
                        _join(
                            [
                                refs.seg(
                                    "events", e["id"], f"{format_event_date(e)} — {e['title']}"
                                )
                                for e in members
                                if e
                            ]
                        ),
                    ),
                ]
                if c.get("finding_id"):
                    fields.append(
                        (
                            "Cites finding",
                            [refs.seg("findings", c["finding_id"], c.get("finding_title") or "")],
                        )
                    )
                cited = [by_id["evidence"].get(i) for i in c.get("evidence_ids", [])]
                if any(cited):
                    fields.append(
                        (
                            "Cites evidence",
                            _join(
                                [
                                    refs.seg("evidence", e["id"], e["description"][:80])
                                    for e in cited
                                    if e
                                ]
                            ),
                        )
                    )
                if c.get("recorded_by"):
                    fields.append(("Recorded by", [c["recorded_by"]]))
                items.append(
                    Item(
                        ref=refs.label("correlations", c["id"]),
                        heading=[c["title"]],
                        badges=[(status.lower(), "status")],
                        fields=fields,
                        body=c.get("explanation", ""),
                        notes=note(c),
                        warnings=warnings,
                    )
                )
            s.groups = [("", items)]

        elif key == "notes":
            s.intro = "The investigator's working notes, included at the report creator's request."
            s.groups = [
                (
                    "",
                    [
                        Item(
                            ref=refs.label("notes", n["id"]),
                            heading=[f"Note, updated {_date_only(n.get('updated_at', ''))}"],
                            body=n["body"],
                        )
                        for n in ws.get("notes", [])
                    ],
                )
            ]

        s.groups = [(label, items) for label, items in s.groups if items]
        sections.append(s)

    return {
        "title": options.title or ws["title"],
        "subtitle": options.subtitle,
        "investigation_title": ws["title"],
        "generated_at": generated_at.strftime("%Y-%m-%d %H:%M UTC"),
        "sections": sections,
        "legend": LEGEND,
        "notes_included": notes_on,
    }


def _join(segs: list) -> list:
    """Segments separated by '; '."""
    out: list = []
    for i, seg in enumerate(segs):
        if i:
            out.append("; ")
        out.append(seg)
    return out


def _reliability_text(rating: str) -> str:
    if rating == "unassessed":
        return "Not assessed"
    return f"{rating} — {RELIABILITY_LABELS.get(rating, rating)}"


def _source_segs(refs: _Refs, source_id: str, url: str | None, rating: str | None) -> list:
    rating = rating or "unassessed"
    tail = f" (reliability {rating})" if rating != "unassessed" else " (reliability not assessed)"
    seg = refs.seg("sources", source_id, url or "")
    if isinstance(seg, dict):
        return [seg, tail]
    return [{"url": url}, tail] if url else [tail.strip()]


# ---------------------------------------------------------------------------
# HTML
# ---------------------------------------------------------------------------

# Sent as a header with the report, and embedded (without frame-ancestors, which browsers
# ignore in a meta tag) so a downloaded copy keeps blocking scripts and remote loads.
META_CSP = (
    "default-src 'none'; style-src 'unsafe-inline'; img-src 'none'; base-uri 'none'; "
    "form-action 'none'"
)
CSP = META_CSP + "; frame-ancestors 'self'"

_CSS = """
:root{--text:#1b1f24;--muted:#57606a;--line:#d0d7de;--accent:#0b5cad;--warn:#9a6700;--neg:#b42318;--pos:#1a7f37}
*{box-sizing:border-box}
body{margin:0;background:#fff;color:var(--text);font:15px/1.55 system-ui,-apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif}
main{max-width:880px;margin:0 auto;padding:32px 20px 48px}
a{color:var(--accent)}
header.report{border-bottom:2px solid var(--text);margin-bottom:18px;padding-bottom:12px}
header.report h1{margin:0;font-size:26px;line-height:1.25}
header.report .subtitle{margin:4px 0 0;font-size:16px;color:var(--muted)}
header.report .meta{margin:8px 0 0;font-size:12px;color:var(--muted)}
.legend{border:1px solid var(--line);border-radius:6px;padding:10px 14px;margin:0 0 22px;font-size:13px;background:#f6f8fa}
.legend dt{font-weight:600}
.legend dd{margin:0 0 6px}
section.sec{margin:26px 0 0}
section.sec>h2{font-size:19px;margin:0 0 4px;padding-bottom:4px;border-bottom:1px solid var(--line)}
.intro{color:var(--muted);font-size:13px;margin:4px 0 10px}
h3.group{font-size:14px;margin:16px 0 6px;color:var(--muted);text-transform:uppercase;letter-spacing:.04em}
article.item{border:1px solid var(--line);border-radius:6px;padding:10px 14px;margin:8px 0;break-inside:avoid;page-break-inside:avoid}
article.item h4{margin:0 0 4px;font-size:15px;overflow-wrap:anywhere}
.ref{display:inline-block;font:600 11px/1.6 ui-monospace,SFMono-Regular,Menlo,monospace;color:var(--muted);border:1px solid var(--line);border-radius:4px;padding:0 5px;margin-right:6px;vertical-align:1px}
.badges{margin:2px 0 6px}
.badge{display:inline-block;font-size:11px;border:1px solid var(--line);border-radius:10px;padding:0 8px;margin:0 4px 2px 0;color:var(--muted)}
.badge.observation,.badge.documented{border-color:var(--pos);color:var(--pos)}
.badge.reported,.badge.assumption,.badge.hypothesis,.badge.unspecified{border-color:var(--warn);color:var(--warn);border-style:dashed}
.badge.conclusion{border-color:#6639ba;color:#6639ba}
dl.fields{display:grid;grid-template-columns:minmax(120px,max-content) 1fr;gap:2px 14px;margin:6px 0 0;font-size:13px}
dl.fields dt{color:var(--muted)}
dl.fields dd{margin:0;overflow-wrap:anywhere}
.body{white-space:pre-wrap;overflow-wrap:anywhere;margin:6px 0 0}
.notes{white-space:pre-wrap;overflow-wrap:anywhere;margin:6px 0 0;font-size:13px;color:var(--muted);border-left:3px solid var(--line);padding-left:8px}
.warning{color:var(--neg);font-size:13px;margin:6px 0 0}
.empty{color:var(--muted);font-style:italic}
footer.report{margin-top:34px;border-top:1px solid var(--line);padding-top:8px;font-size:12px;color:var(--muted)}
.mono{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:12px}
@media (max-width:600px){main{padding:18px 14px 32px}dl.fields{grid-template-columns:1fr}dl.fields dt{margin-top:4px}header.report h1{font-size:21px}}
@media print{@page{margin:16mm 14mm}body{font-size:11pt}main{max-width:none;padding:0}a{color:inherit;text-decoration:none}
  section.sec>h2{break-after:avoid;page-break-after:avoid}.legend{background:none}}
"""


def _h(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def _segs_html(segs: list) -> str:
    out = []
    for seg in segs:
        if isinstance(seg, dict) and "ref" in seg:
            text = f" {_h(seg['text'])}" if seg.get("text") else ""
            out.append(f'<a href="#{_h(seg["ref"])}">[{_h(seg["ref"])}]</a>{text}')
        elif isinstance(seg, dict) and "url" in seg:
            url = safe_url(seg["url"])
            if url:
                out.append(
                    f'<a class="mono" href="{_h(url)}" rel="noopener noreferrer nofollow">{_h(url)}</a>'
                )
            else:
                out.append(f'<span class="mono">{_h(seg["url"])}</span>')
        else:
            out.append(_h(seg))
    return "".join(out)


def render_html(model: dict) -> str:
    parts = [
        "<!doctype html>",
        '<html lang="en"><head><meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        f'<meta http-equiv="Content-Security-Policy" content="{_h(META_CSP)}">',
        '<meta name="referrer" content="no-referrer">',
        f"<title>{_h(model['title'])}</title>",
        f"<style>{_CSS}</style></head><body><main>",
        '<header class="report">',
        f"<h1>{_h(model['title'])}</h1>",
    ]
    if model["subtitle"]:
        parts.append(f'<p class="subtitle">{_h(model["subtitle"])}</p>')
    meta = f"Investigation: {_h(model['investigation_title'])} · Generated {_h(model['generated_at'])} by OpenOSINT, locally"
    parts.append(f'<p class="meta">{meta}</p></header>')
    parts.append('<dl class="legend">')
    for term, text in model["legend"]:
        parts.append(f"<dt>{_h(term)}</dt><dd>{_h(text)}</dd>")
    parts.append("</dl>")
    for sec in model["sections"]:
        parts.append(f'<section class="sec" id="sec-{_h(sec.key)}"><h2>{_h(sec.title)}</h2>')
        if sec.intro:
            parts.append(f'<p class="intro">{_h(sec.intro)}</p>')
        if not sec.groups and sec.empty:
            parts.append(f'<p class="empty">{_h(sec.empty)}</p>')
        for label, items in sec.groups:
            if label:
                parts.append(f'<h3 class="group">{_h(label)}</h3>')
            for item in items:
                anchor = f' id="{_h(item.ref)}"' if item.ref else ""
                ref = f'<span class="ref">{_h(item.ref)}</span>' if item.ref else ""
                parts.append(
                    f'<article class="item"{anchor}><h4>{ref}{_segs_html(item.heading)}</h4>'
                )
                if item.badges:
                    parts.append(
                        '<div class="badges">'
                        + "".join(
                            f'<span class="badge {_h(cls)}">{_h(text)}</span>'
                            for text, cls in item.badges
                        )
                        + "</div>"
                    )
                for warning in item.warnings:
                    parts.append(f'<p class="warning">{_h(warning)}</p>')
                if item.fields:
                    parts.append('<dl class="fields">')
                    for label_, segs in item.fields:
                        parts.append(f"<dt>{_h(label_)}</dt><dd>{_segs_html(segs)}</dd>")
                    parts.append("</dl>")
                if item.body:
                    parts.append(f'<div class="body">{_h(item.body)}</div>')
                if item.notes:
                    parts.append(f'<div class="notes">Analyst notes: {_h(item.notes)}</div>')
                parts.append("</article>")
        parts.append("</section>")
    notes_line = (
        "Analyst notes are included."
        if model["notes_included"]
        else "Analyst notes are not included."
    )
    parts.append(
        '<footer class="report">Assembled from the investigator\'s records in OpenOSINT. '
        "Nothing in this report was generated, inferred or verified automatically. "
        f"{notes_line}</footer>"
    )
    parts.append("</main></body></html>")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# PDF
# ---------------------------------------------------------------------------

# The PDF uses reportlab's built-in fonts, which cover Latin text; replace the few symbols
# they lack. Text in other scripts is a known limitation (see the docs).
_PDF_SUBS = {
    "≈": "approx.",
    "→": "->",
    "–": "-",
    "—": "-",
    "“": '"',
    "”": '"',
    "‘": "'",
    "’": "'",
    "…": "...",
}


def _plain(value: Any) -> str:
    text = "" if value is None else str(value)
    for a, b in _PDF_SUBS.items():
        text = text.replace(a, b)
    return text


def _p(value: Any) -> str:
    """Text for reportlab's paragraph markup: symbols substituted, markup escaped."""
    return xml_escape(_plain(value), {'"': "&quot;"})


def _segs_pdf(segs: list) -> str:
    out = []
    for seg in segs:
        if isinstance(seg, dict) and "ref" in seg:
            text = f" {_p(seg['text'])}" if seg.get("text") else ""
            out.append(
                f'<link href="#{_p(seg["ref"])}" color="#0b5cad">[{_p(seg["ref"])}]</link>{text}'
            )
        elif isinstance(seg, dict) and "url" in seg:
            url = safe_url(seg["url"])
            out.append(
                f'<link href="{_p(url)}" color="#0b5cad">{_p(url)}</link>'
                if url
                else _p(seg["url"])
            )
        else:
            out.append(_p(seg))
    return "".join(out)


# Field values longer than this are laid out as paragraphs in the PDF, not table cells.
LONG_FIELD = 600


def _seg_length(segs: list) -> int:
    total = 0
    for seg in segs:
        if isinstance(seg, dict):
            total += len(str(seg.get("text") or seg.get("url") or "")) + len(
                str(seg.get("ref") or "")
            )
        else:
            total += len(str(seg))
    return total


def render_pdf(model: dict) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import (
        KeepTogether,
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )

    base = getSampleStyleSheet()
    st = {
        "title": ParagraphStyle(
            "t", parent=base["Title"], fontSize=18, leading=22, alignment=0, spaceAfter=2
        ),
        "subtitle": ParagraphStyle(
            "st",
            parent=base["Normal"],
            fontSize=12,
            textColor=colors.HexColor("#57606a"),
            spaceAfter=2,
        ),
        "meta": ParagraphStyle(
            "m",
            parent=base["Normal"],
            fontSize=8,
            textColor=colors.HexColor("#57606a"),
            spaceAfter=8,
        ),
        "h2": ParagraphStyle(
            "h2", parent=base["Heading2"], fontSize=13, spaceBefore=12, spaceAfter=3
        ),
        "group": ParagraphStyle(
            "g",
            parent=base["Heading4"],
            fontSize=9,
            textColor=colors.HexColor("#57606a"),
            spaceBefore=6,
        ),
        "intro": ParagraphStyle(
            "i",
            parent=base["Normal"],
            fontSize=8.5,
            textColor=colors.HexColor("#57606a"),
            spaceAfter=4,
        ),
        "item": ParagraphStyle(
            "it", parent=base["Heading4"], fontSize=10, spaceBefore=6, spaceAfter=1
        ),
        "badges": ParagraphStyle(
            "b", parent=base["Normal"], fontSize=8, textColor=colors.HexColor("#57606a")
        ),
        "field": ParagraphStyle("f", parent=base["Normal"], fontSize=8.5, leading=11),
        "body": ParagraphStyle("bd", parent=base["Normal"], fontSize=9, leading=12, spaceBefore=2),
        "notes": ParagraphStyle(
            "n",
            parent=base["Normal"],
            fontSize=8.5,
            leading=11,
            textColor=colors.HexColor("#57606a"),
            leftIndent=6,
        ),
        "warn": ParagraphStyle(
            "w", parent=base["Normal"], fontSize=8.5, textColor=colors.HexColor("#b42318")
        ),
        "legend": ParagraphStyle("l", parent=base["Normal"], fontSize=8, leading=10.5),
        "empty": ParagraphStyle(
            "e", parent=base["Italic"], fontSize=9, textColor=colors.HexColor("#57606a")
        ),
    }

    def para(text: str, style: str) -> Paragraph:
        return Paragraph(text.replace("\n", "<br/>"), st[style])

    story: list = [para(_p(model["title"]), "title")]
    if model["subtitle"]:
        story.append(para(_p(model["subtitle"]), "subtitle"))
    story.append(
        para(
            f"Investigation: {_p(model['investigation_title'])} - Generated {_p(model['generated_at'])} by OpenOSINT, locally",
            "meta",
        )
    )
    for term, text in model["legend"]:
        story.append(para(f"<b>{_p(term)}.</b> {_p(text)}", "legend"))
    story.append(Spacer(1, 4 * mm))
    for sec in model["sections"]:
        story.append(para(_p(sec.title), "h2"))
        if sec.intro:
            story.append(para(_p(sec.intro), "intro"))
        if not sec.groups and sec.empty:
            story.append(para(_p(sec.empty), "empty"))
        for label, items in sec.groups:
            if label:
                story.append(para(_p(label).upper(), "group"))
            for item in items:
                anchor = f'<a name="{_p(item.ref)}"/>[{_p(item.ref)}] ' if item.ref else ""
                block = [para(anchor + _segs_pdf(item.heading), "item")]
                if item.badges:
                    block.append(para(" | ".join(_p(text) for text, _ in item.badges), "badges"))
                for warning in item.warnings:
                    block.append(para(_p(warning), "warn"))
                # A table row cannot break across pages, so a long value (a rationale, a list
                # of many cross-references) goes below the table as a paragraph that can.
                short = [(k, v) for k, v in item.fields if _seg_length(v) <= LONG_FIELD]
                long_ = [(k, v) for k, v in item.fields if _seg_length(v) > LONG_FIELD]
                if short:
                    rows = [[para(_p(k), "field"), para(_segs_pdf(v), "field")] for k, v in short]
                    table = Table(rows, colWidths=[42 * mm, None])
                    table.setStyle(
                        TableStyle(
                            [
                                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                                ("TEXTCOLOR", (0, 0), (0, -1), colors.HexColor("#57606a")),
                                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                                ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
                                ("TOPPADDING", (0, 0), (-1, -1), 1),
                            ]
                        )
                    )
                    block.append(table)
                for k, v in long_:
                    block.append(para(f"<b>{_p(k)}:</b> {_segs_pdf(v)}", "body"))
                if item.body:
                    block.append(para(_p(item.body), "body"))
                if item.notes:
                    block.append(para(f"Analyst notes: {_p(item.notes)}", "notes"))
                # Keep short items on one page; long ones may break across pages.
                size = len(item.body) + len(item.notes) + sum(_seg_length(v) for _, v in long_)
                if size < 1500:
                    story.append(KeepTogether(block))
                else:
                    story.extend(block)
    notes_line = (
        "Analyst notes are included."
        if model["notes_included"]
        else "Analyst notes are not included."
    )
    story.append(Spacer(1, 6 * mm))
    story.append(
        para(
            "Assembled from the investigator's records in OpenOSINT. Nothing in this report was "
            f"generated, inferred or verified automatically. {notes_line}",
            "meta",
        )
    )

    def footer(canvas, doc):  # noqa: ANN001
        canvas.saveState()
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(colors.HexColor("#57606a"))
        canvas.drawString(14 * mm, 9 * mm, _plain(model["title"])[:90])  # plain text, not markup
        canvas.drawRightString(A4[0] - 14 * mm, 9 * mm, f"Page {doc.page}")
        canvas.restoreState()

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=14 * mm,
        rightMargin=14 * mm,
        topMargin=14 * mm,
        bottomMargin=16 * mm,
        title=model["title"][:200],
        author="",
        creator="OpenOSINT",
        subject="Investigation report",
    )
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return buf.getvalue()


def report_filename(title: str, fmt: str, generated: datetime | None = None) -> str:
    """A safe download name: report-<slug>-<date>.<ext>."""
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:60] or "investigation"
    day = (generated or datetime.now(timezone.utc)).strftime("%Y-%m-%d")
    return f"report-{slug}-{day}.{fmt}"
