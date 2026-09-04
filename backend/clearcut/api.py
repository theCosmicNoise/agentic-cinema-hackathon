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

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from clearcut.core.buckets import taxonomy
from clearcut.core.config import get_settings
from clearcut.core.ledger import ClearanceLedger
import re
import uuid

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


@app.middleware("http")
async def no_store_frontend(request, call_next):
    """Never let a browser serve a stale UI.

    The frontend is a handful of small files and the cost of re-fetching them
    is nil, whereas a cached stylesheet silently showing an old build during a
    live demo is expensive.
    """
    response = await call_next(request)
    path = request.url.path
    if path == "/" or path.endswith((".css", ".js", ".html")):
        response.headers["Cache-Control"] = "no-store, must-revalidate"
    return response


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
                "sample": True,
            }
        )
    for m in sorted(upload_dir().glob("*.meta.json")):
        try:
            d = json.loads(m.read_text())
        except Exception:  # noqa: BLE001, S112
            continue
        out.append(
            {
                "id": d["id"],
                "title": d.get("title") or d.get("original_name"),
                "author": d.get("author"),
                "draft": d.get("draft_label"),
                "date": d.get("draft_date"),
                "pages": d.get("page_count", 0),
                "original_name": d.get("original_name"),
                "sample": False,
            }
        )
    return out


UPLOAD_DIR = None  # resolved lazily under the data dir


def upload_dir() -> Path:
    d = Path(get_settings().data_dir) / "uploads"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _screenplay_path(sid: str) -> Path | None:
    """A screenplay id resolves either to a bundled sample or an upload."""
    for base, suffixes in ((SCREENPLAY_DIR, (".txt",)), (upload_dir(), (".txt", ".pdf", ".fountain"))):
        for suf in suffixes:
            p = base / f"{sid}{suf}"
            if p.exists():
                return p
    return None


@app.post("/api/upload")
async def upload(file: UploadFile = File(...)) -> dict:
    """Accept a real screenplay — Final Draft PDF export, Fountain, or plain text."""
    name = Path(file.filename or "script").name
    suffix = Path(name).suffix.lower()
    if suffix not in {".pdf", ".txt", ".fountain"}:
        raise HTTPException(400, "Upload a PDF, .fountain or .txt screenplay.")

    raw = await file.read()
    if len(raw) > 25 * 1024 * 1024:
        raise HTTPException(413, "Screenplay exceeds the 25 MB limit.")

    sid = f"up_{uuid.uuid4().hex[:8]}"
    dest = upload_dir() / f"{sid}{suffix}"
    dest.write_bytes(raw)

    try:
        meta = parse_screenplay(load_screenplay(dest)).meta
    except Exception as exc:  # noqa: BLE001
        dest.unlink(missing_ok=True)
        raise HTTPException(422, f"Could not read that screenplay: {exc}") from exc

    if meta.page_count < 1:
        dest.unlink(missing_ok=True)
        raise HTTPException(422, "That file contains no readable screenplay text.")

    (upload_dir() / f"{sid}.meta.json").write_text(
        json.dumps({"id": sid, "original_name": name, **json.loads(meta.model_dump_json())})
    )
    return {
        "id": sid,
        "original_name": name,
        "title": meta.title,
        "author": meta.author,
        "draft": meta.draft_label,
        "date": meta.draft_date,
        "pages": meta.page_count,
        "uploaded": True,
    }


@app.delete("/api/screenplays/{screenplay_id}")
def delete_screenplay(screenplay_id: str) -> dict:
    """Remove an uploaded screenplay and its metadata.

    Only uploads are removable. The bundled samples are read-only fixtures, and
    the clearance ledger is deliberately left intact — it is the production's
    record of what was cleared, and it outlives any single file.
    """
    if not screenplay_id.startswith("up_"):
        raise HTTPException(
            403, "Only uploaded screenplays can be removed; samples are read-only."
        )
    if "/" in screenplay_id or "\\" in screenplay_id or ".." in screenplay_id:
        raise HTTPException(400, "Invalid screenplay id.")

    removed = []
    for f in list(upload_dir().glob(f"{screenplay_id}.*")):
        if f.is_file():
            f.unlink()
            removed.append(f.name)
    if not removed:
        raise HTTPException(404, f"No uploaded screenplay '{screenplay_id}'")

    # Sessions referencing it are orphaned; drop them so the UI cannot offer a
    # run that could never start.
    dropped = 0
    sess_dir = Path(get_settings().data_dir) / "sessions"
    if sess_dir.exists():
        for sf in sess_dir.glob("*.json"):
            try:
                if f'"screenplay_id": "{screenplay_id}"' in sf.read_text():
                    sf.unlink()
                    dropped += 1
            except OSError:
                continue

    return {"removed": removed, "sessions_dropped": dropped}


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


@app.get("/api/buckets")
def buckets() -> list[dict]:
    """How the review groups items — by who has to act on them."""
    return taxonomy()


@app.post("/api/sessions")
def new_session(req: NewSession) -> dict:
    path = _screenplay_path(req.screenplay)
    if path is None:
        raise HTTPException(404, f"No screenplay '{req.screenplay}'")
    project = req.project_id or re.sub(r"_v\d+$", "", req.screenplay)
    s = create_session(path, project)
    store().put(s)
    return json.loads(s.model_dump_json())


@app.get("/api/sessions")
def list_sessions() -> list[dict]:
    return store().list()


@app.delete("/api/sessions/{sid}")
def drop_session(sid: str) -> dict:
    """Discard a run. The clearance ledger is untouched — it is the production's
    record of what was cleared and outlives any single review."""
    if not store().delete(sid):
        raise HTTPException(404, "no such session")
    return {"deleted": sid}


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

    path = _screenplay_path(s.screenplay_id)
    if path is None:
        raise HTTPException(410, "The screenplay for this session is no longer available.")
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
