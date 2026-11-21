---
title: "Research workspace"
label: "Research workspace"
seo_title: "OpenOSINT research workspace: organise an investigation"
description: "Keep an investigation's targets, findings, sources, evidence and notes in one place, saved locally in your data directory. How to use the /workspace page."
group: Use
order: 6.5
---
The research workspace organises an investigation instead of leaving it in chat history. You record what you research and what you find; the workspace keeps it structured and saved.

It is a record-keeping tool only. Nothing in it runs a tool, fetches a URL or contacts a target. Source links open only when you click them.

## Open it

Start the [web UI](/docs/web-ui/) and click **Workspace** in the left rail, or go to `http://127.0.0.1:8080/workspace`.

The workspace only works on a local, unrestricted instance. A public or demo instance, a non-loopback bind, or a request through a reverse proxy without `OPENOSINT_TRUSTED_PROXY` gets a 403, so one shared store is never exposed to whoever can reach the server.

## Investigations

- **Create** one with **+ New investigation**: a title and an optional description.
- **Open** one from the list. The list shows every saved investigation, most recently changed first.
- **Rename** it or change its description from **Overview → Rename / edit description**.
- **Delete** it from **Overview → Delete investigation**. You must type its exact title to confirm. This deletes every target, finding, source, evidence entry and note in it, and cannot be undone.

## What an investigation holds

| Tab | What you record |
|---|---|
| Overview | Title, description, created and updated dates, and how many items each tab holds |
| Targets | The identifiers you research: username, domain, email, URL, IP, phone or other. Domains and emails are lower-cased; duplicates are refused. |
| Findings | Your findings, each with a title, description, provenance, confidence, source URL, target, date recorded and investigator notes, plus the evidence that supports it |
| Evidence | Evidence entries: a description, provenance, source URL, date collected, and optionally the target and the finding it supports |
| Sources | Every source the findings and evidence rely on, with its type, dates, your reliability rating and what cites it. You can also add a source by hand. |
| Timeline | Dated events and the correlations you draw between them (below) |
| Graph | Entities and the relationships between them, drawn as an interactive map (below) |
| Notes | Free-form investigator notes |
| Report | A report of the investigation, as HTML or PDF (below) |

Every item can be edited and deleted. Deleting a target, source or finding removes the link from the items that pointed to it; the items themselves stay.

## Provenance: observation, reported claim, assumption or conclusion

Each finding records where it comes from, and the Findings tab groups them so the difference stays visible:

- **Direct observation**: what you saw in a source yourself. Give it a source URL.
- **Source-reported claim**: what a source says, which you have not verified. Give it a source URL.
- **Assumption**: something you take as given but have not supported with a source.
- **Analyst conclusion**: what you infer from the above.

Evidence entries have a provenance too: **direct observation** or **source-reported claim**. Evidence saved before this field existed shows **not specified**; it is never guessed.

Confidence is **low**, **medium** or **high**. A new finding starts at **low**, and nothing raises it for you: set it yourself when the evidence supports it, not because a tool returned a result.

## Sources

A source URL typed into a finding or an evidence entry is added to the Sources tab automatically, or linked to the existing source with the same URL. Only `http://` and `https://` URLs are accepted. URLs are stored, never fetched.

A source records:

| Field | Meaning |
|---|---|
| URL | Where you accessed it. Kept exactly as first entered and read-only afterwards, because findings and evidence cite it: a different URL is a different source. |
| Source title | The page or document title |
| Source type | website, social media, news, government, company, court record, dataset, archive, document, other, or unspecified |
| Original URL | Where the content originally lived, when the URL above is a copy or an archive |
| Published / observed on | When the source published the content, or when you observed it |
| Date accessed | When you accessed it |
| Reliability | Your assessment, below |

### Reliability

Reliability uses the A–F scale common in intelligence source grading:

