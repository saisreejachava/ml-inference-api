# Real-Time Risk Intelligence Platform

A containerized FastAPI microservices platform for real-time ML inference across two domains:

- FinTech: transaction fraud and credit risk
- Cybersecurity: behavioral and access anomaly signals

The system returns a unified risk score (0-100), decision (`allow`, `review`, `block`), and explainable risk factors.

## Architecture

```
Client
  │
  ▼
[API Gateway :8000]  ← auth boundary, rate limiting, request IDs, routing
  │
  ▼
[Inference Service :8001]  ← prediction + unified risk scoring + async jobs
  │
  ▼
[Redis :6379]  ← cache + async job state
```

Supporting services: Prometheus (:9090), Grafana (:3000)
Frontend: Risk dashboard (:5173)

## Quick Start

### Prerequisites
- Docker Desktop (Mac/Windows) or Docker Engine (Linux)
- Docker Compose v2+

### Start the stack

```bash
docker compose -f infra/docker-compose.yml up --build
```

### API docs

- Gateway Swagger UI: http://localhost:8000/docs
- Inference Swagger UI: http://localhost:8001/docs
- Risk Dashboard UI: http://localhost:5173

## Core Endpoints

### 1) Existing text prediction flow

```bash
curl -X POST http://localhost:8000/predict \
  -H "Content-Type: application/json" \
  -d '{"text": "This product is amazing!", "mode": "sync", "model_version": "v1"}'
```

### 2) Unified risk scoring flow

```bash
curl -X POST http://localhost:8000/risk/score \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "u-123",
    "transaction_amount": 9500,
    "transaction_country": "NG",
    "home_country": "US",
    "is_new_device": true,
    "failed_login_attempts": 5,
    "account_age_days": 30,
    "credit_score": 590,
    "debt_to_income": 0.64,
    "chargeback_count_90d": 3,
    "ip_reputation": 0.82,
    "mode": "sync",
    "model_version": "v1"
  }'
```

### 3) Async risk scoring + polling

```bash
# Submit async
curl -X POST http://localhost:8000/risk/score \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "u-123",
    "transaction_amount": 9500,
    "transaction_country": "NG",
    "home_country": "US",
    "is_new_device": true,
    "failed_login_attempts": 5,
    "account_age_days": 30,
    "credit_score": 590,
    "debt_to_income": 0.64,
    "chargeback_count_90d": 3,
    "ip_reputation": 0.82,
    "mode": "async",
    "model_version": "v1"
  }'

# Poll result
curl http://localhost:8000/result/<job_id>
```

### 4) Dashboard APIs for frontend

```bash
# Recent risk events
curl http://localhost:8000/events/recent

# Aggregate analytics for cards/charts
curl http://localhost:8000/analytics
```

WebSocket stream for live table updates:

`ws://localhost:8000/ws/live-events`

## Risk Model (V1)

The unified score combines three component probabilities:

- `fraud_probability`
- `credit_default_probability`
- `cyber_anomaly_probability`

Weighted aggregation:

- fraud: 45%
- credit: 30%
- cyber: 25%

Decision thresholds:

- `allow`: < 50
- `review`: 50-74.99
- `block`: >= 75

## Run Load Tests

```bash
pip install locust
locust -f tests/load/locustfile.py --host=http://localhost:8000
```

The load suite includes:

- `/predict` sync + async
- `/risk/score` sync + async

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `REDIS_URL` | `redis://redis:6379` | Redis connection string |
| `CACHE_TTL` | `1800` | Cache TTL in seconds |
| `INFERENCE_SERVICE_URL` | `http://inference-service:8001` | Internal gateway target |
