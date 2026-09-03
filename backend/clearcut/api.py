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
from clearcut.core.models import AgentEvent
from clearcut.core.screenplay import load_screenplay, parse_screenplay
from clearcut.pipeline import run_clearance

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
