"""Module 9: credit decision API (FastAPI).

  POST /api/score                  score 1-1,000 applications -> decision, PD, risk band, reasons
  GET  /api/applications/sample    random real 2015 applications to try it with
  GET  /api/stress?d_unemp=2.5     book loss rate under an unemployment shock
  GET  /api/dashboard              headline results of every module
  GET  /api/meta                   model version, input fields, scenarios
  GET  /api/health                 liveness
  GET  /metrics                    Prometheus metrics
  GET  /docs                       interactive API docs
  GET  /                           the React dashboard (when dashboard/dist exists)

Run:
    python -m api.export                      # once, after Modules 2-8
    uvicorn api.main:app --port 8000
"""

from __future__ import annotations

import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal, Optional

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, create_model

from models import features as F

DIST = Path(__file__).resolve().parents[1] / "dashboard" / "dist"

# Input schema: the 34 model inputs (all optional; missing -> treated as missing by the model) plus grade,
# which the approval policy needs. Unknown fields are rejected, so e.g. addr_state cannot be sent.
Application = create_model(
    "Application",
    __config__=ConfigDict(extra="forbid"),
    loan_id=(Optional[str], None),
    grade=(Literal[tuple("ABCDEFG")], ...),
    **{c: (Optional[float], None) for c in F.NUMERIC},
    **{c: (Optional[str], None) for c in F.CATEGORICAL},
)


class ScoreRequest(BaseModel):
    applications: list[Application] = Field(min_length=1, max_length=1000)  # type: ignore[valid-type]


class Reason(BaseModel):
    feature: str
    text: str


class Decision(BaseModel):
    loan_id: str
    decision: Literal["approve", "decline"]
    pd: float
    pd_baseline: float
    risk_band: int
    grade: str
    pd_by_scenario: dict[str, float]
    reasons: list[Reason]
    missing_fields: int


class ScoreResponse(BaseModel):
    model_version: str
    decisions: list[Decision]
    latency_ms: float


# Prometheus metrics (module level, so creating several apps in tests does not re-register them)
try:
    from prometheus_client import Counter, Histogram, make_asgi_app

    REQUESTS = Counter("api_requests_total", "API requests", ["path", "status"])
    LATENCY = Histogram("api_request_seconds", "API request latency", ["path"],
                        buckets=(0.001, 0.0025, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 1.0))
    DECISIONS = Counter("api_decisions_total", "Credit decisions", ["decision"])
except ImportError:  # metrics are optional
    make_asgi_app = None


def create_app(platform=None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if platform is None:
            from api.service import Platform

            app.state.platform = Platform()
        else:
            app.state.platform = platform
        yield

    app = FastAPI(title="Consumer Credit Risk Decision API", version="1.0", lifespan=lifespan,
                  description="PD model, macro stress overlay and optimized approval policy behind one endpoint.")
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["GET", "POST"], allow_headers=["*"])

    @app.middleware("http")
    async def timing(request: Request, call_next):
        t0 = time.perf_counter()
        response = await call_next(request)
        secs = time.perf_counter() - t0
        response.headers["X-Process-Time-Ms"] = f"{secs * 1000:.2f}"
        path = request.url.path
        if make_asgi_app and path.startswith("/api/"):
            REQUESTS.labels(path=path, status=response.status_code).inc()
            LATENCY.labels(path=path).observe(secs)
        return response

    def P(request: Request):
        return request.app.state.platform

    @app.get("/api/health")
    def health(request: Request):
        return {"status": "ok", "model_version": P(request).version}

    @app.get("/api/meta")
    def meta(request: Request):
        return P(request).meta()

    @app.post("/api/score", response_model=ScoreResponse)
    def score(req: ScoreRequest, request: Request):           # sync: runs in a worker thread
        t0 = time.perf_counter()
        decisions = P(request).score([a.model_dump() for a in req.applications])
        if make_asgi_app:
            for d in decisions:
                DECISIONS.labels(decision=d["decision"]).inc()
        return {"model_version": P(request).version, "decisions": decisions,
                "latency_ms": (time.perf_counter() - t0) * 1000}

    @app.get("/api/applications/sample")
    def sample(request: Request, n: int = Query(1, ge=1, le=100), seed: Optional[int] = None):
        return P(request).sample(n, seed)

    @app.get("/api/stress")
    def stress(request: Request, d_unemp: float = Query(..., description="unemployment change, pp")):
        try:
            return P(request).stress(d_unemp)
        except ValueError as e:
            raise HTTPException(422, str(e)) from e

    @app.get("/api/stress/grid")
    def stress_grid(request: Request):
        return P(request).grid

    @app.get("/api/dashboard")
    def dashboard(request: Request):
        return P(request).dashboard

    if make_asgi_app:
        app.mount("/metrics", make_asgi_app())
    if DIST.exists():                                          # built React dashboard
        app.mount("/", StaticFiles(directory=DIST, html=True), name="dashboard")
    return app


app = create_app()
