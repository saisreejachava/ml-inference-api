"""
MockMLModel — drop-in placeholder for any real sklearn / HuggingFace / ONNX model.

To swap in a real model:
  1. Replace `load()` with your model loading logic (joblib, torch.load, etc.)
  2. Replace `predict()` with your inference logic.
  3. Keep the return shape: {"label": str, "confidence": float}
"""

import random
import time


LABELS = ["positive", "negative", "neutral"]


class MockMLModel:
    def __init__(self):
        self.model = None
        self.version = "v1"

    def load(self):
        """Simulate model loading (e.g., from disk or registry)."""
        time.sleep(0.5)  # simulate slow load once at startup
        self.model = {"loaded": True}

    def predict(self, text: str) -> dict:
        """
        Simulate CPU-bound inference with slight processing delay.
        Replace with: return {"label": self.model.predict([text])[0], "confidence": ...}
        """
        time.sleep(0.02)  # ~20ms simulated inference time
        label = LABELS[len(text) % 3]
        confidence = round(random.uniform(0.75, 0.99), 4)
        return {"label": label, "confidence": confidence}
