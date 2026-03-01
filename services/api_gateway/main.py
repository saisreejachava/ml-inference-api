import asyncio
import time
import uuid
from collections import Counter, deque
from datetime import datetime, timezone

import httpx
import structlog
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

logger = structlog.get_logger()
limiter = Limiter(key_func=get_remote_address)

app = FastAPI(title="Risk Intelligence API Gateway", version="2.1.0")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

INFERENCE_SERVICE_URL = "http://inference-service:8001"
TIMEOUT_SECONDS = 10.0
MAX_EVENT_BUFFER = 300

recent_events: deque[dict] = deque(maxlen=MAX_EVENT_BUFFER)
emitted_async_jobs: set[str] = set()


class ConnectionManager:
    def __init__(self):
        self.active_connections: set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        async with self._lock:
            self.active_connections.add(websocket)

    async def disconnect(self, websocket: WebSocket):
        async with self._lock:
            if websocket in self.active_connections:
                self.active_connections.remove(websocket)

    async def broadcast_json(self, payload: dict):
        stale: list[WebSocket] = []
        async with self._lock:
            sockets = list(self.active_connections)
        for socket in sockets:
            try:
                await socket.send_json(payload)
            except Exception:
                stale.append(socket)
        if stale:
            async with self._lock:
                for socket in stale:
                    self.active_connections.discard(socket)


ws_manager = ConnectionManager()