| Rating | Meaning |
|---|---|
| A | Completely reliable |
| B | Usually reliable |
| C | Fairly reliable |
| D | Not usually reliable |
| E | Unreliable |
| F | Reliability cannot be judged |

Every source starts **not assessed**, including those added automatically. Only you set a rating, and a rating needs a written rationale ("Why this rating"), which is shown with it. The date of the assessment is recorded when you set or change the rating or rationale. OpenOSINT never rates a source and never changes your rating. The rating describes the source, not any one claim in it: record how far you trust a claim in the finding's confidence.

### Tracing

- A source card lists the findings that cite it, the evidence taken from it, and the findings that evidence supports.
- A finding card lists its supporting evidence with each entry's provenance, source and source rating.
- Finding and evidence cards show the cited source's rating next to its link.

Click any listed item to open it.

## Timeline and correlation

The **Timeline** tab lists the investigation's events in date order. Like the rest of the workspace it holds only what you enter: nothing dates, links, verifies or correlates events for you, and nothing contacts a target.

**Events** have a title, an optional description and investigator notes, a category (communication, registration, publication, account activity, infrastructure change, transaction, meeting, travel, legal or other) and a provenance:

| Provenance | Meaning |
|---|---|
| Source-reported | A source says it happened |
| Analyst observation | You saw it in a source yourself |
| Hypothesis (the default) | You think it may have happened |
| Analyst conclusion | You infer it from other events or findings |

There is no "verified" provenance, and a new event is a hypothesis until you say otherwise.

**Dates** are one of three kinds, shown differently in the list:

- **Exact**: a date (`YYYY-MM-DD`), optionally with a time (`HH:MM`).
- **Approximate**, shown with `≈`: a year (`2026`), a month (`2026-03`) or a day.
- **Range**, shown as `start → end`: a start and an end date, each optionally with a time.

A time can have a time zone: an IANA name such as `Europe/London`, `UTC`, or an offset such as `+05:30`. Dates and times are kept exactly as you entered them.

Events can be **linked** to the investigation's targets, entities, findings, evidence and sources. Deleting a linked item removes the link and keeps the event.

Using the timeline:

- Sort oldest or newest first. Filter by category, provenance, linked entity, date range, events that cite evidence, or text.
- Click an event to see its details, links and correlations; edit or delete it there. Deleting asks first and says which correlations lose it.
- Long timelines show 100 events at a time, grouped by month, with **Show more**.

**Correlations** group two or more events you think may be connected. Tick events and choose **Compare selected** to see them side by side, in order, with the time between them; **Group as correlation** records the grouping. A correlation has a title, your explanation, a confidence level (low by default), notes, an optional "recorded by", and optionally a cited finding and evidence. It is an **analyst hypothesis** unless you mark it documented, which needs a cited finding or evidence entry. The time between events is plain arithmetic: it is shown as approximate when a date is approximate or only one of the times has a time zone, and it is never a claim that one event caused another. If a correlation loses its citations or falls below two events because something was deleted, it is flagged, not changed.

### How events are ordered

An event with a time and a time zone is ordered by that moment in UTC. An event without a time zone is ordered by its date and time as written, and an approximate date by the start of its year or month. A timeline that mixes events with and without time zones can therefore be out of order by up to the time-zone difference on the same day; give times a zone when the order matters.

## Entity relationship graph

The **Graph** tab is a map you draw yourself. Every entity and relationship is entered by you: nothing is looked up, inferred or created from targets, findings or tool results, and nothing contacts an entity.

**Entities** have a type (person, organization, username, domain, email, phone, IP address, location or custom), a name, and optionally a description, analyst notes and a link to one of the investigation's targets. An entity linked to a target and given no name takes the target's value. Each type has its own colour and shape.

**Relationships** connect two different entities. Each has:

