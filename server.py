"""Prior Art — FastAPI app. One process, no other services.

    uvicorn server:app --reload
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

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
        enable_tracing=True,
        send_default_pii=False,
        integrations=[StarletteIntegration(), FastApiIntegration()],
    )

app = FastAPI(title="Prior Art", version="0.1.1", docs_url=None, redoc_url=None)
_map_cache: dict | None = None


def _clean_text(value: str) -> str:
    return (value or "").replace("\x00", "")


class AskBody(BaseModel):
    text: str = Field(default="", max_length=8000)
    github: str = Field(default="", max_length=400)
    devpost: str = Field(default="", max_length=400)

    @field_validator("text", "github", "devpost", mode="before")
    @classmethod
    def _nuls(cls, v):
        if v is None:
            return ""
        if not isinstance(v, str):
            return v
        return _clean_text(v)


class CoachBody(BaseModel):
    text: str = Field(default="", max_length=8000)
    time_budget_hours: float | None = Field(default=None, ge=0, le=168)

    @field_validator("text", mode="before")
    @classmethod
    def _nuls(cls, v):
        if v is None:
            return ""
        if not isinstance(v, str):
            return v
        return _clean_text(v)


@app.exception_handler(RequestValidationError)
def _validation(_request: Request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse({"detail": exc.errors()}, status_code=422)


@app.exception_handler(Exception)
def _uncaught(_request: Request, exc: Exception) -> JSONResponse:
    if isinstance(exc, HTTPException):
        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
    print(f"uncaught ({type(exc).__name__}: {exc})")
    return JSONResponse({"detail": "request failed"}, status_code=500)


@app.on_event("startup")
def _startup() -> None:
    from engine import engine, json_safe

    engine.load()
    global _map_cache
    _map_cache = json_safe(engine.map_data)


@app.get("/")
def index() -> FileResponse:
    return FileResponse(WEB / "index.html")


@app.get("/api/config")
def config() -> JSONResponse:
    from engine import engine, json_safe

    n_emb = 0 if engine.embeddings is None else int(engine.embeddings.shape[0])
    payload = {
        "sentry_dsn": os.getenv("SENTRY_FRONTEND_DSN", "").strip(),
        "source": Path(engine.source).name,
        "n": len(engine.projects),
        "n_finalists": sum(1 for p in engine.projects if p.finalist),
        "n_map": len((engine.map_data or {}).get("points") or []),
        "n_embeddings": n_emb,
    }
    return JSONResponse(json_safe(payload))


@app.get("/api/map")
def api_map() -> JSONResponse:
    from engine import engine, json_safe

    payload = _map_cache if _map_cache is not None else engine.map_data
    return JSONResponse(json_safe(payload))


@app.get("/api/findings")
def api_findings() -> JSONResponse:
    from engine import json_safe

    if not FINDINGS_PATH.exists():
        return JSONResponse({"charts": []})
    try:
        return JSONResponse(json_safe(json.loads(FINDINGS_PATH.read_text(encoding="utf-8"))))
    except Exception:
        return JSONResponse({"charts": []})


@app.post("/api/ask")
def api_ask(body: AskBody) -> JSONResponse:
    from engine import engine, json_safe

    text = body.text.strip()
    github = body.github.strip()
    devpost = body.devpost.strip()
    if not text and not github:
        raise HTTPException(status_code=400, detail="provide a description or a GitHub URL")
    try:
        return JSONResponse(json_safe(engine.ask(text, github=github, devpost=devpost)))
    except Exception as exc:
        try:
            pairs, xy = engine._tfidf_neighbours(text or "project")
            n_f = sum(1 for p in engine.projects if p.finalist)
            n = max(1, len(engine.projects))
            return JSONResponse(
                json_safe(
                    {
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
                        "source": "tfidf",
                        "degraded": True,
                    }
                )
            )
        except Exception:
            print(f"ask failed ({exc})")
            return JSONResponse(
                json_safe(
                    {
                        "point": {"x": 0.0, "y": 0.0},
                        "neighbours": [],
                        "probability": 0.0,
                        "model": {"auc": None, "auc_spread": [], "n_train": 0, "n_finalists": 0},
                        "backend": "tfidf",
                        "source": "tfidf",
                        "degraded": True,
                    }
                )
            )


@app.post("/api/coach")
def api_coach(body: CoachBody) -> JSONResponse:
    from engine import engine, hours_until_build_end, json_safe

    text = body.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="provide a description")
    try:
        return JSONResponse(json_safe(engine.coach(text, time_budget_hours=body.time_budget_hours)))
    except Exception as exc:
        print(f"coach failed ({exc})")
        remaining = hours_until_build_end()
        budget = remaining if body.time_budget_hours is None else float(body.time_budget_hours)
        return JSONResponse(
            json_safe(
                {
                    "baseline": 0.0,
                    "moves": [],
                    "hours_remaining": remaining,
                    "time_budget_hours": round(max(0.0, budget), 2),
                }
            )
        )


app.mount("/web", StaticFiles(directory=WEB), name="web")
