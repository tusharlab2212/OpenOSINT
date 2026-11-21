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
| Graph | Entities and the relationships between them, drawn as an interactive map (below) |
| Notes | Free-form investigator notes |

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

## Where the data is

Everything is in `workspace.db`, a SQLite file in the data directory (`~/.openosint/`, or `$OPENOSINT_HOME`). It persists across restarts. A database from an earlier version is upgraded in place the first time it is opened: new fields and the graph's tables are added empty or unassessed, and nothing already saved is changed. An older OpenOSINT cannot open it afterwards. Like the rest of the data directory, a new directory is created owner-only (0700) and the new database file 0600. Nothing is sent anywhere. Back up or move an investigation by copying that file while OpenOSINT is not running.

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
- Very large graphs (thousands of elements) stay usable but slower; the relationship list then becomes the practical view.
- No export yet. The data is a plain SQLite file you can read with any SQLite tool.