| Field | Meaning |
|---|---|
| Relationship | Your own wording, or a suggestion such as "owns", "works for", "registered" or "hosted on" |
| Status | **Hypothesis** (the default) or **documented fact**. A documented relationship must cite a finding or at least one evidence entry; without one it is refused. |
| Confidence | Low (the default), medium or high |
| Cites finding / evidence | The finding and evidence entries that support it |
| Description, analyst notes | Free text |
| Recorded by | Optional name or initials of who recorded it |

On the graph, documented relationships are solid green lines, hypotheses are dashed, and a thicker line means higher confidence. If every finding and evidence entry a documented relationship cited is deleted, it is drawn as a red dotted line and its details say so: it is not downgraded automatically, so you decide whether to cite new support or mark it a hypothesis.

Using the graph:

- Drag a node to move it; positions are saved. Scroll or pinch to zoom, and drag the background to pan.
- Click an entity or a relationship to see its details. A relationship shows its cited evidence with each entry's provenance, source and source reliability, and its finding. Click any of them to open it.
- The relationship list under the graph shows every relationship as text, which is easier to use on a phone or with many relationships.
- **Fit** shows the whole graph. **Arrange** lays every entity out again and replaces their saved positions; it asks first.
- Deleting an entity deletes its relationships, and asks first, naming how many. Deleting a relationship asks first too. Deleting a finding or evidence entry removes it from the relationships that cited it.

New entities without a saved position are placed automatically next to the existing ones. Larger graphs hide small labels until you zoom in and simplify drawing while you pan.

## Reports

The **Report** tab assembles a report from what you recorded. It is an assembly, not an analysis: nothing is summarised, inferred, dated or verified, missing values are left out rather than filled in, and every confidence level and reliability rating is labelled as investigator-assigned. Reports are generated on this computer.

Choose the sections to include, in this fixed order: investigation overview, targets, entities, relationships, findings, evidence, sources, timeline, correlations and analyst notes. **Analyst notes are off by default**; including them adds the Notes section and the notes on every item. You can set a title and a subtitle; the title defaults to the investigation's.

- **Preview** shows the report inside the page (in a sandboxed frame that runs nothing).
- **Open in a new tab** shows the HTML report on its own, ready to print. The browser's *Print → Save as PDF* gives a PDF of exactly this layout.
- **Download HTML** saves a single self-contained file: no scripts, no remote content, and a Content-Security-Policy that keeps it that way.
- **Download PDF** builds a PDF on the server with reportlab (already a dependency).

What the report shows:

- A short legend explaining provenance, investigator-assigned confidence and reliability, and that relationships and correlations are hypotheses unless documented.
- Each item with a reference: T targets, N entities, R relationships, F findings, E evidence, S sources, V events, C correlations, M notes. Cross-references link to the referenced item when its section is included; otherwise the item is named (or its URL shown) without a link.
- Findings grouped by provenance (direct observations, source-reported claims, assumptions, analyst conclusions) with their confidence, source and the source's reliability, target and supporting evidence.
- Evidence with provenance, collection date, source, target, the finding it supports and the relationships that cite it.
- Sources with their URL, original URL, type, dates, reliability (or "Not assessed") with rationale and date, and what cites them.
- The timeline in date order with approximate dates marked ≈ and ranges as start → end; correlations labelled analyst hypothesis or documented, with "time order is not causation".
- Warnings recorded on items, such as a documented relationship whose citations were deleted.

The local API is `GET /api/investigations/{id}/report` with `format` (`html` or `pdf`), `sections` (comma-separated), `title`, `subtitle` and `download=true` (HTML as an attachment). Unknown sections, an unknown format or a title over 200 characters get a 422.

## Where the data is

Everything is in `workspace.db`, a SQLite file in the data directory (`~/.openosint/`, or `$OPENOSINT_HOME`). It persists across restarts. A database from an earlier version is upgraded in place the first time it is opened: new fields and the graph and timeline tables are added empty or unassessed, and nothing already saved is changed. An older OpenOSINT cannot open it afterwards. Like the rest of the data directory, a new directory is created owner-only (0700) and the new database file 0600. Nothing is sent anywhere. Back up or move an investigation by copying that file while OpenOSINT is not running.

