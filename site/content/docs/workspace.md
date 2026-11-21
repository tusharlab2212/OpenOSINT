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
| Findings | Your findings, each with a title, description, type, confidence, source URL, target, date recorded and investigator notes |
| Evidence | Evidence entries: a description, source URL, date collected, and optionally the target and the finding it supports |
| Sources | Every source URL the findings and evidence rely on, with how many of each use it. You can also add a source by hand. |
| Notes | Free-form investigator notes |

Every item can be edited and deleted. Deleting a target, source or finding removes the link from the items that pointed to it; the items themselves stay.

## Findings: observation, assumption or conclusion

Each finding has a type, and the Findings tab groups them so the difference stays visible:

- **Observation**: what a source shows. Give it a source URL.
- **Assumption**: something you take as given but have not supported with a source.
- **Conclusion**: what you infer from the observations.

Confidence is **low**, **medium** or **high**. A new finding starts at **low**, and nothing raises it for you: set it yourself when the evidence supports it, not because a tool returned a result.

## Sources

A source URL typed into a finding or an evidence entry is added to the Sources tab automatically, or linked to the existing source with the same URL. Only `http://` and `https://` URLs are accepted. URLs are stored, never fetched.

## Where the data is

Everything is in `workspace.db`, a SQLite file in the data directory (`~/.openosint/`, or `$OPENOSINT_HOME`). It persists across restarts. Like the rest of the data directory, a new directory is created owner-only (0700) and the new database file 0600. Nothing is sent anywhere. Back up or move an investigation by copying that file while OpenOSINT is not running.

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

Invalid input gets a 422 with the reason, an unknown id a 404, and a duplicate target or source URL a 409. Browser requests from another origin are rejected, as for every `/api` route.

## Limits

- One user, one machine: there are no accounts, sharing or sync.
- Findings are not created from chat or tool results automatically; you record them.
- Evidence is a description and a link, not a stored copy: attaching files or archived snapshots is not supported yet.
- No export yet. The data is a plain SQLite file you can read with any SQLite tool.
