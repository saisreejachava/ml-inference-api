"""
Prometheus metrics — import this in main.py to expose /metrics.

Usage:
    from metrics import instrumentator
    instrumentator.instrument(app).expose(app)
"""

from prometheus_fastapi_instrumentator import Instrumentator
from prometheus_client import Counter, Histogram, Gauge

REQUEST_COUNT = Counter(
    "inference_requests_total",
    "Total prediction requests",
    ["model_version", "cached"]
)

INFERENCE_LATENCY = Histogram(
    "inference_latency_ms",
    "Inference latency in milliseconds",
    buckets=[5, 10, 25, 50, 100, 150, 200, 500, 1000]
)

CACHE_HIT_RATE = Gauge(
    "cache_hit_rate",
    "Rolling cache hit rate"
)

instrumentator = Instrumentator(
    should_group_status_codes=True,
    should_ignore_untemplated=True,
    should_respect_env_var=True,
    should_instrument_requests_inprogress=True,
    excluded_handlers=["/health", "/metrics"],
    inprogress_name="inprogress",
    inprogress_labels=True,
)