class PredictRequest(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    text: str
    mode: str = "sync"
    model_version: str = "v1"


class PredictResponse(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    request_id: str
    prediction: str
    confidence: float
    model_version: str
    latency_ms: float
    cached: bool


class RiskScoreRequest(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    user_id: str
    event_type: str = "transaction"
    transaction_amount: float = Field(ge=0)
    transaction_country: str
    home_country: str = "US"
    is_new_device: bool = False
    failed_login_attempts: int = Field(default=0, ge=0)
    account_age_days: int = Field(default=365, ge=0)
    credit_score: int = Field(default=700, ge=300, le=850)
    debt_to_income: float = Field(default=0.3, ge=0, le=2)
    chargeback_count_90d: int = Field(default=0, ge=0)
    ip_reputation: float = Field(default=0.1, ge=0, le=1)
    mode: str = "sync"
    model_version: str = "v1"


class RiskComponents(BaseModel):
    fraud_probability: float
    credit_default_probability: float
    cyber_anomaly_probability: float


class RiskScoreResponse(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    request_id: str
    user_id: str
    model_version: str
    risk_score: float
    decision: str
    confidence: float
    components: RiskComponents
    factors: list[str]
    latency_ms: float
    cached: bool


class AnalyticsResponse(BaseModel):
    total_events: int
    allow_count: int
    review_count: int
    block_count: int
    avg_risk_score: float
    top_factors: list[str]


@app.middleware("http")
async def add_request_id(request: Request, call_next):
    request_id = str(uuid.uuid4())
    request.state.request_id = request_id
    start = time.time()
    response = await call_next(request)
    duration = (time.time() - start) * 1000
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Response-Time-ms"] = str(round(duration, 2))
    logger.info(
        "request_handled",
        request_id=request_id,
        path=request.url.path,
        duration_ms=round(duration, 2),
        status=response.status_code,
    )
    return response


@app.get("/health")
async def health():
    return {"status": "ok", "service": "api-gateway"}


def build_event_record(body: RiskScoreRequest, scored: dict) -> dict:
    return {
        "id": str(uuid.uuid4()),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "user_id": body.user_id,
        "event_type": body.event_type,
        "decision": scored["decision"],
        "risk_score": scored["risk_score"],
        "transaction_amount": body.transaction_amount,
        "country": body.transaction_country,
        "factors": scored["factors"],
        "components": scored["components"],
    }


async def record_and_broadcast_event(event: dict):
    recent_events.appendleft(event)
    await ws_manager.broadcast_json({"type": "risk_event", "event": event})


@app.get("/events/recent")
async def get_recent_events(limit: int = 50):
    clipped_limit = max(1, min(limit, 200))
    return {"events": list(recent_events)[:clipped_limit]}


@app.get("/analytics", response_model=AnalyticsResponse)
async def get_analytics():
    events = list(recent_events)
    if not events:
        return {
            "total_events": 0,
            "allow_count": 0,
            "review_count": 0,
            "block_count": 0,
            "avg_risk_score": 0.0,
            "top_factors": [],
        }

    decision_counter = Counter(event["decision"] for event in events)
    factor_counter: Counter = Counter()
    for event in events:
        factor_counter.update(event.get("factors", []))

    avg_risk_score = round(sum(event["risk_score"] for event in events) / len(events), 2)
    top_factors = [factor for factor, _ in factor_counter.most_common(5)]

    return {
        "total_events": len(events),
        "allow_count": decision_counter.get("allow", 0),
        "review_count": decision_counter.get("review", 0),
        "block_count": decision_counter.get("block", 0),
        "avg_risk_score": avg_risk_score,
        "top_factors": top_factors,
    }


@app.websocket("/ws/live-events")
async def live_events(websocket: WebSocket):
    await ws_manager.connect(websocket)
    await websocket.send_json({"type": "snapshot", "events": list(recent_events)[:50]})
    try:
        while True:
            # Keep socket alive; incoming payload is ignored for now.
            await websocket.receive_text()
    except WebSocketDisconnect:
        await ws_manager.disconnect(websocket)


@app.post("/predict", response_model=PredictResponse)
@limiter.limit("100/minute")
async def predict(request: Request, body: PredictRequest):
    request_id = request.state.request_id

    if body.mode == "async":
        async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
            try:
                resp = await client.post(
                    f"{INFERENCE_SERVICE_URL}/predict/async",
                    json={**body.model_dump(), "request_id": request_id},
                )
                resp.raise_for_status()
                return JSONResponse(status_code=202, content=resp.json())
            except httpx.TimeoutException:
                raise HTTPException(status_code=504, detail="Inference service timed out")
            except httpx.HTTPStatusError as exc:
                raise HTTPException(status_code=exc.response.status_code, detail="Inference service error")

    async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
        try:
            start = time.time()
            resp = await client.post(
                f"{INFERENCE_SERVICE_URL}/predict",
                json={**body.model_dump(), "request_id": request_id},
            )
            resp.raise_for_status()
            data = resp.json()
            data["latency_ms"] = round((time.time() - start) * 1000, 2)
            return data
        except httpx.TimeoutException:
            raise HTTPException(status_code=504, detail="Inference service timed out")
        except httpx.HTTPStatusError as exc:
            raise HTTPException(status_code=exc.response.status_code, detail="Inference service error")


@app.post("/risk/score", response_model=RiskScoreResponse)
@limiter.limit("120/minute")
async def risk_score(request: Request, body: RiskScoreRequest):
    request_id = request.state.request_id

    if body.mode == "async":
        async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
            try:
                resp = await client.post(
                    f"{INFERENCE_SERVICE_URL}/risk/score/async",
                    json={**body.model_dump(), "request_id": request_id},
                )
                resp.raise_for_status()
                return JSONResponse(status_code=202, content=resp.json())
            except httpx.TimeoutException:
                raise HTTPException(status_code=504, detail="Inference service timed out")
            except httpx.HTTPStatusError as exc:
                raise HTTPException(status_code=exc.response.status_code, detail="Inference service error")

    async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
        try:
            start = time.time()
            resp = await client.post(
                f"{INFERENCE_SERVICE_URL}/risk/score",
                json={**body.model_dump(), "request_id": request_id},
            )
            resp.raise_for_status()
            data = resp.json()
            data["latency_ms"] = round((time.time() - start) * 1000, 2)

            event = build_event_record(body, data)
            await record_and_broadcast_event(event)
            return data
        except httpx.TimeoutException:
            raise HTTPException(status_code=504, detail="Inference service timed out")
        except httpx.HTTPStatusError as exc:
            raise HTTPException(status_code=exc.response.status_code, detail="Inference service error")


@app.get("/result/{job_id}")
async def get_result(job_id: str):
    async with httpx.AsyncClient(timeout=5.0) as client:
        try:
            resp = await client.get(f"{INFERENCE_SERVICE_URL}/result/{job_id}")
            resp.raise_for_status()
            data = resp.json()

            if data.get("job_type") == "risk" and data.get("status") == "complete" and job_id not in emitted_async_jobs:
                emitted_async_jobs.add(job_id)
                event = {
                    "id": str(uuid.uuid4()),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "user_id": data.get("user_id", "unknown"),
                    "event_type": "async-risk",
                    "decision": data.get("decision", "review"),
                    "risk_score": data.get("risk_score", 0.0),
                    "transaction_amount": None,
                    "country": None,
                    "factors": data.get("factors", []),
                    "components": data.get("components", {}),
                }
                await record_and_broadcast_event(event)

            return data
        except httpx.HTTPStatusError as exc:
            raise HTTPException(status_code=exc.response.status_code, detail="Job not found or still processing")
