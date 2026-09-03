"""
HTTP layer.

One long-lived endpoint matters here: /api/clear streams agent events over
Server-Sent Events as the run happens. A clearance pass takes minutes, and the
whole point of an agent network is that you can watch it reason — a spinner
would throw away the most interesting thing the product does.

Static files are served from this same app so the deployment is a single
container with no separate frontend build.
"""

from __future__ import annotations

import asyncio
import json
import logging
import queue
import threading
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from clearcut.core.config import get_settings
from clearcut.core.ledger import ClearanceLedger
import re

from clearcut.core.models import AgentEvent, Verdict
from clearcut.core.screenplay import load_screenplay, parse_screenplay
from clearcut.pipeline import run_clearance
from clearcut.session import (
    STAGE_BLURB,
    STAGE_GATE,
    STAGE_ORDER,
    ItemDecision,
    SessionStore,
    Stage,
    create_session,
    run_stage,
)

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[2]
SCREENPLAY_DIR = REPO_ROOT / "assets" / "screenplays"
FRONTEND_DIR = REPO_ROOT / "frontend"

app = FastAPI(title="CLEARCUT", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


_store: SessionStore | None = None


def store() -> SessionStore:
    global _store
    if _store is None:
        _store = SessionStore(get_settings().data_dir)
    return _store


class NewSession(BaseModel):
    screenplay: str
    project_id: str | None = None


class Decision(BaseModel):
    dismissed: bool | None = None
    verdict_override: str | None = None
    note: str | None = None
    substitution_accepted: bool | None = None


class ClearRequest(BaseModel):
    screenplay: str
    project_id: str = "demo"
    deep_verify: bool = False
    substitute: bool = True
    use_ledger: bool = True


@app.get("/api/health")
def health() -> dict:
    s = get_settings()
    return {
        "ok": True,
        "gemini_configured": bool(s.google_api_key or s.google_cloud_project),
        "parallel_configured": bool(s.parallel_api_key),
    }


@app.get("/api/screenplays")
def screenplays() -> list[dict]:
    """The drafts available to clear, newest revision colour last."""
    out = []
    for p in sorted(SCREENPLAY_DIR.glob("*.txt")):
        try:
            meta = parse_screenplay(load_screenplay(p)).meta
        except Exception:  # noqa: BLE001, S112
            continue
        out.append(
            {
                "id": p.stem,
                "title": meta.title,
                "author": meta.author,
                "draft": meta.draft_label,
                "date": meta.draft_date,
                "pages": meta.page_count,
            }
        )
    return out


@app.get("/api/ledger/{project_id}")
def ledger(project_id: str) -> dict:
    led = ClearanceLedger(project_id, get_settings().data_dir)
    return {
        "project_id": project_id,
        "entries": len(led.entries),
        "history": led.history,
        "items": [
            {
                "value": e.value,
                "category": e.category.value,
                "verdict": e.verdict.value,
                "first_cleared_draft": e.first_cleared_draft,
                "last_verified_draft": e.last_verified_draft,
            }
            for e in led.entries.values()
        ],
    }


# --------------------------------------------------------------------------- #
# Stage-gated sessions — the reviewed workflow
# --------------------------------------------------------------------------- #
@app.get("/api/stages")
def stages() -> list[dict]:
    return [
        {"id": s.value, "name": s.value.title(), "does": STAGE_BLURB[s], "gate": STAGE_GATE[s]}
        for s in STAGE_ORDER
    ]


@app.post("/api/sessions")
def new_session(req: NewSession) -> dict:
    path = SCREENPLAY_DIR / f"{req.screenplay}.txt"
    if not path.exists():
        raise HTTPException(404, f"No screenplay '{req.screenplay}'")
    project = req.project_id or re.sub(r"_v\d+$", "", req.screenplay)
    s = create_session(path, project)
    store().put(s)
    return json.loads(s.model_dump_json())


@app.get("/api/sessions")
def list_sessions() -> list[dict]:
    return store().list()


@app.get("/api/sessions/{sid}")
def get_session(sid: str) -> dict:
    s = store().get(sid)
    if not s:
        raise HTTPException(404, "no such session")
    return json.loads(s.model_dump_json())


@app.post("/api/sessions/{sid}/stage/{stage_id}")
async def advance(sid: str, stage_id: str, deep: bool = False) -> StreamingResponse:
    """Run one stage, streaming its events. The stage then awaits review."""
    s = store().get(sid)
    if not s:
        raise HTTPException(404, "no such session")
    try:
        stage = Stage(stage_id)
    except ValueError:
        raise HTTPException(400, f"unknown stage '{stage_id}'") from None
    if not s.can_run(stage):
        raise HTTPException(
            409, f"stage '{stage_id}' is not unlocked — approve the previous stage first"
        )

    path = SCREENPLAY_DIR / f"{s.screenplay_id}.txt"
    events: queue.Queue = queue.Queue()
    SENTINEL = object()

    def work() -> None:
        try:
            run_stage(s, stage, path, events.put, deep_verify=deep)
            s.events.extend([])  # events are streamed, not replayed
            store().put(s)
        finally:
            events.put(SENTINEL)

    threading.Thread(target=work, daemon=True).start()

    async def stream():
        loop = asyncio.get_running_loop()
        while True:
            item = await loop.run_in_executor(None, events.get)
            if item is SENTINEL:
                break
            if isinstance(item, AgentEvent):
                yield f"data: {json.dumps({'type':'event','data':json.loads(item.model_dump_json())})}\n\n"
        fresh = store().get(sid)
        yield f"data: {json.dumps({'type':'stage_done','data':json.loads(fresh.model_dump_json())})}\n\n"

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/sessions/{sid}/approve/{stage_id}")
def approve(sid: str, stage_id: str) -> dict:
    """The human gate. Nothing downstream runs until this is called."""
    s = store().get(sid)
    if not s:
        raise HTTPException(404, "no such session")
    try:
        stage = Stage(stage_id)
    except ValueError:
        raise HTTPException(400, "unknown stage") from None
    st = s.stage(stage)
    if st.status not in ("awaiting_review", "approved"):
        raise HTTPException(409, f"stage is '{st.status}', not awaiting review")
    st.status = "approved"
    st.approved_at = __import__("datetime").datetime.now(
        __import__("datetime").timezone.utc
    )
    store().put(s)
    return json.loads(s.model_dump_json())


@app.post("/api/sessions/{sid}/items/{item_id}")
def decide(sid: str, item_id: str, d: Decision) -> dict:
    """Record a reviewer decision. Overrides the machine."""
    s = store().get(sid)
    if not s:
        raise HTTPException(404, "no such session")
    if not any(i.id == item_id for i in s.items):
        raise HTTPException(404, "no such item")

    cur = s.decisions.get(item_id) or ItemDecision()
    if d.dismissed is not None:
        cur.dismissed = d.dismissed
    if d.note is not None:
        cur.note = d.note
    if d.substitution_accepted is not None:
        cur.substitution_accepted = d.substitution_accepted
    if d.verdict_override is not None:
        cur.verdict_override = None if d.verdict_override == "" else Verdict(d.verdict_override)
    cur.decided_at = __import__("datetime").datetime.now(
        __import__("datetime").timezone.utc
    )
    s.decisions[item_id] = cur
    store().put(s)
    return json.loads(s.model_dump_json())


@app.get("/api/sessions/{sid}/report.pdf")
def session_pdf(sid: str) -> FileResponse:
    s = store().get(sid)
    if not s or not s.pdf_path or not Path(s.pdf_path).exists():
        raise HTTPException(404, "no report generated yet")
    return FileResponse(s.pdf_path, media_type="application/pdf",
                        filename=f"{s.report_id}.pdf")


@app.post("/api/clear")
async def clear(req: ClearRequest) -> StreamingResponse:
    """Run a clearance pass, streaming every agent event as it happens."""
    path = SCREENPLAY_DIR / f"{req.screenplay}.txt"
    if not path.exists():
        raise HTTPException(404, f"No screenplay '{req.screenplay}'")

    events: queue.Queue = queue.Queue()
    SENTINEL = object()

    def emit(e: AgentEvent) -> None:
        events.put(e)

    def work() -> None:
        try:
            report = run_clearance(
                path,
                project_id=req.project_id,
                emit=emit,
                deep_verify=req.deep_verify,
                substitute=req.substitute,
                use_ledger=req.use_ledger,
            )
            events.put(("report", report))
        except Exception as exc:  # noqa: BLE001
            logger.exception("clearance run failed")
            events.put(("error", str(exc)))
        finally:
            events.put(SENTINEL)

    threading.Thread(target=work, daemon=True).start()

    async def stream():
        loop = asyncio.get_running_loop()
        while True:
            item = await loop.run_in_executor(None, events.get)
            if item is SENTINEL:
                break
            if isinstance(item, AgentEvent):
                payload = {"type": "event", "data": json.loads(item.model_dump_json())}
            elif isinstance(item, tuple) and item[0] == "report":
                payload = {
                    "type": "report",
                    "data": json.loads(item[1].model_dump_json()),
                }
            else:
                payload = {"type": "error", "data": {"message": item[1]}}
            yield f"data: {json.dumps(payload)}\n\n"

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# Frontend last, so /api routes win.
if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="ui")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(str(FRONTEND_DIR / "index.html"))
