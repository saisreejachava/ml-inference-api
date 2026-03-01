# Benchmark Results

## Test Environment
- Tool: Locust
- Duration: 60 seconds
- Users: 500 concurrent
- Spawn rate: 50/s
- Host: http://localhost:8000

## Results Summary Template

| Metric             | Baseline | Tuned | Improvement |
|--------------------|----------|-------|-------------|
| p50 latency        |          |       |             |
| p95 latency        |          |       |             |
| p99 latency        |          |       |             |
| Throughput (RPS)   |          |       |             |
| Cache hit rate     |          |       |             |
| Error rate         |          |       |             |

## How to Reproduce

```bash
# 1) Start the platform
cd /Users/chavasaisreeja/Downloads/ml-inference-api
docker compose -f infra/docker-compose.yml up --build -d

# 2) Warm cache with risk calls
for i in {1..20}; do
  curl -s -X POST http://localhost:8000/risk/score \
    -H "Content-Type: application/json" \
    -d '{
      "user_id": "warmup",
      "transaction_amount": 200,
      "transaction_country": "US",
      "home_country": "US",
      "is_new_device": false,
      "failed_login_attempts": 0,
      "account_age_days": 400,
      "credit_score": 740,
      "debt_to_income": 0.22,
      "chargeback_count_90d": 0,
      "ip_reputation": 0.05,
      "mode": "sync",
      "model_version": "v1"
    }' > /dev/null
done

# 3) Run headless load test
locust -f tests/load/locustfile.py --host=http://localhost:8000 \
  --users 500 --spawn-rate 50 --run-time 60s --headless \
  --csv=benchmarks/results
```
