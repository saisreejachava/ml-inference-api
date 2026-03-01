import asyncio
import hashlib
import json
import os
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager

import redis.asyncio as aioredis
import structlog
from fastapi import BackgroundTasks, FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from model import MockMLModel

logger = structlog.get_logger()

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379")
CACHE_TTL = int(os.getenv("CACHE_TTL", 1800))

model: MockMLModel = None
redis_client: aioredis.Redis = None
executor = ThreadPoolExecutor(max_workers=4)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global model, redis_client
    logger.info("Loading ML model...")
    model = MockMLModel()
    model.load()
    logger.info("Model loaded successfully")

    redis_client = await aioredis.from_url(REDIS_URL, encoding="utf-8", decode_responses=True)
    logger.info("Redis connected")
    yield
    await redis_client.close()
    executor.shutdown(wait=False)


app = FastAPI(title="ML Inference Service", version="2.0.0", lifespan=lifespan)


class PredictRequest(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    text: str
    mode: str = "sync"
    model_version: str = "v1"
    request_id: str = ""


class RiskScoreRequest(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    user_id: str
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
    request_id: str = ""


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


class AsyncJobResponse(BaseModel):
    job_id: str
    status: str
    poll_url: str


def make_cache_key(text: str, model_version: str) -> str:
    payload = f"{text}:{model_version}"
    return "pred:" + hashlib.sha256(payload.encode()).hexdigest()


def make_risk_cache_key(body: RiskScoreRequest) -> str:
    payload = {
        "user_id": body.user_id,
        "transaction_amount": body.transaction_amount,
        "transaction_country": body.transaction_country,
        "home_country": body.home_country,
        "is_new_device": body.is_new_device,
        "failed_login_attempts": body.failed_login_attempts,
        "account_age_days": body.account_age_days,
        "credit_score": body.credit_score,
        "debt_to_income": body.debt_to_income,
        "chargeback_count_90d": body.chargeback_count_90d,
        "ip_reputation": body.ip_reputation,
        "model_version": body.model_version,
    }
    serialized = json.dumps(payload, sort_keys=True)
    return "risk:" + hashlib.sha256(serialized.encode()).hexdigest()


def clamp(val: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, val))


def run_inference(text: str) -> dict:
    return model.predict(text)


def run_risk_scoring(body: RiskScoreRequest) -> dict:
    country_mismatch = 1.0 if body.transaction_country.upper() != body.home_country.upper() else 0.0

    fraud_probability = clamp(
        min(body.transaction_amount / 10000.0, 1.0) * 0.35
        + min(body.chargeback_count_90d / 5.0, 1.0) * 0.30
        + (0.20 if body.is_new_device else 0.0)
        + country_mismatch * 0.15
    )

    credit_default_probability = clamp(
        (1.0 - ((body.credit_score - 300.0) / 550.0)) * 0.60
        + min(body.debt_to_income / 1.0, 1.0) * 0.30
        + (0.10 if body.account_age_days < 180 else 0.0)
    )

    cyber_anomaly_probability = clamp(
        min(body.failed_login_attempts / 10.0, 1.0) * 0.45
        + body.ip_reputation * 0.35
        + (0.20 if body.is_new_device else 0.0)
    )

    weighted_score = (
        fraud_probability * 0.45
        + credit_default_probability * 0.30
        + cyber_anomaly_probability * 0.25
    ) * 100.0
    risk_score = round(weighted_score, 2)

    if risk_score >= 75:
        decision = "block"
    elif risk_score >= 50:
        decision = "review"
    else:
        decision = "allow"

    confidence = round(clamp(0.70 + abs(risk_score - 50.0) / 50.0 * 0.28, 0.70, 0.98), 4)

    factors = []
    if body.transaction_amount >= 5000:
        factors.append("high_transaction_amount")
    if country_mismatch:
        factors.append("country_mismatch")
    if body.is_new_device:
        factors.append("new_device")
    if body.failed_login_attempts >= 3:
        factors.append("multiple_failed_logins")
    if body.chargeback_count_90d >= 2:
        factors.append("historical_chargebacks")
    if body.credit_score < 620:
        factors.append("low_credit_score")
    if body.debt_to_income > 0.5:
        factors.append("high_debt_to_income")
    if body.ip_reputation >= 0.7:
        factors.append("high_risk_ip")

    return {
        "risk_score": risk_score,
        "decision": decision,
        "confidence": confidence,
        "components": {
            "fraud_probability": round(fraud_probability, 4),
            "credit_default_probability": round(credit_default_probability, 4),
            "cyber_anomaly_probability": round(cyber_anomaly_probability, 4),
        },
        "factors": factors,
    }


@app.get("/health")
async def health():
    return {"status": "ok", "service": "inference-service"}


@app.post("/predict")
async def predict(body: PredictRequest):
    cache_key = make_cache_key(body.text, body.model_version)

    cached = await redis_client.get(cache_key)
    if cached:
        data = json.loads(cached)
        data["cached"] = True
        data["request_id"] = body.request_id
        logger.info("cache_hit", key=cache_key)
        return data

    lock_key = f"lock:{cache_key}"
    lock = redis_client.lock(lock_key, timeout=10)
    await lock.acquire(blocking=True, blocking_timeout=8)

    try:
        cached = await redis_client.get(cache_key)
        if cached:
            data = json.loads(cached)
            data["cached"] = True
            data["request_id"] = body.request_id
            return data

        start = time.time()
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(executor, run_inference, body.text)
        latency_ms = round((time.time() - start) * 1000, 2)

        response = {
            "request_id": body.request_id,
            "prediction": result["label"],
            "confidence": result["confidence"],
            "model_version": body.model_version,
            "latency_ms": latency_ms,
            "cached": False,
        }

        await redis_client.setex(cache_key, CACHE_TTL, json.dumps(response))
        logger.info("inference_complete", latency_ms=latency_ms, cached=False)
        return response

    finally:
        try:
            await lock.release()
        except Exception:
            pass


@app.post("/predict/async", response_model=AsyncJobResponse)
async def predict_async(body: PredictRequest, background_tasks: BackgroundTasks):
    job_id = str(uuid.uuid4())
    job_key = f"job:{job_id}"
    await redis_client.setex(job_key, 300, json.dumps({"status": "pending", "job_type": "predict"}))
    background_tasks.add_task(process_async_predict_job, job_id, body)
    return {"job_id": job_id, "status": "pending", "poll_url": f"/result/{job_id}"}


@app.post("/risk/score", response_model=RiskScoreResponse)
async def risk_score(body: RiskScoreRequest):
    cache_key = make_risk_cache_key(body)

    cached = await redis_client.get(cache_key)
    if cached:
        data = json.loads(cached)
        data["cached"] = True
        data["request_id"] = body.request_id
        return data

    lock_key = f"lock:{cache_key}"
    lock = redis_client.lock(lock_key, timeout=10)
    await lock.acquire(blocking=True, blocking_timeout=8)

    try:
        cached = await redis_client.get(cache_key)
        if cached:
            data = json.loads(cached)
            data["cached"] = True
            data["request_id"] = body.request_id
            return data

        start = time.time()
        loop = asyncio.get_event_loop()
        scored = await loop.run_in_executor(executor, run_risk_scoring, body)
        latency_ms = round((time.time() - start) * 1000, 2)

        response = {
            "request_id": body.request_id,
            "user_id": body.user_id,
            "model_version": body.model_version,
            "risk_score": scored["risk_score"],
            "decision": scored["decision"],
            "confidence": scored["confidence"],
            "components": scored["components"],
            "factors": scored["factors"],
            "latency_ms": latency_ms,
            "cached": False,
        }

        await redis_client.setex(cache_key, CACHE_TTL, json.dumps(response))
        logger.info(
            "risk_scored",
            user_id=body.user_id,
            risk_score=response["risk_score"],
            decision=response["decision"],
            cached=False,
            latency_ms=latency_ms,
        )
        return response

    finally:
        try:
            await lock.release()
        except Exception:
            pass


@app.post("/risk/score/async", response_model=AsyncJobResponse)
async def risk_score_async(body: RiskScoreRequest, background_tasks: BackgroundTasks):
    job_id = str(uuid.uuid4())
    job_key = f"job:{job_id}"
    await redis_client.setex(job_key, 300, json.dumps({"status": "pending", "job_type": "risk"}))
    background_tasks.add_task(process_async_risk_job, job_id, body)
    return {"job_id": job_id, "status": "pending", "poll_url": f"/result/{job_id}"}


async def process_async_predict_job(job_id: str, body: PredictRequest):
    job_key = f"job:{job_id}"
    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(executor, run_inference, body.text)
        response = {
            "status": "complete",
            "job_id": job_id,
            "job_type": "predict",
            "prediction": result["label"],
            "confidence": result["confidence"],
            "model_version": body.model_version,
        }
        await redis_client.setex(job_key, 300, json.dumps(response))
    except Exception as exc:
        await redis_client.setex(
            job_key,
            300,
            json.dumps({"status": "failed", "job_type": "predict", "error": str(exc)}),
        )


async def process_async_risk_job(job_id: str, body: RiskScoreRequest):
    job_key = f"job:{job_id}"
    try:
        loop = asyncio.get_event_loop()
        scored = await loop.run_in_executor(executor, run_risk_scoring, body)
        response = {
            "status": "complete",
            "job_id": job_id,
            "job_type": "risk",
            "request_id": body.request_id,
            "user_id": body.user_id,
            "model_version": body.model_version,
            "risk_score": scored["risk_score"],
            "decision": scored["decision"],
            "confidence": scored["confidence"],
            "components": scored["components"],
            "factors": scored["factors"],
        }
        await redis_client.setex(job_key, 300, json.dumps(response))
    except Exception as exc:
        await redis_client.setex(
            job_key,
            300,
            json.dumps({"status": "failed", "job_type": "risk", "error": str(exc)}),
        )


@app.get("/result/{job_id}")
async def get_result(job_id: str):
    job_key = f"job:{job_id}"
    data = await redis_client.get(job_key)
    if not data:
        raise HTTPException(status_code=404, detail="Job not found or expired")
    return json.loads(data)
