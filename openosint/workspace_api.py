"""HTTP routes for the research workspace (``/api/investigations``) and its page (``/workspace``).

The routes read and write the local ``workspace.db`` only: no tool runs, no outbound
request, no URL is fetched. Investigations are private data, so on a restricted request
(a public or demo instance, or one reached through an undeclared reverse proxy) every
route answers 403 instead of exposing one shared store to whoever can reach the server.
"""

# No `from __future__ import annotations`: the route factories below annotate request
# bodies with models chosen at runtime, which FastAPI must resolve from the signature.

import asyncio
from collections.abc import Callable
from pathlib import Path
from typing import Literal, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel, ConfigDict, Field

from openosint import workspace as ws
from openosint import workspace_report as report
from openosint.workspace import WorkspaceError, WorkspaceStore

_URL = Field(default=None, max_length=ws.URL_MAX)
_TEXT = Field(default=None, max_length=ws.TEXT_MAX)
_TITLE = Field(default=None, max_length=ws.TITLE_MAX)
_SHORT = Field(default=None, max_length=ws.SHORT_TEXT_MAX)
_ID = Field(default=None, max_length=32)
_DATE = Field(default=None, max_length=10)


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class InvestigationCreate(_Body):
    title: str = Field(max_length=ws.TITLE_MAX)
    description: Optional[str] = _TEXT


class InvestigationUpdate(_Body):
    title: Optional[str] = _TITLE
    description: Optional[str] = _TEXT


class TargetBody(_Body):
    kind: Optional[Literal[ws.TARGET_KINDS]] = None  # type: ignore[valid-type]
    value: Optional[str] = _SHORT
    notes: Optional[str] = _TEXT


class SourceBody(_Body):
    url: Optional[str] = _URL
    title: Optional[str] = _TITLE
    notes: Optional[str] = _TEXT
    source_type: Optional[Literal[ws.SOURCE_TYPES]] = None  # type: ignore[valid-type]
    original_url: Optional[str] = _URL
    published_on: Optional[str] = _DATE
    accessed_on: Optional[str] = _DATE
    # Validated by the store (accepts any letter case); assigned only by the user.
    reliability: Optional[str] = Field(default=None, max_length=20)
    reliability_rationale: Optional[str] = _TEXT


class FindingBody(_Body):
    title: Optional[str] = _TITLE
    description: Optional[str] = _TEXT
    kind: Optional[Literal[ws.FINDING_KINDS]] = None  # type: ignore[valid-type]
    confidence: Optional[Literal[ws.CONFIDENCE_LEVELS]] = None  # type: ignore[valid-type]
    source_id: Optional[str] = _ID
    source_url: Optional[str] = _URL
    target_id: Optional[str] = _ID
    notes: Optional[str] = _TEXT
    recorded_on: Optional[str] = _DATE


class NoteBody(_Body):
    body: Optional[str] = _TEXT


class EvidenceBody(_Body):
    description: Optional[str] = _TEXT
    source_id: Optional[str] = _ID
    source_url: Optional[str] = _URL
    target_id: Optional[str] = _ID
    finding_id: Optional[str] = _ID
    collected_on: Optional[str] = _DATE
    notes: Optional[str] = _TEXT
    kind: Optional[Literal[ws.EVIDENCE_KINDS]] = None  # type: ignore[valid-type]


class EntityBody(_Body):
    kind: Optional[Literal[ws.ENTITY_KINDS]] = None  # type: ignore[valid-type]
    label: Optional[str] = _TITLE
    description: Optional[str] = _TEXT
    notes: Optional[str] = _TEXT
    target_id: Optional[str] = _ID
    pos_x: Optional[float] = None
    pos_y: Optional[float] = None


class RelationshipBody(_Body):
    from_entity_id: Optional[str] = _ID
    to_entity_id: Optional[str] = _ID
    label: Optional[str] = _TITLE
    status: Optional[Literal[ws.RELATIONSHIP_STATUSES]] = None  # type: ignore[valid-type]
    confidence: Optional[Literal[ws.CONFIDENCE_LEVELS]] = None  # type: ignore[valid-type]
    description: Optional[str] = _TEXT
    notes: Optional[str] = _TEXT
    recorded_by: Optional[str] = _TITLE
    finding_id: Optional[str] = _ID
    evidence_ids: Optional[list[str]] = Field(default=None, max_length=100)


