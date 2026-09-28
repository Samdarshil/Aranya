"""
Temporal / historical-trend analysis.

Honesty note: with only a handful of observations per animal (typical for a
brand-new prototype deployment), there isn't enough sequential data to
legitimately train an LSTM/GRU. Rather than fabricate a "trained temporal
model", this module:

  1. Always computes real, simple statistical trend features (moving
     average, slope/direction, volatility) — genuinely useful and honest.
  2. Exposes `enough_data_for_sequence_model()` and a stub
     `train_or_load_sequence_model()` so that once a farm/vet has logged
     >= MIN_SEQUENCE_LENGTH_FOR_TEMPORAL_MODEL observations for an animal,
     a real PyTorch LSTM can be trained/loaded and used instead — without
     changing the UI or the rest of the pipeline.
"""

from __future__ import annotations

from typing import Any, Dict, List

import numpy as np

from backend.core.vision_config import MIN_SEQUENCE_LENGTH_FOR_TEMPORAL_MODEL


def compute_statistical_trend(risk_scores: List[float]) -> Dict[str, Any]:
    if not risk_scores:
        return {"direction": "no data", "slope": 0.0, "moving_avg": 0.0, "volatility": 0.0}

    arr = np.array(risk_scores, dtype=float)
    moving_avg = float(arr[-3:].mean()) if len(arr) >= 1 else float(arr.mean())
    volatility = float(arr.std())

    if len(arr) >= 2:
        x = np.arange(len(arr))
        slope = float(np.polyfit(x, arr, 1)[0])
    else:
        slope = 0.0

    if slope > 3:
        direction = "worsening"
    elif slope < -3:
        direction = "improving"
    else:
        direction = "stable"

    return {
        "direction": direction,
        "slope": round(slope, 2),
        "moving_avg": round(moving_avg, 1),
        "volatility": round(volatility, 1),
        "n_observations": len(arr),
    }


def enough_data_for_sequence_model(n_observations: int) -> bool:
    return n_observations >= MIN_SEQUENCE_LENGTH_FOR_TEMPORAL_MODEL


def train_or_load_sequence_model(animal_id: str, feature_sequences: List[List[float]]):
    """
    Stub for a real LSTM/GRU sequence model (PyTorch), intentionally not
    implemented here: with fewer than MIN_SEQUENCE_LENGTH_FOR_TEMPORAL_MODEL
    labelled sequential observations, training one would be meaningless
    and we do not want to fabricate a "trained model" result.

    Once enough real observations exist (per-animal or pooled across
    similar animals with proper labels), implement this to:
        1. Build sliding-window sequences from `feature_sequences`.
        2. Train a small LSTM/GRU regressor/classifier in PyTorch.
        3. Persist to models/livestock_temporal.pt.
        4. Return next-step risk prediction + confidence.
    """
    raise NotImplementedError(
        "Not enough historical data to train a real temporal model yet. "
        "Use compute_statistical_trend() until "
        "enough_data_for_sequence_model() returns True."
    )
