"""Prior Art — FastAPI app. One process, no other services.

    uvicorn server:app --reload
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from schema import ROOT

load_dotenv()

WEB = ROOT / "web"
FINDINGS_PATH = ROOT / "data" / "findings.json"

SENTRY_DSN = os.getenv("SENTRY_DSN", "").strip()
if SENTRY_DSN:
    import sentry_sdk
    from sentry_sdk.integrations.fastapi import FastApiIntegration
    from sentry_sdk.integrations.starlette import StarletteIntegration

    sentry_sdk.init(
        dsn=SENTRY_DSN,
        traces_sample_rate=1.0,
        profiles_sample_rate=1.0,
        send_default_pii=False,
        integrations=[StarletteIntegration(), FastApiIntegration()],
    )

app = FastAPI(title="Prior Art", version="0.1.1", docs_url=None, redoc_url=None)
_map_cache: dict | None = None


class AskBody(BaseModel):
    text: str = Field(min_length=1, max_length=8000)


@app.on_event("startup")
def _startup() -> None:
    from engine import engine

    engine.load()
    global _map_cache
    _map_cache = engine.map_data


@app.get("/")
def index() -> FileResponse:
    return FileResponse(WEB / "index.html")


@app.get("/api/config")
def config() -> dict:
    from engine import engine

    return {
        "sentry_dsn": os.getenv("SENTRY_FRONTEND_DSN", "").strip(),
        "source": Path(engine.source).name,
        "n": len(engine.projects),
        "n_finalists": sum(1 for p in engine.projects if p.finalist),
    }


@app.get("/api/map")
def api_map() -> JSONResponse:
    from engine import engine

    payload = _map_cache if _map_cache is not None else engine.map_data
    return JSONResponse(payload)


@app.get("/api/findings")
def api_findings() -> JSONResponse:
    if not FINDINGS_PATH.exists():
        return JSONResponse({"charts": []})
    return JSONResponse(json.loads(FINDINGS_PATH.read_text(encoding="utf-8")))


@app.post("/api/ask")
def api_ask(body: AskBody) -> dict:
    from engine import engine

    text = body.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="text is empty")
    try:
        return engine.ask(text)
    except Exception as exc:
        # Last-ditch: never 500 in front of a judge if neighbours can still run.
        try:
            pairs, xy = engine._tfidf_neighbours(text)
            n_f = sum(1 for p in engine.projects if p.finalist)
            n = max(1, len(engine.projects))
            return {
                "point": {"x": float(xy[0]), "y": float(xy[1])},
                "neighbours": engine.neighbour_records(pairs),
                "probability": round(n_f / n, 4),
                "model": {
                    "auc": None,
                    "auc_spread": [],
                    "n_train": n,
                    "n_finalists": n_f,
                },
                "backend": "tfidf",
                "degraded": True,
            }
        except Exception:
            raise HTTPException(status_code=500, detail=str(exc)) from exc


app.mount("/web", StaticFiles(directory=WEB), name="web")