class LinkRef(_Body):
    kind: Literal[tuple(ws.EVENT_LINK_KINDS)]  # type: ignore[valid-type]
    id: str = Field(max_length=32)


class EventBody(_Body):
    title: Optional[str] = _TITLE
    description: Optional[str] = _TEXT
    category: Optional[Literal[ws.EVENT_CATEGORIES]] = None  # type: ignore[valid-type]
    provenance: Optional[Literal[ws.EVENT_PROVENANCE]] = None  # type: ignore[valid-type]
    date_precision: Optional[Literal[ws.DATE_PRECISIONS]] = None  # type: ignore[valid-type]
    start_date: Optional[str] = Field(default=None, max_length=10)
    start_time: Optional[str] = Field(default=None, max_length=5)
    end_date: Optional[str] = Field(default=None, max_length=10)
    end_time: Optional[str] = Field(default=None, max_length=5)
    timezone: Optional[str] = Field(default=None, max_length=64)
    notes: Optional[str] = _TEXT
    links: Optional[list[LinkRef]] = Field(default=None, max_length=ws.MAX_LINKS)


class CorrelationBody(_Body):
    title: Optional[str] = _TITLE
    explanation: Optional[str] = _TEXT
    status: Optional[Literal[ws.CORRELATION_STATUSES]] = None  # type: ignore[valid-type]
    confidence: Optional[Literal[ws.CONFIDENCE_LEVELS]] = None  # type: ignore[valid-type]
    event_ids: Optional[list[str]] = Field(default=None, max_length=ws.MAX_LINKS)
    evidence_ids: Optional[list[str]] = Field(default=None, max_length=ws.MAX_LINKS)
    finding_id: Optional[str] = _ID
    notes: Optional[str] = _TEXT
    recorded_by: Optional[str] = _TITLE


class PositionBody(_Body):
    x: float
    y: float


_SECTION_BODIES: dict[str, type[_Body]] = {
    "targets": TargetBody,
    "sources": SourceBody,
    "findings": FindingBody,
    "notes": NoteBody,
    "evidence": EvidenceBody,
    "entities": EntityBody,
    "relationships": RelationshipBody,
    "events": EventBody,
    "correlations": CorrelationBody,
}


