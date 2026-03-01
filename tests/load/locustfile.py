"""
Load test with Locust.

Install: pip install locust
Run:     locust -f locustfile.py --host=http://localhost:8000

Then open http://localhost:8089 and set:
  - Number of users: 500
  - Spawn rate: 50

Or headless (CI mode):
  locust -f tests/load/locustfile.py --host=http://localhost:8000 \
         --users 500 --spawn-rate 50 --run-time 60s --headless \
         --csv=benchmarks/results
"""

import random
from locust import HttpUser, between, task

SAMPLE_TEXTS = [
    "This product is absolutely amazing, I love it!",
    "Terrible experience, would not recommend.",
    "It was okay, nothing special about it.",
    "Best purchase I've made all year.",
    "Completely broken on arrival, very disappointed.",
]

RISK_SCENARIOS = [
    {
        "user_id": "user-low-risk",
        "transaction_amount": 120.0,
        "transaction_country": "US",
        "home_country": "US",
        "is_new_device": False,
        "failed_login_attempts": 0,
        "account_age_days": 720,
        "credit_score": 760,
        "debt_to_income": 0.21,
        "chargeback_count_90d": 0,
        "ip_reputation": 0.05,
        "mode": "sync",
        "model_version": "v1",
    },
    {
        "user_id": "user-high-risk",
        "transaction_amount": 9800.0,
        "transaction_country": "NG",
        "home_country": "US",
        "is_new_device": True,
        "failed_login_attempts": 6,
        "account_age_days": 45,
        "credit_score": 580,
        "debt_to_income": 0.68,
        "chargeback_count_90d": 3,
        "ip_reputation": 0.86,
        "mode": "sync",
        "model_version": "v1",
    },
]


class InferenceUser(HttpUser):
    wait_time = between(0.1, 0.5)

    @task(6)
    def predict_sync(self):
        self.client.post(
            "/predict",
            json={
                "text": random.choice(SAMPLE_TEXTS),
                "mode": "sync",
                "model_version": "v1",
            },
            name="/predict [sync]",
        )

    @task(2)
    def predict_async(self):
        resp = self.client.post(
            "/predict",
            json={
                "text": random.choice(SAMPLE_TEXTS),
                "mode": "async",
                "model_version": "v1",
            },
            name="/predict [async]",
        )
        if resp.status_code == 202:
            job_id = resp.json().get("job_id")
            if job_id:
                self.client.get(f"/result/{job_id}", name="/result/[job_id]")

    @task(3)
    def risk_score_sync(self):
        self.client.post(
            "/risk/score",
            json=random.choice(RISK_SCENARIOS),
            name="/risk/score [sync]",
        )

    @task(1)
    def risk_score_async(self):
        payload = dict(random.choice(RISK_SCENARIOS))
        payload["mode"] = "async"
        resp = self.client.post("/risk/score", json=payload, name="/risk/score [async]")
        if resp.status_code == 202:
            job_id = resp.json().get("job_id")
            if job_id:
                self.client.get(f"/result/{job_id}", name="/result/[job_id]")

    @task(1)
    def health_check(self):
        self.client.get("/health")