## API

The page uses these local routes, which you can also call from a script on the same machine:

| Method and path | Does |
|---|---|
| `GET /api/investigations` | List investigations, with item counts |
| `POST /api/investigations` | Create one: `{"title": …, "description": …}` |
| `GET /api/investigations/{id}` | One investigation with every tab |
| `PATCH /api/investigations/{id}` | Change `title` and/or `description` |
| `DELETE /api/investigations/{id}` | Delete it and everything in it |
| `POST /api/investigations/{id}/{tab}` | Add to `targets`, `findings`, `evidence`, `sources` or `notes` |
| `PATCH /api/investigations/{id}/{tab}/{item_id}` | Edit an item; send `""` to clear a field or link |
| `DELETE /api/investigations/{id}/{tab}/{item_id}` | Delete an item |
| `GET /api/investigations/{id}/sources/{item_id}/trace` | A source with the findings that cite it, its evidence, and the findings that evidence supports |
| `GET /api/investigations/{id}/findings/{item_id}/trace` | A finding with its source and its supporting evidence, each with its source |
| `POST`, `PATCH`, `DELETE` on `/api/investigations/{id}/entities[/{item_id}]` and `…/relationships[/{item_id}]` | Graph entities and relationships, like the other tabs. A relationship's evidence is a list: `"evidence_ids": [...]`. |
| `PUT /api/investigations/{id}/entities/{item_id}/position` | Save a node's position: `{"x": …, "y": …}` |
| `POST`, `PATCH`, `DELETE` on `/api/investigations/{id}/events[/{item_id}]` and `…/correlations[/{item_id}]` | Timeline events (links as `"links": [{"kind": "evidence", "id": …}]`) and correlations (`"event_ids"`, `"evidence_ids"`) |
| `GET /api/investigations/{id}/relationships/{item_id}/trace` | A relationship with its two entities, its finding and its evidence, each with its source |

Invalid input gets a 422 with the reason, an unknown id a 404, and a duplicate target or source URL a 409. Browser requests from another origin are rejected, as for every `/api` route.

## Limits

- One user, one machine: there are no accounts, sharing or sync.
- Findings are not created from chat or tool results automatically; you record them.
- Evidence is a description and a link, not a stored copy: attaching files or archived snapshots is not supported yet.
- Reliability is one rating per source. There is no separate rating per claim, and no history of earlier ratings: changing a rating replaces it (the new rationale and date are what you see).
- A source's URL cannot be corrected after it is saved; add the right URL as a new source and move the links.
- The graph has one view per investigation: no filtering, grouping, search or export, and no undo for moved nodes.
- Relationships are directed (from → to); there is no separate undirected kind. Several relationships can join the same two entities.
- "Recorded by" is free text you type: there are no user accounts, so it is not verified.
- The timeline is a list, not a scaled chart: distance on screen does not show time. Events are grouped by the month of their start date.
- Recurring events, uncertainty margins ("± 3 days") and time zones on approximate dates are not supported; use the notes.
- Reports are generated from the current data each time; there is no saved report history or versioning, and no Word or Markdown export.
- The PDF uses reportlab's built-in fonts, which cover Latin-script text. Text in other scripts (Cyrillic, Arabic, Chinese and others) may not display in the PDF; use the HTML report, or print it to PDF from the browser, for those. A few symbols are written out in the PDF (≈ as "approx.", → as "->").
- Reports contain no images or graph drawing: the entity graph is listed as entities and relationships.
- The date filters compare with each event's sort key (UTC when a time zone is given), so an event late in the day in a time zone west of UTC can fall on the next day for filtering.
- Very large graphs (thousands of elements) stay usable but slower; the relationship list then becomes the practical view.
- No export yet. The data is a plain SQLite file you can read with any SQLite tool.