def register_workspace_routes(
    app: FastAPI,
    web_dir: Path,
    request_restriction: Callable[[Request], tuple[bool, str]],
    db_path: Callable[[], Path] = ws.default_db_path,
) -> None:
    """Add the workspace page and API to *app*. ``db_path`` is read per request."""

    def _check(request: Request) -> None:
        restricted, reason = request_restriction(request)
        if restricted:
            raise HTTPException(
                403,
                "The research workspace is only available on a local, unrestricted instance "
                f"({reason}).",
            )

    async def _run(fn: Callable[[WorkspaceStore], object]) -> object:
        def work() -> object:
            with WorkspaceStore(db_path()) as store:
                return fn(store)

        try:
            return await asyncio.to_thread(work)
        except WorkspaceError as exc:
            raise HTTPException(exc.status, str(exc)) from None

    @app.get("/workspace", include_in_schema=False)
    async def workspace_page():
        page = web_dir / "workspace.html"
        if page.exists():
            return HTMLResponse(page.read_text(encoding="utf-8"))
        return HTMLResponse("<h1>workspace.html not found</h1>", status_code=404)

    @app.get("/api/investigations")
    async def list_investigations(request: Request):
        _check(request)
        return {"investigations": await _run(lambda s: s.list_investigations())}

    @app.post("/api/investigations", status_code=201)
    async def create_investigation(request: Request, body: InvestigationCreate):
        _check(request)
        return await _run(lambda s: s.create_investigation(body.title, body.description))

    @app.get("/api/investigations/{inv_id}")
    async def get_investigation(request: Request, inv_id: str):
        _check(request)
        return await _run(lambda s: s.get_workspace(inv_id))

    @app.patch("/api/investigations/{inv_id}")
    async def update_investigation(request: Request, inv_id: str, body: InvestigationUpdate):
        _check(request)
        fields = body.model_dump(exclude_unset=True)
        return await _run(lambda s: s.update_investigation(inv_id, fields))

    @app.delete("/api/investigations/{inv_id}")
    async def delete_investigation(request: Request, inv_id: str):
        _check(request)
        await _run(lambda s: s.delete_investigation(inv_id))
        return {"status": "deleted", "id": inv_id}

    @app.get("/api/investigations/{inv_id}/sources/{item_id}/trace")
    async def trace_source(request: Request, inv_id: str, item_id: str):
        _check(request)
        return await _run(lambda s: s.trace_source(inv_id, item_id))

    @app.get("/api/investigations/{inv_id}/findings/{item_id}/trace")
    async def trace_finding(request: Request, inv_id: str, item_id: str):
        _check(request)
        return await _run(lambda s: s.trace_finding(inv_id, item_id))

    @app.get("/api/investigations/{inv_id}/report")
    async def investigation_report(
        request: Request,
        inv_id: str,
        format: str = "html",
        sections: Optional[str] = None,
        title: Optional[str] = None,
        subtitle: Optional[str] = None,
        download: bool = False,
    ):
        """An HTML or PDF report built from the investigation's records, locally."""
        _check(request)
        if format not in report.FORMATS:
            raise HTTPException(422, f"format must be one of: {', '.join(report.FORMATS)}")
        try:
            options = report.parse_options(sections, title, subtitle)
        except WorkspaceError as exc:
            raise HTTPException(exc.status, str(exc)) from None
        data = await _run(lambda s: s.get_workspace(inv_id))
        model = report.build_report(data, options)
        name = report.report_filename(model["title"], format)
        headers = {
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "no-referrer",
        }
        if format == "pdf":
            body = await asyncio.to_thread(report.render_pdf, model)
            headers["Content-Disposition"] = f'attachment; filename="{name}"'
            return Response(body, media_type="application/pdf", headers=headers)
        headers["Content-Security-Policy"] = report.CSP
        headers["Content-Disposition"] = (
            f'{"attachment" if download else "inline"}; filename="{name}"'
        )
        return HTMLResponse(report.render_html(model), headers=headers)

    @app.get("/api/investigations/{inv_id}/relationships/{item_id}/trace")
    async def trace_relationship(request: Request, inv_id: str, item_id: str):
        _check(request)
        return await _run(lambda s: s.trace_relationship(inv_id, item_id))

    @app.put("/api/investigations/{inv_id}/entities/{item_id}/position")
    async def set_entity_position(request: Request, inv_id: str, item_id: str, body: PositionBody):
        _check(request)
        return await _run(lambda s: s.set_entity_position(inv_id, item_id, body.x, body.y))

    for section, model in _SECTION_BODIES.items():
        _add_section_routes(app, section, model, _check, _run)


def _add_section_routes(app, section, model, check, run) -> None:
    async def create_item(request: Request, inv_id: str, body: model):  # type: ignore[valid-type]
        check(request)
        data = body.model_dump(exclude_unset=True)
        return await run(lambda s: s.add_item(inv_id, section, data))

    async def update_item(request: Request, inv_id: str, item_id: str, body: model):  # type: ignore[valid-type]
        check(request)
        data = body.model_dump(exclude_unset=True)
        return await run(lambda s: s.update_item(inv_id, section, item_id, data))

    async def delete_item(request: Request, inv_id: str, item_id: str):
        check(request)
        await run(lambda s: s.delete_item(inv_id, section, item_id))
        return {"status": "deleted", "id": item_id}

    base = f"/api/investigations/{{inv_id}}/{section}"
    app.add_api_route(base, create_item, methods=["POST"], status_code=201, name=f"add_{section}")
    app.add_api_route(base + "/{item_id}", update_item, methods=["PATCH"], name=f"update_{section}")
    app.add_api_route(
        base + "/{item_id}", delete_item, methods=["DELETE"], name=f"delete_{section}"
    )
